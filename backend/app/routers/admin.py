from collections import Counter, defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import serializers as ser
from ..db import get_db
from ..models import (
    Certification, DirectoryEntry, HelpRequest, Incident, Protocol, ProtocolStep, ReqStatus, Report, RequestCategory, RequestRecipient,
    TrustEvent, TrustScore, User, UserCertification, UserSkill, Verification, utcnow,
)
from ..schemas import CertVerifyIn, DirectoryIn, ModerateIn, ProtocolIn, ReportResolveIn, VerifyIn
from ..security import admin_user
from ..services import care
from ..services import orchestrator as orch
from ..services import trust as trust_svc
from ..services.realtime import hub, notify
from .requests import flow

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _unmatched_ids(db: Session) -> list[int]:
    """Open requests nobody has been asked about / everyone declined or timed out, with no assignment."""
    out = []
    for r in db.scalars(select(HelpRequest).where(HelpRequest.status.in_(ReqStatus.OPEN))):
        pending = db.scalar(select(func.count()).select_from(RequestRecipient).where(
            RequestRecipient.request_id == r.id, RequestRecipient.state.in_(["NOTIFIED", "ACCEPTED"])))
        if not pending and r.filled_slots == 0 and r.status != ReqStatus.TRUSTED_CIRCLE:
            out.append(r.id)
    return out


