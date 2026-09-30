"""Assistance orchestration: ASK > UNDERSTAND > ASSESS > MATCH > CONNECT > CARE > RESOLVE > LEARN.

All state changes go through this module so lifecycle rules, history, notifications, trust events
and credits stay consistent. Acceptance uses a conditional UPDATE on `filled_slots` so simultaneous
acceptances can never over-fill a request (works on PostgreSQL row locks and SQLite write locks).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Assignment, HelpRequest, RecipientState, RelationshipPreference, ReqStatus, RequestCategory,
    RequestRecipient, RequestStatusHistory, Review, User, utcnow,
)
from . import circle as circle_svc
from . import credits as credits_svc
from . import nlu, smartmatch
from . import trust as trust_svc
from .geo import eta_minutes, haversine_km
from .realtime import emit, notify

S = ReqStatus


class FlowError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


ALLOWED: dict[str, set[str]] = {
    S.CREATED: {S.ANALYZING, S.MATCHING, S.CANCELLED},
    S.ANALYZING: {S.MATCHING, S.CANCELLED},
    S.MATCHING: {S.TRUSTED_CIRCLE, S.HELPERS_NOTIFIED, S.ACCEPTED, S.ESCALATED, S.CANCELLED, S.EXPIRED},
    S.TRUSTED_CIRCLE: {S.ESCALATED, S.MATCHING, S.ACCEPTED, S.HELPERS_NOTIFIED, S.CANCELLED, S.EXPIRED},
    S.ESCALATED: {S.MATCHING, S.HELPERS_NOTIFIED, S.ACCEPTED, S.CANCELLED, S.EXPIRED},
    S.HELPERS_NOTIFIED: {S.ASSIGNED, S.ACCEPTED, S.MATCHING, S.ESCALATED, S.CANCELLED, S.EXPIRED},
    S.ASSIGNED: {S.ACCEPTED, S.MATCHING, S.CANCELLED},
    S.ACCEPTED: {S.ON_THE_WAY, S.IN_PROGRESS, S.MATCHING, S.CANCELLED},
    S.ON_THE_WAY: {S.IN_PROGRESS, S.MATCHING, S.CANCELLED},
    S.IN_PROGRESS: {S.COMPLETED, S.CANCELLED},
    S.COMPLETED: {S.RATED},
}
for _st in S.OPEN:  # a helper may accept from any open state (e.g. while still waiting on the circle)
    ALLOWED[_st].add(S.ASSIGNED)
CLAIMABLE = S.OPEN + (S.ASSIGNED, S.ACCEPTED)


def aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def first_name(u: User) -> str:
    return u.name.split()[0] if u.name else "A neighbour"


def transition(db: Session, req: HelpRequest, to: str, actor_id: int | None = None, note: str | None = None) -> None:
    frm = req.status
    if frm == to:
        return
    if to not in ALLOWED.get(frm, set()):
        raise FlowError(f"Cannot move request from {frm} to {to}", 409)
    req.status = to
    req.updated_at = utcnow()
    db.add(RequestStatusHistory(request_id=req.id, from_status=frm, to_status=to, actor_id=actor_id, note=note))
    for uid in participants(db, req):
        emit(db, uid, {"type": "request_update", "request_id": req.id, "status": to})
    db.flush()


def participants(db: Session, req: HelpRequest) -> set[int]:
    ids = {req.requester_id}
    ids |= set(db.scalars(select(Assignment.helper_id).where(Assignment.request_id == req.id)))
    ids |= set(db.scalars(select(RequestRecipient.user_id).where(
        RequestRecipient.request_id == req.id, RequestRecipient.state.in_([RecipientState.NOTIFIED, RecipientState.ACCEPTED]))))
    return ids


# ---- creation ------------------------------------------------------------------------------
def create_request(db: Session, user: User, *, text: str, lat: float | None, lng: float | None,
                   share_location: bool = False, routing_mode: str | None = None, custom_ids: list[int] | None = None,
                   overrides: dict | None = None, reveal_relationship: bool = False, force_urgency: str | None = None) -> HelpRequest:
    s = get_settings()
    overrides = overrides or {}
    u = nlu.understand(text)
    cat = overrides.get("category") or u.category
    if db.get(RequestCategory, cat) is None:
        raise FlowError("Unknown category")
    urgency = force_urgency or overrides.get("urgency") or u.urgency
    # users may raise urgency but can never lower it below what the safety floor detected
    floor = nlu.rule_understand(text).urgency if not force_urgency else urgency
    order = ("normal", "urgent", "critical")
    if order.index(urgency) < order.index(floor) and floor == "critical":
        urgency = floor
    if lat is None and user.lat is not None and user.profile and user.profile.location_sharing != "off":
        lat, lng = user.lat, user.lng
    mode = routing_mode or ("circle_first" if (user.profile and user.profile.prefer_trusted_circle) else "community")
    req = HelpRequest(
        requester_id=user.id, raw_text=text, title=overrides.get("title") or u.title, description=overrides.get("description") or u.description,
        category=cat, urgency=urgency, skills_required=overrides.get("skills_required") or u.skills_required or [],
        num_helpers=overrides.get("num_helpers") or u.num_helpers, time_requirement=overrides.get("time_requirement") or u.time_requirement,
        lat=lat, lng=lng, location_shared=bool(share_location and lat is not None), routing_mode=mode,
        reveal_relationship=reveal_relationship, nlu_source=u.source,
        expires_at=utcnow() + timedelta(minutes=s.request_expiry_minutes), status=S.CREATED,
    )
    db.add(req)
    db.flush()
    db.add(RequestStatusHistory(request_id=req.id, from_status=None, to_status=S.CREATED, actor_id=user.id))
    notify(db, user.id, "request_created", "Request created", req.title, {"request_id": req.id})
    transition(db, req, S.ANALYZING, user.id)
    transition(db, req, S.MATCHING, user.id)
    if req.urgency == "critical":
        from . import care  # local import: care depends on orchestrator helpers

        care.ensure_incident(db, req)
    dispatch(db, req, custom_ids=custom_ids)
    return req


# ---- notification of recipients ------------------------------------------------------------
def _location_hint(req: HelpRequest, helper: User) -> str:
    if req.lat is None or helper.lat is None:
        return "Location not shared"
    d = haversine_km(req.lat, req.lng, helper.lat, helper.lng)
    return f"about {d * 1000:.0f} m away" if d < 1 else f"about {d:.1f} km away"


def notify_recipient(db: Session, req: HelpRequest, helper: User, channel: str, match_score: float | None = None) -> bool:
    if db.scalar(select(RequestRecipient.id).where(RequestRecipient.request_id == req.id, RequestRecipient.user_id == helper.id)):
        return False
    db.add(RequestRecipient(request_id=req.id, user_id=helper.id, channel=channel, match_score=match_score))
    trust_svc.record_event(db, helper.id, "notified", category=req.category, request_id=req.id)
    requester = db.get(User, req.requester_id)
    who = first_name(requester)
    hint = _location_hint(req, helper)
    if channel == "circle":
        kind = "trusted_request"
        title = f"{'CRITICAL: ' if req.urgency == 'critical' else 'Urgent: ' if req.urgency == 'urgent' else ''}{who} needs help"
    else:
        kind = "urgent_request" if req.urgency != "normal" else "new_request"
        title = f"{'URGENT: ' if req.urgency != 'normal' else ''}{req.title}"
    notify(db, helper.id, kind, title, f"{req.title} - {hint}",
           {"request_id": req.id, "urgency": req.urgency, "channel": channel})
    return True


def _recipient_ids(db: Session, req: HelpRequest) -> set[int]:
    return set(db.scalars(select(RequestRecipient.user_id).where(RequestRecipient.request_id == req.id)))


def _notify_circle(db: Session, req: HelpRequest, requester: User) -> list[circle_svc.CircleMember]:
    members = circle_svc.circle_members(db, requester, lat=req.lat, lng=req.lng)
    for m in members:
        notify_recipient(db, req, m.user, "circle")
    if members:
        notify(db, requester.id, "circle_notified", "Trusted Circle notified",
               f"Asked {len(members)} trusted contact{'s' if len(members) != 1 else ''} nearby.", {"request_id": req.id})
    return members


def _notify_community(db: Session, req: HelpRequest, count: int, *, exclude: set[int] | None = None) -> int:
    ex = (exclude or set()) | _recipient_ids(db, req)
    ranked = smartmatch.rank(db, req, limit=count, radius_km=req.search_radius_km, exclude_ids=ex)
    n = 0
    for r in ranked:
        if notify_recipient(db, req, r.helper, "circle" if r.in_circle else "community", r.match_score):
            n += 1
    return n


# ---- dispatch (routing policy) -------------------------------------------------------------
def dispatch(db: Session, req: HelpRequest, *, custom_ids: list[int] | None = None) -> None:
    s = get_settings()
    requester = db.get(User, req.requester_id)
    prefs = db.get(RelationshipPreference, requester.id)
    req.search_radius_km = req.search_radius_km or s.community_radius_km

    if req.urgency == "critical":
        use_circle = prefs.prefer_circle_for_critical if prefs else True
        members = _notify_circle(db, req, requester) if use_circle else []
        n = _notify_community(db, req, s.broadcast_size)
        _after_dispatch(db, req, requester, bool(members) or n > 0, circle_wait=False)
        return

    if req.urgency == "urgent":
        members = _notify_circle(db, req, requester) if req.routing_mode != "community" else []
        n = _notify_community(db, req, s.broadcast_size)
        _after_dispatch(db, req, requester, bool(members) or n > 0, circle_wait=False)
        return

    # NORMAL
    if req.routing_mode == "custom":
        ids = custom_ids or []
        allowed = {m.user.id for m in circle_svc.circle_members(db, requester, lat=req.lat, lng=req.lng, nearby_only=False)}
        allowed |= {u.id for u in smartmatch.find_candidates(db, req)}
        bad = [i for i in ids if i not in allowed]
        if not ids or bad:
            raise FlowError("Custom recipients must be people in your Trusted Circle or nearby available helpers")
        for uid in ids:
            notify_recipient(db, req, db.get(User, uid), "circle" if circle_svc.in_circle(db, requester.id, uid) else "community")
        _after_dispatch(db, req, requester, True, circle_wait=False)
        return

    if req.routing_mode == "circle_first":
        members = _notify_circle(db, req, requester)
        if members:
            window = (prefs.circle_window_override_s if prefs and prefs.circle_window_override_s is not None else s.circle_window("normal"))
            req.circle_deadline = utcnow() + timedelta(seconds=window)
            transition(db, req, S.TRUSTED_CIRCLE, requester.id, f"asked {len(members)} trusted contact(s)")
            return
        notify(db, requester.id, "circle_unavailable", "No trusted contacts nearby",
               "None of your Trusted Circle can be reached nearby. Finding community help.", {"request_id": req.id})

    n = _notify_community(db, req, s.normal_notify_count)
    _after_dispatch(db, req, requester, n > 0, circle_wait=False)


def _after_dispatch(db: Session, req: HelpRequest, requester: User, any_notified: bool, circle_wait: bool) -> None:
    if any_notified:
        transition(db, req, S.HELPERS_NOTIFIED, requester.id)
        notify(db, requester.id, "matching_started", "Finding help nearby", "Suitable helpers have been notified.", {"request_id": req.id})
    else:
        _alert_unmatched(db, req)


def _alert_unmatched(db: Session, req: HelpRequest) -> None:
    if req.unmatched_alerted:
        return
    req.unmatched_alerted = True
    notify(db, req.requester_id, "no_helpers", "No helpers available yet",
           "We'll keep looking and widen the search.", {"request_id": req.id})
    if req.urgency != "normal":
        for admin in db.scalars(select(User).where(User.role == "admin")):
            notify(db, admin.id, "unmatched_urgent", f"Unmatched {req.urgency} request", req.title, {"request_id": req.id})


# ---- escalation ----------------------------------------------------------------------------
def escalate_to_community(db: Session, req: HelpRequest, actor_id: int | None = None, reason: str = "circle_unavailable") -> None:
    if req.status not in (S.TRUSTED_CIRCLE, S.MATCHING, S.ESCALATED, S.HELPERS_NOTIFIED):
        raise FlowError("Request is not waiting on the Trusted Circle", 409)
    s = get_settings()
    for rec in db.scalars(select(RequestRecipient).where(
            RequestRecipient.request_id == req.id, RequestRecipient.channel == "circle", RequestRecipient.state == RecipientState.NOTIFIED)):
        rec.state = RecipientState.EXPIRED
        notify(db, rec.user_id, "request_withdrawn", "Request moved on", "It has been passed to other helpers.", {"request_id": req.id})
    req.escalated_at = utcnow()
    req.circle_deadline = None
    if req.status == S.TRUSTED_CIRCLE:
        transition(db, req, S.ESCALATED, actor_id, reason)
    notify(db, req.requester_id, "escalated", "Finding a community helper",
           "Nobody from your trusted circle is available. I'll find a nearby community helper.", {"request_id": req.id})
    n = _notify_community(db, req, s.normal_notify_count if req.urgency == "normal" else s.broadcast_size)
    if n:
        transition(db, req, S.HELPERS_NOTIFIED, actor_id)
    else:
        if req.status == S.ESCALATED:
            transition(db, req, S.MATCHING, actor_id, "no community helpers yet")
        _alert_unmatched(db, req)


def process_timeouts(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Idempotent maintenance sweep: circle windows, helper response windows, widening, expiry."""
    s = get_settings()
    now = now or utcnow()
    stats = {"escalated": 0, "expired_requests": 0, "expired_recipients": 0, "widened": 0}

    # 1. expire open requests
    for req in db.scalars(select(HelpRequest).where(HelpRequest.status.in_(S.OPEN), HelpRequest.expires_at <= now)):
        _expire(db, req)
        stats["expired_requests"] += 1

    # 2. circle windows elapsed -> escalate
    for req in db.scalars(select(HelpRequest).where(HelpRequest.status == S.TRUSTED_CIRCLE, HelpRequest.circle_deadline <= now)):
        escalate_to_community(db, req, None, "circle_window_elapsed")
        stats["escalated"] += 1

    # 3. community helper response windows elapsed
    open_ids = select(HelpRequest.id).where(HelpRequest.status == S.HELPERS_NOTIFIED)
    recs = db.scalars(select(RequestRecipient).where(RequestRecipient.request_id.in_(open_ids), RequestRecipient.state == RecipientState.NOTIFIED)).all()
    for rec in recs:
        req = db.get(HelpRequest, rec.request_id)
        if aware(rec.notified_at) + timedelta(seconds=s.helper_window(req.urgency)) <= now:
            rec.state = RecipientState.EXPIRED
            stats["expired_recipients"] += 1
    db.flush()

    # 4. nobody left to answer -> next batch / widen radius
    for req in db.scalars(select(HelpRequest).where(HelpRequest.status == S.HELPERS_NOTIFIED)):
        pending = db.scalar(select(RequestRecipient.id).where(RequestRecipient.request_id == req.id, RequestRecipient.state == RecipientState.NOTIFIED))
        if pending is None and req.filled_slots < req.num_helpers:
            if _next_batch(db, req):
                stats["widened"] += 1
    return stats


