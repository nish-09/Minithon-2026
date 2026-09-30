from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serializers as ser
from ..db import get_db
from ..models import Assignment, HelpRequest, Message, RecipientState, ReqStatus, RequestCategory, RequestRecipient, User
from ..schemas import (
    MessageIn, NoShowIn, ProgressIn, RequestCreate, RequestPatch, ReviewIn, TrustedCircleAskIn,
)
from ..security import current_user
from ..services import orchestrator as orch
from ..services.geo import bbox, fuzz, haversine_km
from ..services.realtime import emit

router = APIRouter(prefix="/api/requests", tags=["requests"])


def flow(fn, db: Session):
    try:
        return fn()
    except orch.FlowError as e:
        db.rollback()
        raise HTTPException(e.status, str(e))


def load_visible(db: Session, rid: int, viewer: User) -> tuple[HelpRequest, str]:
    req = db.get(HelpRequest, rid)
    role = ser.access_role(db, req, viewer) if req else None
    if req is None or role is None:
        raise HTTPException(404, "Request not found")  # 404 (not 403) so existence is not revealed
    return req, role


@router.post("", status_code=201)
def create(body: RequestCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.routing_mode == "custom" and not body.custom_recipient_ids:
        raise HTTPException(422, "custom routing needs custom_recipient_ids")
    lat, lng = body.lat, body.lng
    if lat is None and user.lat is None:
        raise HTTPException(422, "Location is required to find nearby help")
    if (lat is None) != (lng is None):
        raise HTTPException(422, "Provide both lat and lng")
    req = flow(lambda: orch.create_request(
        db, user, text=body.text, lat=lat, lng=lng, share_location=body.share_location, routing_mode=body.routing_mode,
        custom_ids=body.custom_recipient_ids, overrides=body.overrides.model_dump(exclude_none=True) if body.overrides else None,
        reveal_relationship=body.reveal_relationship), db)
    db.commit()
    db.refresh(req)
    return ser.request_out(db, req, user, "requester")


@router.get("")
def list_requests(scope: str = Query("mine", pattern="^(mine|invited|assigned|all)$"), status: str | None = None,
                  limit: int = Query(50, ge=1, le=200), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(HelpRequest)
    if scope == "mine":
        q = q.where(HelpRequest.requester_id == user.id)
    elif scope == "assigned":
        q = q.where(HelpRequest.id.in_(select(Assignment.request_id).where(Assignment.helper_id == user.id, Assignment.status != "CANCELLED")))
    elif scope == "invited":
        q = q.where(HelpRequest.id.in_(select(RequestRecipient.request_id).where(
            RequestRecipient.user_id == user.id, RequestRecipient.state == RecipientState.NOTIFIED)), HelpRequest.status.in_(ReqStatus.OPEN))
    elif scope == "all":
        if user.role != "admin":
            raise HTTPException(403, "Admin access required")
    if status:
        q = q.where(HelpRequest.status == status.upper())
    rows = db.scalars(q.order_by(HelpRequest.id.desc()).limit(limit)).all()
    for r in rows:
        orch.refresh_request(db, r)
    db.commit()
    return [ser.request_out(db, r, user) for r in rows]


@router.get("/radar")
def radar(lat: float | None = Query(None, ge=-90, le=90), lng: float | None = Query(None, ge=-180, le=180),
          radius_km: float = Query(10, gt=0, le=50), category: str | None = None, urgency: str | None = Query(None, pattern="^(normal|urgent|critical)$"),
          user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Anonymised map view of open requests nearby. Approximate coordinates, no names, no free text.
    Critical incidents are only shown to people who were actually notified (and admins)."""
    if lat is None:
        lat, lng = user.lat, user.lng
    if lat is None:
        raise HTTPException(422, "Location required")
    a, b, c, d = bbox(lat, lng, radius_km)
    q = select(HelpRequest).where(HelpRequest.status.in_(ReqStatus.OPEN), HelpRequest.lat.between(a, b), HelpRequest.lng.between(c, d),
                                  HelpRequest.requester_id != user.id)
    if category:
        q = q.where(HelpRequest.category == category)
    if urgency:
        q = q.where(HelpRequest.urgency == urgency)
    notified = set(db.scalars(select(RequestRecipient.request_id).where(RequestRecipient.user_id == user.id)))
    cats = {c_.slug: c_ for c_ in db.scalars(select(RequestCategory))}
    out = []
    for r in db.scalars(q.limit(200)):
        if r.urgency == "critical" and r.id not in notified and user.role != "admin":
            continue
        dist = haversine_km(lat, lng, r.lat, r.lng)
        if dist > radius_km:
            continue
        flat, flng = fuzz(r.lat, r.lng)
        cat = cats.get(r.category)
        out.append({"id": r.id, "category": r.category, "icon": cat.icon if cat else "🤝", "label": cat.label if cat else r.category,
                    "urgency": r.urgency, "lat": flat, "lng": flng, "distance_km": round(dist, 1), "status": r.status,
                    "invited": r.id in notified, "created_at": r.created_at.isoformat()})
    return sorted(out, key=lambda x: x["distance_km"])


@router.get("/{rid}")
def get_one(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, role = load_visible(db, rid, user)
    flow(lambda: orch.refresh_request(db, req), db)
    db.commit()
    db.refresh(req)
    return ser.request_out(db, req, user, role)


@router.patch("/{rid}")
def patch(rid: int, body: RequestPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, role = load_visible(db, rid, user)
    if role != "requester":
        raise HTTPException(403, "Only the requester can edit this request")
    if req.status in ReqStatus.TERMINAL or req.status in (ReqStatus.IN_PROGRESS, ReqStatus.ON_THE_WAY):
        raise HTTPException(409, f"Cannot edit a request that is {req.status.lower()}")
    data = body.model_dump(exclude_unset=True)
    if "num_helpers" in data and data["num_helpers"] is not None and data["num_helpers"] < req.filled_slots:
        raise HTTPException(409, "Cannot reduce helpers below the number already assigned")
    for k, v in data.items():
        if v is not None:
            setattr(req, k, v)
    db.commit()
    return ser.request_out(db, req, user, role)


@router.post("/{rid}/cancel")
def cancel(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, role = load_visible(db, rid, user)
    flow(lambda: orch.cancel(db, req, user), db)
    db.commit()
    return ser.request_out(db, req, user, role)


@router.post("/{rid}/complete")
def complete(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, role = load_visible(db, rid, user)
    flow(lambda: orch.complete(db, req, user), db)
    db.commit()
    return ser.request_out(db, req, user, role)


@router.post("/{rid}/progress")
def progress(rid: int, body: ProgressIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Assigned helper reports ON_THE_WAY or arrival (IN_PROGRESS)."""
    req, role = load_visible(db, rid, user)
    flow(lambda: orch.helper_progress(db, req, user, body.status), db)
    db.commit()
    return ser.request_out(db, req, user, "helper")


@router.post("/{rid}/withdraw")
def withdraw(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, role = load_visible(db, rid, user)
    flow(lambda: orch.helper_withdraw(db, req, user), db)
    db.commit()
    return {"status": "withdrawn"}


@router.post("/{rid}/no-show")
def no_show(rid: int, body: NoShowIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, _ = load_visible(db, rid, user)
    flow(lambda: orch.report_no_show(db, req, user, body.helper_id), db)
    db.commit()
    return {"status": "recorded"}


@router.post("/{rid}/review", status_code=201)
def review(rid: int, body: ReviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, _ = load_visible(db, rid, user)
    rv = flow(lambda: orch.rate(db, req, user, body.helper_id, body.rating, body.comment), db)
    db.commit()
    return {"id": rv.id, "rating": rv.rating}


@router.post("/{rid}/trusted-circle")
def ask_trusted_circle(rid: int, body: TrustedCircleAskIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, _ = load_visible(db, rid, user)
    n = flow(lambda: orch.ask_circle(db, req, user, body.recipient_ids if body else None), db)
    db.commit()
    db.refresh(req)
    return {"asked": n, "request": ser.request_out(db, req, user, "requester")}


@router.post("/{rid}/expand-to-community")
def expand_to_community(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, _ = load_visible(db, rid, user)
    if req.requester_id != user.id:
        raise HTTPException(403, "Only the requester can do this")
    flow(lambda: orch.escalate_to_community(db, req, user.id, "requester_expanded"), db)
    db.commit()
    db.refresh(req)
    return ser.request_out(db, req, user, "requester")


# ---- chat ---------------------------------------------------------------------------------
def _chat_participants(db: Session, req: HelpRequest) -> set[int]:
    return {req.requester_id} | set(db.scalars(select(Assignment.helper_id).where(Assignment.request_id == req.id, Assignment.status != "CANCELLED")))


@router.get("/{rid}/messages")
def messages(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, role = load_visible(db, rid, user)
    if user.id not in _chat_participants(db, req) and role != "admin":
        raise HTTPException(403, "Chat opens once a helper is assigned")
    rows = db.scalars(select(Message).where(Message.request_id == rid).order_by(Message.id)).all()
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_({m.sender_id for m in rows} or {0})))}
    return [{"id": m.id, "sender_id": m.sender_id, "sender": names.get(m.sender_id), "body": m.body, "created_at": m.created_at.isoformat()} for m in rows]


@router.post("/{rid}/messages", status_code=201)
def send_message(rid: int, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, _ = load_visible(db, rid, user)
    parts = _chat_participants(db, req)
    if user.id not in parts or len(parts) < 2:
        raise HTTPException(403, "Chat opens once a helper is assigned")
    if req.status in ReqStatus.TERMINAL and req.status != ReqStatus.COMPLETED:
        raise HTTPException(409, "This request is closed")
    m = Message(request_id=rid, sender_id=user.id, body=body.body)
    db.add(m)
    db.flush()
    for uid in parts - {user.id}:
        emit(db, uid, {"type": "message", "request_id": rid, "from": user.name.split()[0], "body": body.body[:200]})
    db.commit()
    return {"id": m.id, "sender_id": user.id, "body": m.body, "created_at": m.created_at.isoformat()}