@router.get("/dashboard")
def dashboard(admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    active = db.scalar(select(func.count()).select_from(HelpRequest).where(HelpRequest.status.in_(ReqStatus.ACTIVE))) or 0
    urgent = db.scalar(select(func.count()).select_from(HelpRequest).where(HelpRequest.status.in_(ReqStatus.ACTIVE), HelpRequest.urgency != "normal")) or 0
    critical = db.scalar(select(func.count()).select_from(Incident).where(Incident.status == "ACTIVE")) or 0
    completed = db.scalar(select(func.count()).select_from(HelpRequest).where(HelpRequest.completed_at >= day_start)) or 0
    avg_resp = db.scalar(select(func.avg(TrustEvent.value)).where(TrustEvent.kind == "responded", TrustEvent.created_at >= now - timedelta(hours=24)))
    online = db.scalar(select(func.count()).select_from(User).where(User.is_available.is_(True), User.is_active.is_(True))) or 0
    return {
        "active_requests": active, "urgent_requests": urgent, "critical_incidents": critical,
        "helpers_online": online, "helpers_connected": len(hub.online_user_ids()), "unmatched_requests": len(_unmatched_ids(db)),
        "completed_today": completed, "avg_response_seconds": round(avg_resp) if avg_resp is not None else None,
        "open_reports": db.scalar(select(func.count()).select_from(Report).where(Report.status == "OPEN")) or 0,
    }


@router.get("/analytics")
def analytics(days: int = Query(30, ge=1, le=365), admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Aggregated community intelligence. Coordinates are bucketed (~1 km) - no personal data."""
    since = utcnow() - timedelta(days=days)
    reqs = db.scalars(select(HelpRequest).where(HelpRequest.created_at >= since)).all()
    cats = {c.slug: c.label for c in db.scalars(select(RequestCategory))}
    by_cat = Counter(r.category for r in reqs)
    unmatched = Counter(r.category for r in reqs if r.status in (ReqStatus.EXPIRED,) or (r.status in ReqStatus.OPEN and r.unmatched_alerted))
    by_urgency = Counter(r.urgency for r in reqs)
    by_day: dict[str, int] = defaultdict(int)
    for r in reqs:
        by_day[r.created_at.date().isoformat()] += 1

    heat: dict[tuple[float, float], float] = defaultdict(float)
    for r in reqs:
        if r.lat is not None:
            heat[(round(r.lat, 2), round(r.lng, 2))] += {"normal": 1.0, "urgent": 2.0, "critical": 3.0}[r.urgency]
    mx = max(heat.values(), default=1.0)

    avail_by_skill = Counter()
    for us in db.scalars(select(UserSkill).join(User, User.id == UserSkill.user_id).where(User.is_available.is_(True), User.is_active.is_(True))):
        avail_by_skill[us.skill.trust_category or us.skill.slug] += 1
    gaps = []
    for slug, n in by_cat.items():
        helpers = avail_by_skill.get(slug, 0)
        ratio = n / max(helpers, 0.5)
        if slug != "other" and (helpers == 0 or ratio >= 3):
            gaps.append({"category": slug, "label": cats.get(slug, slug), "requests": n, "available_helpers": helpers, "ratio": round(ratio, 1)})
    resp = db.execute(select(TrustEvent.value).where(TrustEvent.kind == "responded", TrustEvent.created_at >= since)).scalars().all()
    resp_sorted = sorted(v for v in resp if v is not None)
    return {
        "days": days, "total_requests": len(reqs),
        "categories": [{"category": c, "label": cats.get(c, c), "count": n, "unmatched": unmatched.get(c, 0)} for c, n in by_cat.most_common()],
        "urgency": dict(by_urgency), "requests_per_day": sorted(by_day.items()),
        "response_time": {"count": len(resp_sorted), "median_s": resp_sorted[len(resp_sorted) // 2] if resp_sorted else None,
                          "p90_s": resp_sorted[int(len(resp_sorted) * 0.9)] if resp_sorted else None},
        "volunteer_availability": dict(avail_by_skill),
        "urgent_incidents": db.scalar(select(func.count()).select_from(Incident).where(Incident.started_at >= since)) or 0,
        "resource_gaps": sorted(gaps, key=lambda g: -g["ratio"]),
        "heatmap": [{"lat": k[0], "lng": k[1], "weight": round(v / mx, 3), "count": v} for k, v in sorted(heat.items(), key=lambda x: -x[1])[:300]],
    }


# ---- users / verification / trust -----------------------------------------------------------
@router.get("/users")
def users(q: str | None = Query(None, max_length=80), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
          admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    query = select(User)
    if q:
        query = query.where(User.name.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
    rows = db.scalars(query.order_by(User.id).limit(limit).offset(offset)).all()
    scores = dict(db.execute(select(TrustScore.user_id, TrustScore.score).where(TrustScore.category == "")).all())
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "is_active": u.is_active, "identity_verified": u.identity_verified,
             "phone_verified": u.phone_verified, "email_verified": u.email_verified, "trust_score": scores.get(u.id),
             "certifications": [{"slug": c.certification.slug, "verified": c.verified} for c in u.certifications],
             "created_at": u.created_at.isoformat()} for u in rows]


@router.patch("/users/{uid}/moderate")
def moderate(uid: int, body: ModerateIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == admin.id:
        raise HTTPException(400, "You cannot deactivate yourself")
    u.is_active = body.is_active
    if not body.is_active:
        u.is_available = False
    db.commit()
    return {"id": u.id, "is_active": u.is_active}


@router.post("/users/{uid}/verify")
def verify(uid: int, body: VerifyIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "User not found")
    setattr(u, f"{body.kind}_verified", body.approved)
    db.add(Verification(user_id=u.id, kind=body.kind, status="APPROVED" if body.approved else "REJECTED", reviewed_by=admin.id))
    trust_svc.refresh_trust(db, u.id)
    db.commit()
    return {"id": u.id, f"{body.kind}_verified": body.approved}


@router.post("/users/{uid}/certifications")
def verify_cert(uid: int, body: CertVerifyIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    cert = db.scalar(select(Certification).where(Certification.slug == body.certification))
    uc = db.get(UserCertification, (uid, cert.id)) if cert else None
    if uc is None:
        raise HTTPException(404, "The user has not claimed that certification")
    uc.verified = body.verified
    db.add(Verification(user_id=uid, kind="certification", status="APPROVED" if body.verified else "REJECTED", evidence=body.certification, reviewed_by=admin.id))
    trust_svc.refresh_trust(db, uid)
    db.commit()
    return {"user_id": uid, "certification": body.certification, "verified": body.verified}


@router.get("/trust-review")
def trust_review(admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Users whose behaviour signals warrant a human look (anomalies, not verdicts)."""
    flagged = []
    for u in db.scalars(select(User).where(User.is_active.is_(True))):
        card = trust_svc.compute_trust(db, u)
        stats, why = card.stats, []
        if (stats.get("no_show_rate") or 0) >= 20:
            why.append(f"No-show rate {stats['no_show_rate']}%")
        if (stats.get("cancellation_rate") or 0) >= 40:
            why.append(f"Cancellation rate {stats['cancellation_rate']}%")
        if any(f.key == "reports" for f in card.factors):
            why.append("Has upheld reports")
        if stats.get("review_count", 0) >= 3 and (stats.get("rating") or 5) < 3:
            why.append(f"Low rating {stats['rating']}")
        if why:
            flagged.append({"user_id": u.id, "name": u.name, "score": card.score, "reasons": why})
    return sorted(flagged, key=lambda x: x["score"])


# ---- requests / incidents / reports ---------------------------------------------------------
@router.get("/requests")
def admin_requests(status: str | None = None, limit: int = Query(100, ge=1, le=300), admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    q = select(HelpRequest)
    if status:
        q = q.where(HelpRequest.status == status.upper())
    return [ser.request_out(db, r, admin, "admin") for r in db.scalars(q.order_by(HelpRequest.id.desc()).limit(limit))]


@router.post("/requests/{rid}/cancel")
def admin_cancel(rid: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    req = db.get(HelpRequest, rid)
    if req is None:
        raise HTTPException(404, "Request not found")
    flow(lambda: orch.cancel(db, req, admin), db)
    db.commit()
    return {"status": req.status}


@router.get("/incidents")
def incidents(active_only: bool = False, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    q = select(Incident)
    if active_only:
        q = q.where(Incident.status == "ACTIVE")
    return [care.incident_state(db, i) | {"user_id": i.user_id, "description": i.description}
            for i in db.scalars(q.order_by(Incident.id.desc()).limit(100))]


@router.get("/reports")
def reports(status: str | None = "OPEN", admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    q = select(Report)
    if status:
        q = q.where(Report.status == status.upper())
    return [{"id": r.id, "reporter_id": r.reporter_id, "target_user_id": r.target_user_id, "request_id": r.request_id, "reason": r.reason,
             "details": r.details, "status": r.status, "created_at": r.created_at.isoformat()} for r in db.scalars(q.order_by(Report.id.desc()).limit(200))]


@router.post("/reports/{rid}/resolve")
def resolve_report(rid: int, body: ReportResolveIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    r = db.get(Report, rid)
    if r is None:
        raise HTTPException(404, "Report not found")
    if r.status != "OPEN":
        raise HTTPException(409, "Report already resolved")
    r.status, r.resolved_by = body.status, admin.id
    db.flush()
    if r.target_user_id:
        trust_svc.refresh_trust(db, r.target_user_id)
        if body.status == "UPHELD":
            notify(db, r.target_user_id, "report_upheld", "A report about you was upheld", "Repeated issues can limit your access.", {})
    db.commit()
    return {"id": r.id, "status": r.status}


# ---- protocols (versioned) ------------------------------------------------------------------
@router.get("/protocols")
def list_protocols(admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Protocol).order_by(Protocol.slug, Protocol.version.desc())).all()
    return [{"id": p.id, "slug": p.slug, "version": p.version, "title": p.title, "is_active": p.is_active, "keywords": p.situation_keywords,
             "requires_emergency_services": p.requires_emergency_services, "source": p.source, "approved_by": p.approved_by,
             "steps": [{"position": s.position, "instruction": s.instruction, "fallback_instruction": s.fallback_instruction, "is_critical": s.is_critical} for s in p.steps]}
            for p in rows]


@router.post("/protocols", status_code=201)
def create_protocol_version(body: ProtocolIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Adds a NEW version (old versions are kept for audit). The newest active version is the one NEXA CARE uses."""
    latest = db.scalar(select(func.max(Protocol.version)).where(Protocol.slug == body.slug)) or 0
    p = Protocol(slug=body.slug, version=latest + 1, title=body.title, situation_keywords=[k.lower() for k in body.situation_keywords],
                 requires_emergency_services=body.requires_emergency_services, source=body.source, approved_by=admin.id)
    for i, s in enumerate(body.steps, start=1):
        p.steps.append(ProtocolStep(position=i, instruction=s.instruction, fallback_instruction=s.fallback_instruction, is_critical=s.is_critical))
    db.add(p)
    db.commit()
    return {"id": p.id, "slug": p.slug, "version": p.version}


@router.post("/protocols/{pid}/active")
def set_protocol_active(pid: int, body: ModerateIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = db.get(Protocol, pid)
    if p is None:
        raise HTTPException(404, "Protocol not found")
    p.is_active = body.is_active
    db.commit()
    return {"id": p.id, "is_active": p.is_active}


# ---- directory ------------------------------------------------------------------------------
@router.post("/directory", status_code=201)
def dir_create(body: DirectoryIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    e = DirectoryEntry(**body.model_dump())
    db.add(e)
    db.commit()
    return {"id": e.id}


@router.put("/directory/{eid}")
def dir_update(eid: int, body: DirectoryIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    e = db.get(DirectoryEntry, eid)
    if e is None:
        raise HTTPException(404, "Entry not found")
    for k, v in body.model_dump().items():
        setattr(e, k, v)
    db.commit()
    return {"id": e.id}


@router.delete("/directory/{eid}", status_code=204)
def dir_delete(eid: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    e = db.get(DirectoryEntry, eid)
    if e is None:
        raise HTTPException(404, "Entry not found")
    db.delete(e)
    db.commit()