def _next_batch(db: Session, req: HelpRequest) -> bool:
    s = get_settings()
    count = s.normal_notify_count if req.urgency == "normal" else s.broadcast_size
    n = _notify_community(db, req, count)
    if n == 0:
        current = req.search_radius_km or s.community_radius_km
        if current < s.max_search_radius_km:
            req.search_radius_km = min(s.max_search_radius_km, current * 2)
            n = _notify_community(db, req, count)
    if n == 0:
        _alert_unmatched(db, req)
        return False
    return True


def _expire(db: Session, req: HelpRequest) -> None:
    for rec in db.scalars(select(RequestRecipient).where(RequestRecipient.request_id == req.id, RequestRecipient.state == RecipientState.NOTIFIED)):
        rec.state = RecipientState.EXPIRED
    transition(db, req, S.EXPIRED, None, "no helper found in time")
    notify(db, req.requester_id, "request_expired", "Request expired", f"No helper was found for: {req.title}", {"request_id": req.id})


# ---- helper responses ----------------------------------------------------------------------
def helper_accept(db: Session, req_id: int, helper: User) -> Assignment:
    req = db.get(HelpRequest, req_id)
    if req is None:
        raise FlowError("Request not found", 404)
    rec = db.scalar(select(RequestRecipient).where(RequestRecipient.request_id == req_id, RequestRecipient.user_id == helper.id))
    if rec is None:
        raise FlowError("Request not found", 404)  # not notified => cannot even learn it exists
    if rec.state == RecipientState.ACCEPTED:
        raise FlowError("You already accepted this request", 409)
    if rec.state in (RecipientState.CANCELLED, RecipientState.EXPIRED, RecipientState.DECLINED):
        # an expired circle member may still help while the request is open
        if not (rec.state == RecipientState.EXPIRED and req.status in CLAIMABLE):
            raise FlowError("This request is no longer available to you", 409)
    if req.requester_id == helper.id:
        raise FlowError("You cannot accept your own request", 400)

    # atomic slot claim: only one of N simultaneous acceptances can take the last slot
    res = db.execute(update(HelpRequest).where(
        HelpRequest.id == req_id, HelpRequest.filled_slots < HelpRequest.num_helpers, HelpRequest.status.in_(CLAIMABLE),
    ).values(filled_slots=HelpRequest.filled_slots + 1).execution_options(synchronize_session=False))
    if res.rowcount != 1:
        raise FlowError("Someone else already accepted this request", 409)

    db.refresh(req)
    now = utcnow()
    d = haversine_km(req.lat, req.lng, helper.lat, helper.lng) if (req.lat is not None and helper.lat is not None) else None
    eta = eta_minutes(d) if d is not None else None
    asg = Assignment(request_id=req_id, helper_id=helper.id, channel=rec.channel, eta_minutes=eta,
                     distance_km=round(d, 2) if d is not None else None, accepted_at=now)
    db.add(asg)
    rec.state = RecipientState.ACCEPTED
    rec.responded_at = now
    secs = max(0.0, (now - aware(rec.notified_at)).total_seconds())
    trust_svc.record_event(db, helper.id, "responded", category=req.category, request_id=req_id, value=secs)
    trust_svc.record_event(db, helper.id, "accepted", category=req.category, request_id=req_id)
    db.flush()

    if req.status in S.OPEN:
        transition(db, req, S.ASSIGNED, helper.id)
        transition(db, req, S.ACCEPTED, helper.id)
    if req.filled_slots >= req.num_helpers:
        _withdraw_remaining(db, req)

    reqr = db.get(User, req.requester_id)
    label = circle_svc.helper_label(db, reqr, helper.id, req.reveal_relationship)
    notify(db, req.requester_id, "helper_accepted", f"{helper.name} accepted" if rec.channel == "circle" or req.reveal_relationship else "A helper accepted",
           f"{label}" + (f" - ETA {eta:.0f} min" if eta else ""),
           {"request_id": req_id, "helper_id": helper.id, "eta_minutes": eta, "distance_km": asg.distance_km})
    if req.incident_id:
        from . import care
        care.on_helper_assigned(db, req, asg)
    return asg


