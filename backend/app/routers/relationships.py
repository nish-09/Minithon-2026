from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Relationship, RelationshipType, RelStatus, User
from ..schemas import RelationshipCreate, RelationshipPatch
from ..security import current_user
from ..services import circle as circle_svc
from ..services.geo import eta_minutes, haversine_km
from ..services.realtime import notify

router = APIRouter(prefix="/api", tags=["trusted-circle"])


def _edge_out(db: Session, me: User, e: Relationship) -> dict:
    other = e.related_user
    rt = db.get(RelationshipType, e.relationship_type)
    dist = None
    if me.lat is not None and other.lat is not None and e.status == RelStatus.ACCEPTED:
        dist = round(haversine_km(me.lat, me.lng, other.lat, other.lng), 2)
    return {
        "id": e.id, "user": {"id": other.id, "name": other.name, "avatar_url": other.avatar_url, "identity_verified": other.identity_verified},
        "relationship_type": e.relationship_type, "label": rt.label if rt else e.relationship_type, "group": rt.group if rt else "other",
        "status": e.status, "direction": "outgoing" if e.initiated_by_id == me.id else "incoming",
        "can_respond": e.status == RelStatus.PENDING and e.initiated_by_id != me.id,
        "is_trusted": e.is_trusted, "can_receive_requests": e.can_receive_requests, "visibility": e.visibility, "priority": e.priority,
        "distance_km": dist, "eta_minutes": eta_minutes(dist) if dist is not None else None,
        "available": other.is_available if e.status == RelStatus.ACCEPTED else None,
        "created_at": e.created_at.isoformat(),
    }


def _wrap(fn, db: Session):
    try:
        return fn()
    except circle_svc.CircleError as err:
        db.rollback()
        raise HTTPException(err.status, str(err))


@router.post("/relationships", status_code=201)
def create_relationship(body: RelationshipCreate, me: User = Depends(current_user), db: Session = Depends(get_db)):
    if (body.email is None) == (body.user_id is None):
        raise HTTPException(422, "Provide exactly one of email or user_id")
    other = db.scalar(select(User).where(User.email == body.email.lower())) if body.email else db.get(User, body.user_id)
    if other is None or not other.is_active:
        if body.email:  # do not reveal whether an address has an account
            return {"status": "invited", "detail": "If that person has a NEXA account, they will receive your invitation."}
        raise HTTPException(404, "User not found")
    edge = _wrap(lambda: circle_svc.create_relationship(db, me, other, body.relationship_type), db)
    notify(db, other.id, "relationship_request", f"{me.name} wants to add you to their Trusted Circle",
           "Accept to be contactable when they need help.", {"relationship_id": circle_svc.get_edge(db, other.id, me.id).id})
    db.commit()
    db.refresh(edge)
    return _edge_out(db, me, edge)


@router.get("/relationships")
def list_relationships(status: str | None = None, me: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Relationship).where(Relationship.user_id == me.id)
    if status:
        q = q.where(Relationship.status == status.upper())
    edges = db.scalars(q.order_by(Relationship.priority, Relationship.id)).all()
    return [_edge_out(db, me, e) for e in edges if e.status != RelStatus.DECLINED or e.initiated_by_id == me.id]


@router.patch("/relationships/{rel_id}")
def patch_relationship(rel_id: int, body: RelationshipPatch, me: User = Depends(current_user), db: Session = Depends(get_db)):
    edge, _ = _wrap(lambda: circle_svc._pair(db, me, rel_id), db)
    data = body.model_dump(exclude_unset=True)
    if "relationship_type" in data:
        if db.get(RelationshipType, data["relationship_type"]) is None:
            raise HTTPException(422, "Unknown relationship type")
        edge.relationship_type = data["relationship_type"]
    for k in ("is_trusted", "can_receive_requests", "visibility", "priority"):
        if k in data and data[k] is not None:
            setattr(edge, k, data[k])
    if edge.status != RelStatus.ACCEPTED and ("is_trusted" in data or "can_receive_requests" in data):
        raise HTTPException(409, "Trusted Circle settings apply once the relationship is accepted")
    db.commit()
    return _edge_out(db, me, edge)


@router.delete("/relationships/{rel_id}", status_code=204)
def delete_relationship(rel_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    _wrap(lambda: circle_svc.remove(db, me, rel_id), db)
    db.commit()


@router.post("/relationships/{rel_id}/accept")
def accept_relationship(rel_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    edge = _wrap(lambda: circle_svc.accept(db, me, rel_id), db)
    notify(db, edge.related_user_id, "relationship_accepted", f"{me.name} accepted your Trusted Circle invitation", "", {})
    db.commit()
    return _edge_out(db, me, edge)


@router.post("/relationships/{rel_id}/decline")
def decline_relationship(rel_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    edge = _wrap(lambda: circle_svc.decline(db, me, rel_id), db)
    db.commit()
    return _edge_out(db, me, edge)


@router.post("/relationships/{rel_id}/block")
def block_relationship(rel_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    edge = _wrap(lambda: circle_svc.block(db, me, rel_id), db)
    db.commit()
    return _edge_out(db, me, edge)


@router.get("/trusted-circle")
def trusted_circle(lat: float | None = None, lng: float | None = None, me: User = Depends(current_user), db: Session = Depends(get_db)):
    """The requester's accepted circle grouped for the UI, with distance/availability, plus pending invitations."""
    use_lat, use_lng = (lat, lng) if lat is not None and lng is not None else (me.lat, me.lng)
    members = circle_svc.circle_members(db, me, lat=use_lat, lng=use_lng, only_contactable=False, nearby_only=False)
    groups: dict[str, list] = {"family": [], "friends": [], "other": []}
    nearby = 0
    for m in members:
        item = _edge_out(db, me, m.edge)
        if m.distance_km is not None:
            item["distance_km"], item["eta_minutes"] = m.distance_km, m.eta_min
        back = circle_svc.get_edge(db, m.user.id, me.id)
        item["contactable"] = bool(m.edge.can_receive_requests and back and back.can_receive_requests)
        item["nearby"] = bool(item["contactable"] and m.distance_km is not None and m.distance_km <= get_settings().circle_radius_km)
        nearby += 1 if item["nearby"] else 0
        groups[item["group"]].append(item)
    pending = [_edge_out(db, me, e) for e in db.scalars(select(Relationship).where(
        Relationship.user_id == me.id, Relationship.status == RelStatus.PENDING))]
    return {"groups": groups, "nearby_count": nearby, "total": len(members), "pending": pending}
