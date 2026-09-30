"""Trusted Circle: relationship graph operations and privacy rules.

Graph model: every relationship is stored as TWO directed edges (A->B and B->A) so each person owns
their own label, visibility, priority and contactability. Both edges share one status; the receiving
side must accept before the relationship is verified (ACCEPTED).

  edge(A->B).can_receive_requests  = A allows B to be contacted for A's requests
  edge(B->A).can_receive_requests  = B is willing to receive A's requests
A request only goes to a circle member when BOTH are true.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import RelationshipType, Relationship, RelStatus, User
from .geo import eta_minutes, haversine_km

VIS_RANK = {"nobody": 0, "me": 1, "circle": 2}


class CircleError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def get_edge(db: Session, owner_id: int, other_id: int) -> Relationship | None:
    return db.scalar(select(Relationship).where(Relationship.user_id == owner_id, Relationship.related_user_id == other_id))


def create_relationship(db: Session, me: User, other: User, rel_type: str) -> Relationship:
    if me.id == other.id:
        raise CircleError("You cannot add yourself to your Trusted Circle")
    rt = db.get(RelationshipType, rel_type)
    if rt is None:
        raise CircleError("Unknown relationship type")
    mine, theirs = get_edge(db, me.id, other.id), get_edge(db, other.id, me.id)
    if (mine and mine.status == RelStatus.BLOCKED) or (theirs and theirs.status == RelStatus.BLOCKED):
        # do not reveal who blocked whom
        raise CircleError("This relationship cannot be created", 409)
    if mine and mine.status in (RelStatus.ACCEPTED, RelStatus.PENDING):
        raise CircleError("A relationship with this person already exists", 409)
    # re-adding after a decline: reuse the rows and reopen them
    if mine is None:
        mine = Relationship(user_id=me.id, related_user_id=other.id, relationship_type=rel_type)
        db.add(mine)
    if theirs is None:
        theirs = Relationship(user_id=other.id, related_user_id=me.id, relationship_type=rt.inverse_slug or "other")
        db.add(theirs)
    mine.relationship_type, theirs.relationship_type = rel_type, rt.inverse_slug or "other"
    mine.status = theirs.status = RelStatus.PENDING
    mine.initiated_by_id = theirs.initiated_by_id = me.id
    db.flush()
    return mine


def _pair(db: Session, me: User, rel_id: int) -> tuple[Relationship, Relationship | None]:
    edge = db.get(Relationship, rel_id)
    if edge is None or edge.user_id != me.id:
        raise CircleError("Relationship not found", 404)  # also hides other users' edges
    return edge, get_edge(db, edge.related_user_id, me.id)


def accept(db: Session, me: User, rel_id: int) -> Relationship:
    edge, back = _pair(db, me, rel_id)
    if edge.status != RelStatus.PENDING or edge.initiated_by_id == me.id:
        raise CircleError("Only the invited person can accept a pending relationship", 409)
    edge.status = RelStatus.ACCEPTED
    if back:
        back.status = RelStatus.ACCEPTED
    return edge


def decline(db: Session, me: User, rel_id: int) -> Relationship:
    edge, back = _pair(db, me, rel_id)
    if edge.status != RelStatus.PENDING or edge.initiated_by_id == me.id:
        raise CircleError("Only the invited person can decline a pending relationship", 409)
    edge.status = RelStatus.DECLINED
    if back:
        back.status = RelStatus.DECLINED
    return edge


def block(db: Session, me: User, rel_id: int) -> Relationship:
    edge, back = _pair(db, me, rel_id)
    edge.status = RelStatus.BLOCKED
    if back:
        back.status = RelStatus.BLOCKED
        back.can_receive_requests = False
    edge.can_receive_requests = False
    return edge


def remove(db: Session, me: User, rel_id: int) -> None:
    edge, back = _pair(db, me, rel_id)
    if edge.status == RelStatus.BLOCKED:
        # keep the block so the other person cannot simply re-invite
        raise CircleError("Unblock by contacting support; blocked relationships cannot be removed", 409)
    db.delete(edge)
    if back:
        db.delete(back)


# ---- privacy ------------------------------------------------------------------------------
def effective_visibility(edge: Relationship, owner: User) -> str:
    """Most restrictive of the edge setting and the owner's profile-wide setting."""
    prof = owner.profile.relationship_visibility if owner.profile else "circle"
    return min((edge.visibility, prof), key=lambda v: VIS_RANK.get(v, 0))


def in_circle(db: Session, owner_id: int, viewer_id: int) -> bool:
    e = get_edge(db, owner_id, viewer_id)
    return bool(e and e.status == RelStatus.ACCEPTED and e.is_trusted)


def viewer_can_see_edge(db: Session, viewer: User, edge: Relationship) -> bool:
    if viewer.id in (edge.user_id, edge.related_user_id):
        return True  # the two people in the relationship always see it
    owner = db.get(User, edge.user_id)
    vis = effective_visibility(edge, owner)
    if edge.status != RelStatus.ACCEPTED:
        return False
    return vis == "circle" and in_circle(db, edge.user_id, viewer.id)


def visible_relationships_of(db: Session, viewer: User, owner_id: int) -> list[Relationship]:
    edges = db.scalars(select(Relationship).where(Relationship.user_id == owner_id, Relationship.status == RelStatus.ACCEPTED)).all()
    return [e for e in edges if viewer_can_see_edge(db, viewer, e)]


def helper_label(db: Session, requester: User, helper_id: int, reveal: bool) -> str:
    """What a helper/stranger is allowed to learn about how they relate to the requester."""
    if reveal:
        edge = get_edge(db, requester.id, helper_id)
        if edge and edge.status == RelStatus.ACCEPTED and effective_visibility(edge, requester) != "nobody":
            rt = db.get(RelationshipType, edge.relationship_type)
            return f"{requester.name.split()[0]}'s {rt.label.lower()}" if rt else "Trusted contact"
    return "Verified nearby helper"


# ---- circle membership for routing --------------------------------------------------------
@dataclass
class CircleMember:
    user: User
    edge: Relationship
    distance_km: float | None
    eta_min: float | None
    available: bool


def circle_members(db: Session, requester: User, *, lat: float | None, lng: float | None,
                   only_contactable: bool = True, nearby_only: bool = True) -> list[CircleMember]:
    s = get_settings()
    rows = db.scalars(select(Relationship).where(
        Relationship.user_id == requester.id, Relationship.status == RelStatus.ACCEPTED, Relationship.is_trusted.is_(True),
    )).all()
    out: list[CircleMember] = []
    for e in rows:
        u = e.related_user
        if not u.is_active:
            continue
        back = get_edge(db, u.id, requester.id)
        if only_contactable and not (e.can_receive_requests and back and back.can_receive_requests and back.status == RelStatus.ACCEPTED):
            continue
        d = eta = None
        if lat is not None and lng is not None and u.lat is not None and u.lng is not None:
            d = round(haversine_km(lat, lng, u.lat, u.lng), 2)
            eta = eta_minutes(d)
        if nearby_only and (d is None or d > s.circle_radius_km):
            continue
        out.append(CircleMember(u, e, d, eta, u.is_available))
    out.sort(key=lambda m: (m.edge.priority, m.distance_km if m.distance_km is not None else 1e9))
    return out