def _withdraw_remaining(db: Session, req: HelpRequest) -> None:
    for rec in db.scalars(select(RequestRecipient).where(RequestRecipient.request_id == req.id, RequestRecipient.state == RecipientState.NOTIFIED)):
        rec.state = RecipientState.CANCELLED
        notify(db, rec.user_id, "request_filled", "Help is already on the way", "Someone else accepted this request. Thank you!", {"request_id": req.id})


def helper_decline(db: Session, req_id: int, helper: User) -> None:
    req = db.get(HelpRequest, req_id)
    rec = db.scalar(select(RequestRecipient).where(RequestRecipient.request_id == req_id, RequestRecipient.user_id == helper.id))
    if req is None or rec is None:
        raise FlowError("Request not found", 404)
    if rec.state != RecipientState.NOTIFIED:
        raise FlowError("Nothing to decline", 409)
    now = utcnow()
    rec.state = RecipientState.DECLINED
    rec.responded_at = now
    trust_svc.record_event(db, helper.id, "responded", category=req.category, request_id=req_id,
                           value=max(0.0, (now - aware(rec.notified_at)).total_seconds()))
    trust_svc.record_event(db, helper.id, "declined", category=req.category, request_id=req_id)
    db.flush()
    if req.status == S.TRUSTED_CIRCLE:
        pending = db.scalar(select(RequestRecipient.id).where(
            RequestRecipient.request_id == req_id, RequestRecipient.state == RecipientState.NOTIFIED))
        if pending is None:  # every trusted contact declined: don't make the requester wait out the window
            escalate_to_community(db, req, None, "all_circle_declined")


