from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import serializers as ser
from ..db import get_db
from ..models import (
    Certification, Notification, RelationshipPreference, RelationshipType, Report, RequestCategory, Review,
    Skill, User, UserCertification, UserSkill, utcnow,
)
from ..schemas import DonateIn, LocationIn, ProfileUpdate, ReportIn
from ..security import current_user
from ..services import circle as circle_svc
from ..services import credits as credits_svc
from ..services import trust as trust_svc

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/reference")
def reference(db: Session = Depends(get_db)):
    """Static lookup data for forms (public)."""
    return {
        "categories": [{"slug": c.slug, "label": c.label, "icon": c.icon, "default_skills": c.default_skills} for c in db.scalars(select(RequestCategory))],
        "skills": [{"slug": s.slug, "label": s.label, "trust_category": s.trust_category} for s in db.scalars(select(Skill))],
        "certifications": [{"slug": c.slug, "label": c.label} for c in db.scalars(select(Certification))],
        "relationship_types": [{"slug": r.slug, "label": r.label, "group": r.group} for r in db.scalars(select(RelationshipType))],
    }


@router.patch("/users/me")
def update_me(body: ProfileUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if "phone" in data and data["phone"] != user.phone:
        if data["phone"] and db.scalar(select(User.id).where(User.phone == data["phone"], User.id != user.id)):
            raise HTTPException(409, "That phone number is already in use")
        user.phone, user.phone_verified = data["phone"], False
    for k in ("name", "avatar_url", "is_available"):
        if k in data and data[k] is not None:
            setattr(user, k, data[k])
    p = user.profile
    for k in ("bio", "availability_schedule", "relationship_visibility", "location_sharing", "prefer_trusted_circle", "trusted_circle_default_mode"):
        if k in data and data[k] is not None:
            setattr(p, k, data[k])
    pref = db.get(RelationshipPreference, user.id) or RelationshipPreference(user_id=user.id)
    db.add(pref)
    for k in ("prefer_circle_for_critical", "reveal_relationship_to_helpers"):
        if k in data and data[k] is not None:
            setattr(pref, k, data[k])
    if "circle_window_override_s" in data:
        pref.circle_window_override_s = data["circle_window_override_s"]

    if body.skills is not None:
        slugs = {s.slug for s in body.skills}
        found = {s.slug: s for s in db.scalars(select(Skill).where(Skill.slug.in_(slugs)))}
        if slugs - set(found):
            raise HTTPException(422, f"Unknown skill(s): {sorted(slugs - set(found))}")
        user.skills.clear()
        db.flush()
        for s in body.skills:
            user.skills.append(UserSkill(user_id=user.id, skill_id=found[s.slug].id, years_experience=s.years_experience))
    if body.certifications is not None:
        found = {c.slug: c for c in db.scalars(select(Certification).where(Certification.slug.in_(body.certifications)))}
        if set(body.certifications) - set(found):
            raise HTTPException(422, "Unknown certification")
        existing = {uc.certification.slug: uc for uc in user.certifications}
        for slug in list(existing):
            if slug not in found:
                user.certifications.remove(existing[slug])
        for slug, c in found.items():
            if slug not in existing:  # claimed certifications stay unverified until an admin verifies them
                user.certifications.append(UserCertification(user_id=user.id, certification_id=c.id, verified=False))
    try:
        db.flush()
        trust_svc.refresh_trust(db, user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Could not update profile")
    db.refresh(user)
    return ser.user_me(db, user)


@router.put("/users/me/location")
def set_location(body: LocationIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.profile and user.profile.location_sharing == "off":
        raise HTTPException(403, "Location sharing is turned off in your privacy settings")
    user.lat, user.lng, user.location_updated_at = body.lat, body.lng, utcnow()
    db.commit()
    return {"lat": user.lat, "lng": user.lng}


@router.delete("/users/me/location", status_code=204)
def clear_location(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.lat = user.lng = user.location_updated_at = None
    user.is_available = False
    db.commit()


def _get_user(db: Session, uid: int) -> User:
    u = db.get(User, uid)
    if u is None or not u.is_active:
        raise HTTPException(404, "User not found")
    return u


@router.get("/users/{user_id}")
def public_profile(user_id: int, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    out = ser.helper_public(db, u)
    out["bio"] = u.profile.bio if u.profile else ""
    out["skills"] = [s.skill.label for s in u.skills]
    out["member_since"] = u.created_at.isoformat()
    return out


@router.get("/users/{user_id}/trust")
def get_trust(user_id: int, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    card = ser.trust_card(db, u)
    return card


@router.get("/users/{user_id}/trust/explanation")
def get_trust_explanation(user_id: int, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    card = ser.trust_card(db, u)
    return {"user_id": u.id, "score": card["score"], "confidence": card["confidence"], "model_version": card["model_version"],
            "factors": card["factors"], "components": card["components"], "categories": card["categories"], "disclaimer": card["disclaimer"]}


@router.get("/users/{user_id}/reviews")
def get_reviews(user_id: int, limit: int = Query(20, ge=1, le=100), viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    _get_user(db, user_id)
    rows = db.scalars(select(Review).where(Review.reviewee_id == user_id).order_by(Review.id.desc()).limit(limit)).all()
    return [{"id": r.id, "rating": r.rating, "comment": r.comment, "category": r.category, "created_at": r.created_at.isoformat(),
             "reviewer": r.reviewer.name.split()[0]} for r in rows]


@router.get("/users/{user_id}/circle")
def user_circle(user_id: int, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    """Relationships of `user_id` that the viewer is allowed to see (owner, circle members, never strangers)."""
    _get_user(db, user_id)
    edges = circle_svc.visible_relationships_of(db, viewer, user_id)
    return [{"user_id": e.related_user_id, "name": e.related_user.name, "relationship_type": e.relationship_type} for e in edges]


# ---- credits --------------------------------------------------------------------------------
@router.get("/credits")
def my_credits(user: User = Depends(current_user), db: Session = Depends(get_db)):
    bal = credits_svc.balance(db, user.id)
    db.commit()
    return {"balance": bal, "transactions": [{"id": t.id, "amount": t.amount, "kind": t.kind, "request_id": t.request_id,
                                              "created_at": t.created_at.isoformat()} for t in credits_svc.history(db, user.id)]}


@router.post("/credits/donate")
def donate(body: DonateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        credits_svc.donate(db, user.id, body.to_user_id, body.amount)
    except credits_svc.CreditError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    from ..services.realtime import notify
    notify(db, body.to_user_id, "credits_received", f"{user.name.split()[0]} donated {body.amount} Help Credits", "", {})
    db.commit()
    return {"balance": credits_svc.balance(db, user.id)}


# ---- notifications --------------------------------------------------------------------------
@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = Query(50, ge=1, le=200), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read.is_(False))
    rows = db.scalars(q.order_by(Notification.id.desc()).limit(limit)).all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read.is_(False)))
    return {"unread": unread, "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "data": n.data, "read": n.read,
                                        "created_at": n.created_at.isoformat()} for n in rows]}


@router.post("/notifications/read", status_code=204)
def mark_read(user: User = Depends(current_user), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))):
        n.read = True
    db.commit()


# ---- reports --------------------------------------------------------------------------------
@router.post("/reports", status_code=201)
def create_report(body: ReportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.target_user_id is None and body.request_id is None:
        raise HTTPException(422, "Report a user or a request")
    if body.target_user_id == user.id:
        raise HTTPException(400, "You cannot report yourself")
    if body.target_user_id is not None:
        _get_user(db, body.target_user_id)
    r = Report(reporter_id=user.id, target_user_id=body.target_user_id, request_id=body.request_id, reason=body.reason, details=body.details)
    db.add(r)
    from ..services.realtime import notify
    for admin in db.scalars(select(User).where(User.role == "admin")):
        notify(db, admin.id, "user_report", f"New report: {body.reason}", body.details[:120], {"target_user_id": body.target_user_id})
    db.commit()
    return {"id": r.id, "status": r.status}
