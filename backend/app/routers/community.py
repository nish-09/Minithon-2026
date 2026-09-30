from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CommunityEvent, DirectoryEntry, User, UserSkill, utcnow
from ..security import current_user
from ..services.geo import bbox, fuzz, haversine_km

router = APIRouter(prefix="/api", tags=["community"])


@router.get("/directory")
def directory(category: str | None = None, q: str | None = Query(None, max_length=80), lat: float | None = Query(None, ge=-90, le=90),
              lng: float | None = Query(None, ge=-180, le=180), radius_km: float = Query(25, gt=0, le=100),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(DirectoryEntry)
    if category:
        query = query.where(DirectoryEntry.category == category)
    if q:
        query = query.where(DirectoryEntry.name.ilike(f"%{q}%"))
    lat = lat if lat is not None else user.lat
    lng = lng if lng is not None else user.lng
    rows = db.scalars(query.limit(500)).all()
    out = []
    for r in rows:
        d = haversine_km(lat, lng, r.lat, r.lng) if (lat is not None and r.lat is not None) else None
        if d is not None and d > radius_km and r.category != "emergency":
            continue  # emergency numbers are always listed
        out.append({"id": r.id, "name": r.name, "category": r.category, "phone": r.phone, "address": r.address, "lat": r.lat, "lng": r.lng,
                    "is_24h": r.is_24h, "notes": r.notes, "distance_km": round(d, 1) if d is not None else None})
    return sorted(out, key=lambda x: (x["category"] != "emergency", x["distance_km"] if x["distance_km"] is not None else 1e9))


@router.get("/events")
def events(lat: float | None = Query(None, ge=-90, le=90), lng: float | None = Query(None, ge=-180, le=180), radius_km: float = Query(15, gt=0, le=100),
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    lat = lat if lat is not None else user.lat
    lng = lng if lng is not None else user.lng
    rows = db.scalars(select(CommunityEvent).where(CommunityEvent.starts_at >= utcnow() - timedelta(hours=2)).order_by(CommunityEvent.starts_at).limit(200)).all()
    out = []
    for e in rows:
        d = haversine_km(lat, lng, e.lat, e.lng) if lat is not None else None
        if d is not None and d > radius_km:
            continue
        out.append({"id": e.id, "title": e.title, "description": e.description, "lat": e.lat, "lng": e.lng, "starts_at": e.starts_at.isoformat(),
                    "distance_km": round(d, 1) if d is not None else None})
    return out


@router.get("/helpers/nearby")
def helpers_nearby(lat: float | None = Query(None, ge=-90, le=90), lng: float | None = Query(None, ge=-180, le=180),
                   radius_km: float = Query(10, gt=0, le=50), skill: str | None = None, min_trust: float = Query(0, ge=0, le=100),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Anonymised helper markers for the Help Radar: approximate location, no names or contact details."""
    from ..models import TrustScore
    lat = lat if lat is not None else user.lat
    lng = lng if lng is not None else user.lng
    if lat is None:
        return []
    a, b, c, d = bbox(lat, lng, radius_km)
    q = select(User).where(User.is_active.is_(True), User.is_available.is_(True), User.id != user.id, User.lat.between(a, b), User.lng.between(c, d))
    if skill:
        from ..models import Skill
        q = q.where(User.id.in_(select(UserSkill.user_id).join(Skill, Skill.id == UserSkill.skill_id).where(Skill.slug == skill)))
    trust = dict(db.execute(select(TrustScore.user_id, TrustScore.score).where(TrustScore.category == "")).all())
    out = []
    for h in db.scalars(q.limit(300)):
        if h.profile and h.profile.location_sharing == "off":
            continue
        dist = haversine_km(lat, lng, h.lat, h.lng)
        if dist > radius_km or trust.get(h.id, 50.0) < min_trust:
            continue
        flat, flng = fuzz(h.lat, h.lng)
        out.append({"id": h.id, "lat": flat, "lng": flng, "distance_km": round(dist, 1), "trust_score": trust.get(h.id),
                    "skills": [s.skill.slug for s in h.skills], "verified": h.identity_verified})
    return sorted(out, key=lambda x: x["distance_km"])