# ---- progress / completion -----------------------------------------------------------------
def _assignment_for(db: Session, req_id: int, helper_id: int) -> Assignment:
    a = db.scalar(select(Assignment).where(Assignment.request_id == req_id, Assignment.helper_id == helper_id, Assignment.status.in_(["ACTIVE", "ARRIVED"])))
    if a is None:
        raise FlowError("You are not assigned to this request", 403)
    return a


def helper_progress(db: Session, req: HelpRequest, helper: User, to: str) -> None:
    a = _assignment_for(db, req.id, helper.id)
    if to == S.ON_THE_WAY:
        if req.status == S.ACCEPTED:
            transition(db, req, S.ON_THE_WAY, helper.id)
        notify(db, req.requester_id, "helper_on_the_way", f"{helper.name} is on the way",
               f"ETA {a.eta_minutes:.0f} min" if a.eta_minutes else "", {"request_id": req.id, "eta_minutes": a.eta_minutes})
    elif to == S.IN_PROGRESS:
        a.status, a.arrived_at = "ARRIVED", utcnow()
        if req.status in (S.ACCEPTED, S.ON_THE_WAY):
            transition(db, req, S.IN_PROGRESS, helper.id)
        notify(db, req.requester_id, "helper_arrived", f"{helper.name} has arrived", "", {"request_id": req.id})
        if req.incident_id:
            from . import care
            care.on_helper_arrived(db, req)
    else:
        raise FlowError("Invalid progress status")


