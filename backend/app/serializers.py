"""Output shaping. Privacy rules live here: who sees what about whom."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Assignment, HelpRequest, RecipientState, RelationshipPreference, RequestCategory, RequestRecipient, RequestStatusHistory,
    Review, TrustScore, User,
)
from .services import circle as circle_svc
from .services import credits as credits_svc
from .services import trust as trust_svc
from .services.geo import fuzz, haversine_km


def user_me(db: Session, u: User) -> dict:
    p = u.profile
    pref = db.get(RelationshipPreference, u.id)
    return {
        "id": u.id, "name": u.name, "email": u.email, "phone": u.phone, "role": u.role, "avatar_url": u.avatar_url,
        "email_verified": u.email_verified, "phone_verified": u.phone_verified, "identity_verified": u.identity_verified,
        "lat": u.lat, "lng": u.lng, "is_available": u.is_available, "created_at": u.created_at.isoformat(),
        "bio": p.bio if p else "", "availability_schedule": p.availability_schedule if p else {},
        "skills": [{"slug": s.skill.slug, "label": s.skill.label, "years_experience": s.years_experience} for s in u.skills],
        "certifications": [{"slug": c.certification.slug, "label": c.certification.label, "verified": c.verified} for c in u.certifications],
        "privacy": {
            "relationship_visibility": p.relationship_visibility if p else "circle",
            "location_sharing": p.location_sharing if p else "requests",
            "prefer_trusted_circle": p.prefer_trusted_circle if p else True,
            "trusted_circle_default_mode": p.trusted_circle_default_mode if p else "ask",
            "prefer_circle_for_critical": pref.prefer_circle_for_critical if pref else True,
            "circle_window_override_s": pref.circle_window_override_s if pref else None,
            "reveal_relationship_to_helpers": pref.reveal_relationship_to_helpers if pref else False,
        },
        "credits": credits_svc.balance(db, u.id),
    }


def trust_card(db: Session, u: User, *, detail: bool = True) -> dict:
    row = db.get(TrustScore, (u.id, ""))
    res = trust_svc.compute_trust(db, u) if (row is None or detail) else None
    if res is None:
        return {"user_id": u.id, "score": row.score}
    cats = {c.slug: c.label for c in db.scalars(select(RequestCategory))}
    return {
        "user_id": u.id, "name": u.name, "avatar_url": u.avatar_url, "score": res.score, "confidence": res.confidence,
        "model_version": res.model_version,
        "components": [{"key": k, "label": trust_svc.COMPONENT_LABELS[k], "score": v, "weight": trust_svc.COMPONENT_WEIGHTS[k]}
                       for k, v in res.components.items()],
        "categories": [{"category": c, "label": cats.get(c, c), "score": v} for c, v in sorted(res.categories.items(), key=lambda x: -x[1])],
        "factors": [{"key": f.key, "label": f.label, "impact": f.impact, "detail": f.detail} for f in res.factors],
        "badges": res.badges, "stats": res.stats,
        "certifications": [c.certification.label for c in u.certifications if c.verified],
        "disclaimer": "Trust scores are indicators based on available evidence, not guarantees of someone's behaviour.",
    }


def helper_public(db: Session, h: User, *, name: bool = True) -> dict:
    """What anyone may see about a helper: no contact details, no relationships."""
    score = db.scalar(select(TrustScore.score).where(TrustScore.user_id == h.id, TrustScore.category == ""))
    return {
        "id": h.id, "name": h.name if name else h.name.split()[0], "avatar_url": h.avatar_url,
        "identity_verified": h.identity_verified, "trust_score": score,
        "certifications": [c.certification.label for c in h.certifications if c.verified],
    }


def access_role(db: Session, req: HelpRequest, viewer: User) -> str | None:
    if viewer.role == "admin":
        return "admin"
    if req.requester_id == viewer.id:
        return "requester"
    if db.scalar(select(Assignment.id).where(Assignment.request_id == req.id, Assignment.helper_id == viewer.id, Assignment.status != "CANCELLED")):
        return "helper"
    rec = db.scalar(select(RequestRecipient).where(RequestRecipient.request_id == req.id, RequestRecipient.user_id == viewer.id))
    if rec is not None:
        return "recipient"
    return None


def requester_name(db: Session, req: HelpRequest, requester: User, viewer: User, role: str | None) -> str:
    """Full name for the requester, admins, and people in their Trusted Circle; first name otherwise."""
    if role in ("requester", "admin") or circle_svc.in_circle(db, requester.id, viewer.id):
        return requester.name
    return requester.name.split()[0]


def request_out(db: Session, req: HelpRequest, viewer: User, role: str | None = None) -> dict:
    role = role or access_role(db, req, viewer)
    requester = db.get(User, req.requester_id)
    cat = db.get(RequestCategory, req.category)
    assigned = db.scalars(select(Assignment).where(Assignment.request_id == req.id, Assignment.status != "CANCELLED")).all()
    is_assigned_helper = any(a.helper_id == viewer.id for a in assigned)

    # location privacy: exact coordinates only to the requester, admins, and assigned helpers when consented
    exact = role in ("requester", "admin") or (is_assigned_helper and req.location_shared)
    lat, lng, approx = req.lat, req.lng, False
    if req.lat is not None and not exact:
        lat, lng = fuzz(req.lat, req.lng)
        approx = True
    if role == "recipient" and viewer.lat is not None and req.lat is not None:
        dist = round(haversine_km(req.lat, req.lng, viewer.lat, viewer.lng), 2)
    else:
        dist = None

    out = {
        "id": req.id, "title": req.title, "description": req.description, "raw_text": req.raw_text if role in ("requester", "admin") else None,
        "category": req.category, "category_label": cat.label if cat else req.category, "icon": cat.icon if cat else "🤝",
        "urgency": req.urgency, "status": req.status, "skills_required": req.skills_required, "num_helpers": req.num_helpers,
        "filled_slots": req.filled_slots, "time_requirement": req.time_requirement,
        "lat": lat, "lng": lng, "location_approximate": approx, "location_shared": req.location_shared, "distance_km": dist,
        "routing_mode": req.routing_mode, "created_at": req.created_at.isoformat(), "updated_at": req.updated_at.isoformat(),
        "expires_at": req.expires_at.isoformat() if req.expires_at else None, "viewer_role": role,
        "incident_id": req.incident_id, "nlu_source": req.nlu_source,
        "requester": {"id": requester.id, "name": requester_name(db, req, requester, viewer, role), "avatar_url": requester.avatar_url}
        if role else None,
        "circle_deadline": req.circle_deadline.isoformat() if req.circle_deadline else None,
    }
    if role in ("requester", "admin"):
        out["assignments"] = []
        for a in assigned:
            # the requester (and admins) may always see how their own contacts relate to them;
            # `reveal_relationship` only governs what the *helper* is told about the requester
            label = circle_svc.helper_label(db, requester, a.helper_id, True)
            out["assignments"].append({
                "id": a.id, "status": a.status, "eta_minutes": a.eta_minutes, "distance_km": a.distance_km, "channel": a.channel,
                "helper": helper_public(db, a.helper), "relationship_label": label,
                "lat": a.helper.lat if (a.helper.profile and a.helper.profile.location_sharing != "off" and a.status in ("ACTIVE", "ARRIVED")) else None,
                "lng": a.helper.lng if (a.helper.profile and a.helper.profile.location_sharing != "off" and a.status in ("ACTIVE", "ARRIVED")) else None,
            })
        recs = db.scalars(select(RequestRecipient).where(RequestRecipient.request_id == req.id)).all()
        out["recipients"] = [{"user_id": r.user_id, "name": r.user.name if r.channel == "circle" else None, "channel": r.channel,
                              "state": r.state, "match_score": r.match_score} for r in recs]
        out["history"] = [{"from": h.from_status, "to": h.to_status, "note": h.note, "at": h.created_at.isoformat()}
                          for h in db.scalars(select(RequestStatusHistory).where(RequestStatusHistory.request_id == req.id).order_by(RequestStatusHistory.id))]
        out["reviews"] = [{"helper_id": r.reviewee_id, "rating": r.rating} for r in db.scalars(select(Review).where(Review.request_id == req.id))]
    elif role == "helper":
        mine = next(a for a in assigned if a.helper_id == viewer.id)
        out["my_assignment"] = {"id": mine.id, "status": mine.status, "eta_minutes": mine.eta_minutes, "distance_km": mine.distance_km}
    elif role == "recipient":
        rec = db.scalar(select(RequestRecipient).where(RequestRecipient.request_id == req.id, RequestRecipient.user_id == viewer.id))
        out["my_recipient_state"] = rec.state
        out["channel"] = rec.channel
        out["can_accept"] = rec.state in (RecipientState.NOTIFIED, RecipientState.EXPIRED) and req.filled_slots < req.num_helpers
        out["relationship_label"] = circle_svc.helper_label(db, requester, viewer.id, req.reveal_relationship) if rec.channel == "circle" else None
    return out
