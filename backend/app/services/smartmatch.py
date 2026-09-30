"""SmartMatch: ranks helpers by contextual suitability for ONE request right now.

Match score (suitability) and trust score (reliability) are separate outputs. Relationship (Trusted
Circle) is a third, separate input: it is a weighted *signal* the requester controls, never an
override - a verified first-aid neighbour 500 m away can outrank an uncle 5 km away in a critical case.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..models import Assignment, HelpRequest, Relationship, RelStatus, RequestRecipient, TrustEvent, User
from . import trust as trust_svc
from .circle import get_edge
from .geo import bbox, eta_minutes, haversine_km

MAX_ETA = {"normal": 45.0, "urgent": 30.0, "critical": 15.0}
MAX_CONCURRENT = 2
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class MatchResult:
    helper: User
    match_score: float
    trust_score: float
    category_trust: float | None
    distance_km: float
    eta_minutes: float
    in_circle: bool
    relationship_priority: int | None
    breakdown: dict[str, float]
    reasons: list[str] = field(default_factory=list)
    skills_matched: list[str] = field(default_factory=list)


def _schedule_ok(schedule: dict, now: datetime) -> float:
    if not schedule:
        return 1.0
    windows = schedule.get(DAYS[now.weekday()], [])
    cur = now.strftime("%H:%M")
    for w in windows:
        try:
            start, end = w.split("-")
            if start <= cur <= end:
                return 1.0
        except ValueError:
            continue
    return 0.3


def skill_coverage(helper: User, required: list[str]) -> tuple[float, list[str], bool]:
    """Returns (coverage 0..1, matched skill slugs, all matched via verified certification)."""
    if not required:
        return 0.6, [], False
    declared = {us.skill.slug for us in helper.skills}
    certified = {uc.certification.grants_skill for uc in helper.certifications if uc.verified and uc.certification.grants_skill}
    score, matched = 0.0, []
    for r in required:
        if r in certified:
            score += 1.0
            matched.append(r)
        elif r in declared:
            score += 0.7
            matched.append(r)
    cov = score / len(required)
    # for repair-style categories any ONE matching trade is enough
    if required and matched and len(required) > 1 and cov < 1.0 and len(matched) >= 1:
        cov = max(cov, 0.85 if any(m in certified for m in matched) else 0.65)
    return min(1.0, cov), matched, bool(matched) and all(m in certified for m in matched)


def find_candidates(db: Session, req: HelpRequest, *, radius_km: float | None = None, exclude_ids: set[int] | None = None) -> list[User]:
    s = get_settings()
    if req.lat is None or req.lng is None:
        return []
    radius = radius_km or s.community_radius_km
    min_lat, max_lat, min_lng, max_lng = bbox(req.lat, req.lng, radius)
    q = (select(User).where(
        User.is_active.is_(True), User.id != req.requester_id, User.lat.between(min_lat, max_lat),
        User.lng.between(min_lng, max_lng), User.is_available.is_(True),
    ).options(selectinload(User.skills), selectinload(User.certifications), selectinload(User.profile)))
    if exclude_ids:
        q = q.where(User.id.not_in(exclude_ids))
    users = db.scalars(q).unique().all()
    # Never match people the requester blocked / was blocked by, and respect contact choices: a circle
    # member the requester unchecked ("Who can be contacted?") or who opted out of this requester's
    # requests must not receive them through the community path either.
    ids = [u.id for u in users]
    excluded = set(db.scalars(select(Relationship.related_user_id).where(
        Relationship.user_id == req.requester_id, Relationship.related_user_id.in_(ids),
        (Relationship.status == RelStatus.BLOCKED) | ((Relationship.status == RelStatus.ACCEPTED) & (Relationship.can_receive_requests.is_(False))))))
    excluded |= set(db.scalars(select(Relationship.user_id).where(
        Relationship.related_user_id == req.requester_id, Relationship.user_id.in_(ids),
        (Relationship.status == RelStatus.BLOCKED) | ((Relationship.status == RelStatus.ACCEPTED) & (Relationship.can_receive_requests.is_(False))))))
    return [u for u in users if u.id not in excluded]


def rank(db: Session, req: HelpRequest, *, limit: int = 10, radius_km: float | None = None,
         exclude_ids: set[int] | None = None, only_ids: set[int] | None = None, now: datetime | None = None) -> list[MatchResult]:
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    requester = db.get(User, req.requester_id)
    cands = find_candidates(db, req, radius_km=radius_km, exclude_ids=exclude_ids)
    if only_ids is not None:
        cands = [c for c in cands if c.id in only_ids]
    if not cands:
        return []
    ids = [c.id for c in cands]

    trust_overall = trust_svc.cached_scores(db, ids)
    cat_trust = {uid: sc for uid, sc in db.execute(
        select(trust_svc.TrustScore.user_id, trust_svc.TrustScore.score).where(
            trust_svc.TrustScore.user_id.in_(ids), trust_svc.TrustScore.category == req.category))}
    busy = dict(db.execute(select(Assignment.helper_id, func.count()).where(
        Assignment.helper_id.in_(ids), Assignment.status == "ACTIVE").group_by(Assignment.helper_id)).all())
    exp = dict(db.execute(select(TrustEvent.user_id, func.count()).where(
        TrustEvent.user_id.in_(ids), TrustEvent.kind == "completed", TrustEvent.category == req.category).group_by(TrustEvent.user_id)).all())
    prior_with_req = dict(db.execute(select(TrustEvent.user_id, func.count()).where(
        TrustEvent.user_id.in_(ids), TrustEvent.kind == "completed", TrustEvent.counterparty_id == req.requester_id).group_by(TrustEvent.user_id)).all())
    declined = set(db.scalars(select(RequestRecipient.user_id).where(
        RequestRecipient.request_id == req.id, RequestRecipient.state == "DECLINED")))

    prefers_circle = bool(requester.profile and requester.profile.prefer_trusted_circle)
    critical = req.urgency == "critical"
    w = {"distance": s.w_distance, "skills": s.w_skills, "availability": s.w_availability,
         "trust": s.w_trust, "relationship": s.w_relationship, "context": s.w_context}
    if critical:
        w["distance"] *= s.critical_distance_boost
        w["skills"] *= s.critical_skill_boost
    if not prefers_circle:
        w["relationship"] = 0.0
    total_w = sum(w.values())
    max_eta = MAX_ETA.get(req.urgency, 45.0)

    results: list[MatchResult] = []
    for h in cands:
        if h.id in declined or busy.get(h.id, 0) >= MAX_CONCURRENT:
            continue
        d = haversine_km(req.lat, req.lng, h.lat, h.lng)
        eta = eta_minutes(d)
        cov, matched, all_cert = skill_coverage(h, req.skills_required)
        if req.skills_required and not matched and critical and req.category == "medical_assistance":
            continue  # cannot provide first-aid help at all
        c_dist = max(0.0, 1 - eta / max_eta)
        sched = _schedule_ok(h.profile.availability_schedule if h.profile else {}, now)
        c_avail = max(0.0, sched * (1 - 0.4 * busy.get(h.id, 0)))
        overall = trust_overall.get(h.id, 50.0)
        ctrust = cat_trust.get(h.id)
        c_trust = (0.6 * ctrust + 0.4 * overall if ctrust is not None else overall) / 100
        edge = get_edge(db, req.requester_id, h.id)
        member = bool(edge and edge.status == RelStatus.ACCEPTED and edge.is_trusted)
        c_rel = (1 - (edge.priority - 1) / 18) if member else 0.0  # priority 1 => 1.0, 10 => 0.5
        c_ctx = min(1.0, exp.get(h.id, 0) / 5) * 0.7 + (0.3 if prior_with_req.get(h.id) else 0.0)

        comps = {"distance": c_dist, "skills": cov, "availability": c_avail, "trust": c_trust,
                 "relationship": c_rel, "context": c_ctx}
        score = sum(w[k] * comps[k] for k in w) / total_w * 100 if total_w else 0.0
        reasons = []
        if matched:
            reasons.append(("Certified in " if all_cert else "Skilled in ") + ", ".join(m.replace("_", " ") for m in matched))
        reasons.append(f"{d * 1000:.0f} m away · ETA {eta:.0f} min" if d < 1 else f"{d:.1f} km away · ETA {eta:.0f} min")
        if exp.get(h.id):
            reasons.append(f"{exp[h.id]} similar help(s) completed")
        if member and prefers_circle:
            reasons.append("In your Trusted Circle")
        results.append(MatchResult(
            helper=h, match_score=round(score, 1), trust_score=round(overall, 1),
            category_trust=None if ctrust is None else round(ctrust, 1), distance_km=round(d, 2), eta_minutes=eta,
            in_circle=member, relationship_priority=edge.priority if member else None,
            breakdown={k: round(v * 100, 1) for k, v in comps.items()}, reasons=reasons, skills_matched=matched,
        ))
    results.sort(key=lambda r: (-r.match_score, r.eta_minutes, -r.trust_score))
    return results[:limit]