def helper_withdraw(db: Session, req: HelpRequest, helper: User) -> None:
    a = _assignment_for(db, req.id, helper.id)
    a.status = "CANCELLED"
    trust_svc.record_event(db, helper.id, "cancelled", category=req.category, request_id=req.id)
    db.execute(update(HelpRequest).where(HelpRequest.id == req.id).values(filled_slots=HelpRequest.filled_slots - 1).execution_options(synchronize_session=False))
    db.refresh(req)
    notify(db, req.requester_id, "helper_withdrew", f"{helper.name} can no longer help", "Finding someone else.", {"request_id": req.id})
    if req.status in (S.ACCEPTED, S.ON_THE_WAY, S.ASSIGNED) and req.filled_slots == 0:
        transition(db, req, S.MATCHING, helper.id, "helper withdrew")
        if not _next_batch(db, req):
            pass
        else:
            transition(db, req, S.HELPERS_NOTIFIED, helper.id)
    trust_svc.refresh_trust(db, helper.id)


def cancel(db: Session, req: HelpRequest, actor: User) -> None:
    if req.requester_id != actor.id and actor.role != "admin":
        raise FlowError("Only the requester can cancel this request", 403)
    if req.status in S.TERMINAL:
        raise FlowError(f"Request is already {req.status.lower()}", 409)
    for rec in db.scalars(select(RequestRecipient).where(RequestRecipient.request_id == req.id, RequestRecipient.state == RecipientState.NOTIFIED)):
        rec.state = RecipientState.CANCELLED
        notify(db, rec.user_id, "request_cancelled", "Request cancelled", req.title, {"request_id": req.id})
    for a in db.scalars(select(Assignment).where(Assignment.request_id == req.id, Assignment.status.in_(["ACTIVE", "ARRIVED"]))):
        a.status = "CANCELLED"
        notify(db, a.helper_id, "request_cancelled", "Request cancelled", f"{req.title} was cancelled by the requester.", {"request_id": req.id})
    transition(db, req, S.CANCELLED, actor.id)
    if req.incident_id:
        from . import care
        care.on_request_closed(db, req, "CANCELLED")


def complete(db: Session, req: HelpRequest, actor: User) -> None:
    if req.requester_id != actor.id and actor.role != "admin":
        raise FlowError("Only the requester can mark this request complete", 403)
    if req.status not in (S.ACCEPTED, S.ON_THE_WAY, S.IN_PROGRESS):
        raise FlowError(f"Cannot complete a request that is {req.status.lower()}", 409)
    s = get_settings()
    if req.status != S.IN_PROGRESS:
        transition(db, req, S.IN_PROGRESS, actor.id)
    transition(db, req, S.COMPLETED, actor.id)
    req.completed_at = utcnow()
    for a in db.scalars(select(Assignment).where(Assignment.request_id == req.id, Assignment.status.in_(["ACTIVE", "ARRIVED"]))):
        a.status, a.completed_at = "DONE", req.completed_at
        credits_svc.earn(db, a.helper_id, s.credit_reward_per_help, req.id, req.requester_id)
        credits_svc.spend_clamped(db, req.requester_id, s.credit_cost_per_help, req.id, a.helper_id)
        trust_svc.record_event(db, a.helper_id, "completed", category=req.category, request_id=req.id, counterparty_id=req.requester_id)
        trust_svc.refresh_trust(db, a.helper_id)
        notify(db, a.helper_id, "request_completed", "Thank you for helping",
               f"+{s.credit_reward_per_help} Help Credits for: {req.title}", {"request_id": req.id})
    notify(db, req.requester_id, "request_completed", "Request completed", "Please rate your helper.", {"request_id": req.id})
    if req.incident_id:
        from . import care
        care.on_request_closed(db, req, "RESOLVED")


def report_no_show(db: Session, req: HelpRequest, actor: User, helper_id: int) -> None:
    if req.requester_id != actor.id:
        raise FlowError("Only the requester can report a no-show", 403)
    a = db.scalar(select(Assignment).where(Assignment.request_id == req.id, Assignment.helper_id == helper_id, Assignment.status == "ACTIVE"))
    if a is None:
        raise FlowError("No active assignment for that helper", 404)
    a.status = "NO_SHOW"
    trust_svc.record_event(db, helper_id, "no_show", category=req.category, request_id=req.id)
    trust_svc.refresh_trust(db, helper_id)
    db.execute(update(HelpRequest).where(HelpRequest.id == req.id).values(filled_slots=HelpRequest.filled_slots - 1).execution_options(synchronize_session=False))
    db.refresh(req)
    if req.filled_slots == 0 and req.status in (S.ACCEPTED, S.ON_THE_WAY):
        transition(db, req, S.MATCHING, actor.id, "no-show")
        if _next_batch(db, req):
            transition(db, req, S.HELPERS_NOTIFIED, actor.id)


def rate(db: Session, req: HelpRequest, actor: User, helper_id: int, rating: int, comment: str) -> Review:
    if req.requester_id != actor.id:
        raise FlowError("Only the requester can rate helpers", 403)
    if req.status not in (S.COMPLETED, S.RATED):
        raise FlowError("You can rate after the request is completed", 409)
    done = db.scalar(select(Assignment.id).where(Assignment.request_id == req.id, Assignment.helper_id == helper_id, Assignment.status == "DONE"))
    if done is None:
        raise FlowError("That user did not help with this request", 400)
    if db.scalar(select(Review.id).where(Review.request_id == req.id, Review.reviewer_id == actor.id, Review.reviewee_id == helper_id)):
        raise FlowError("You already rated this helper", 409)
    rv = Review(request_id=req.id, reviewer_id=actor.id, reviewee_id=helper_id, rating=rating, comment=comment[:1000], category=req.category)
    db.add(rv)
    db.flush()
    if req.status == S.COMPLETED:
        transition(db, req, S.RATED, actor.id)
    trust_svc.refresh_trust(db, helper_id)
    return rv


# ---- explicit actions from the requester ---------------------------------------------------
def refresh_request(db: Session, req: HelpRequest, now: datetime | None = None) -> None:
    """Lazy per-request maintenance so state is correct even if the background sweeper is delayed."""
    now = now or utcnow()
    if req.status in S.OPEN and req.expires_at and aware(req.expires_at) <= now:
        _expire(db, req)
    elif req.status == S.TRUSTED_CIRCLE and req.circle_deadline and aware(req.circle_deadline) <= now:
        escalate_to_community(db, req, None, "circle_window_elapsed")


def ask_circle(db: Session, req: HelpRequest, actor: User, recipient_ids: list[int] | None = None) -> int:
    if req.requester_id != actor.id:
        raise FlowError("Only the requester can do this", 403)
    if req.status not in S.OPEN:
        raise FlowError(f"Request is {req.status.lower()}", 409)
    requester = db.get(User, req.requester_id)
    members = circle_svc.circle_members(db, requester, lat=req.lat, lng=req.lng)
    if recipient_ids is not None:
        allowed = {m.user.id for m in members}
        if set(recipient_ids) - allowed:
            raise FlowError("You can only ask people who are in your Trusted Circle and reachable", 400)
        members = [m for m in members if m.user.id in set(recipient_ids)]
    if not members:
        raise FlowError("No reachable Trusted Circle members nearby", 409)
    n = 0
    for m in members:
        if notify_recipient(db, req, m.user, "circle"):
            n += 1
            continue
        existing = db.scalar(select(RequestRecipient).where(RequestRecipient.request_id == req.id, RequestRecipient.user_id == m.user.id))
        if existing and existing.state == RecipientState.NOTIFIED:  # already asked via community: now also counts as circle
            existing.channel = "circle"
            n += 1
    req.routing_mode = "circle_first"
    if req.urgency == "normal" and req.status in (S.MATCHING, S.ESCALATED, S.CREATED) and n:
        s = get_settings()
        prefs = db.get(RelationshipPreference, requester.id)
        window = prefs.circle_window_override_s if prefs and prefs.circle_window_override_s is not None else s.circle_window("normal")
        req.circle_deadline = utcnow() + timedelta(seconds=window)
        transition(db, req, S.TRUSTED_CIRCLE, actor.id, "asked trusted circle")
    if n:
        notify(db, requester.id, "circle_notified", "Trusted Circle notified", f"Asked {n} trusted contact(s).", {"request_id": req.id})
    return n


def invite_helper(db: Session, req: HelpRequest, actor: User, helper_id: int) -> None:
    """Requester hand-picks a helper from the SmartMatch list."""
    if req.requester_id != actor.id:
        raise FlowError("Only the requester can do this", 403)
    if req.status not in S.OPEN:
        raise FlowError(f"Request is {req.status.lower()}", 409)
    ranked = {r.helper.id: r for r in smartmatch.rank(db, req, limit=50, radius_km=req.search_radius_km)}
    r = ranked.get(helper_id)
    if r is None:
        raise FlowError("That helper is not currently a suitable match", 400)
    if not notify_recipient(db, req, r.helper, "circle" if r.in_circle else "community", r.match_score):
        raise FlowError("That helper was already asked", 409)
    if req.status in (S.MATCHING, S.ESCALATED):
        transition(db, req, S.HELPERS_NOTIFIED, actor.id, "requester chose helper")
