from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Assignment, HelpRequest, Incident, IncidentStep, User
from ..schemas import CloseIn, EscalateIn, IncidentCreate, StepCompleteIn, UtteranceIn
from ..security import current_user
from ..services import care
from ..services import orchestrator as orch
from .requests import flow

router = APIRouter(prefix="/api/incidents", tags=["nexa-care"])


def _care(fn, db: Session):
    try:
        return fn()
    except care.CareError as e:
        db.rollback()
        raise HTTPException(e.status, str(e))


def load(db: Session, iid: int, user: User) -> Incident:
    inc = db.get(Incident, iid)
    if inc is None:
        raise HTTPException(404, "Incident not found")
    allowed = inc.user_id == user.id or user.role == "admin"
    if not allowed and inc.request_id:  # an assigned helper may follow the incident state
        allowed = bool(db.scalar(select(Assignment.id).where(Assignment.request_id == inc.request_id,
                                                              Assignment.helper_id == user.id, Assignment.status != "CANCELLED")))
    if not allowed:
        raise HTTPException(404, "Incident not found")
    return inc


def owner_only(inc: Incident, user: User) -> None:
    if inc.user_id != user.id:
        raise HTTPException(403, "Only the person in the incident can do this")


@router.post("", status_code=201)
def create(body: IncidentCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Start an emergency flow from a short description (typed or transcribed from voice)."""
    lat, lng = body.lat, body.lng
    if lat is None and user.lat is None:
        raise HTTPException(422, "Location is required so nearby helpers can reach you")
    if (lat is None) != (lng is None):
        raise HTTPException(422, "Provide both lat and lng")
    req = flow(lambda: orch.create_request(db, user, text=body.text, lat=lat, lng=lng, share_location=body.share_location,
                                           routing_mode="community", force_urgency="critical"), db)
    inc = db.get(Incident, req.incident_id)
    reply = care.start_care(db, inc)
    db.commit()
    return {"incident": reply.state, "speech": reply.speech, "request_id": req.id, "actions": reply.actions}


@router.get("/active")
def active(user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = db.scalar(select(Incident).where(Incident.user_id == user.id, Incident.status == "ACTIVE").order_by(Incident.id.desc()))
    return {"incident": care.incident_state(db, inc) if inc else None}


@router.get("/{iid}")
def get_one(iid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = load(db, iid, user)
    out = care.incident_state(db, inc)
    if inc.user_id != user.id and user.role != "admin":  # assigned helper: no personal guidance history
        out.pop("current_instruction", None)
    return out


@router.get("/{iid}/log")
def audit_log(iid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = load(db, iid, user)
    if inc.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "Audit log is only visible to the person and administrators")
    rows = db.scalars(select(IncidentStep).where(IncidentStep.incident_id == iid).order_by(IncidentStep.id)).all()
    return [{"id": r.id, "kind": r.kind, "actor": r.actor, "step": r.step_position, "content": r.content, "meta": r.meta,
             "at": r.created_at.isoformat()} for r in rows]


@router.post("/{iid}/start-care")
def start_care(iid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = load(db, iid, user)
    owner_only(inc, user)
    r = _care(lambda: care.start_care(db, inc), db)
    db.commit()
    return {"speech": r.speech, "incident": r.state, "actions": r.actions}


@router.post("/{iid}/say")
def say(iid: int, body: UtteranceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One conversational turn (voice transcript or typed)."""
    inc = load(db, iid, user)
    owner_only(inc, user)
    r = _care(lambda: care.handle_utterance(db, inc, body.text), db)
    db.commit()
    return {"speech": r.speech, "incident": r.state, "actions": r.actions}


@router.post("/{iid}/step-complete")
def step_complete(iid: int, body: StepCompleteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = load(db, iid, user)
    owner_only(inc, user)
    r = _care(lambda: care.step_unable(db, inc) if body.unable else care.step_complete(db, inc, body.step), db)
    db.commit()
    return {"speech": r.speech, "incident": r.state, "actions": r.actions}


@router.post("/{iid}/escalate")
def escalate(iid: int, body: EscalateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = load(db, iid, user)
    owner_only(inc, user)
    r = _care(lambda: care.escalate(db, inc, body.emergency_contacted, body.note), db)
    db.commit()
    return {"speech": r.speech, "incident": r.state, "actions": r.actions, "emergency_number": get_settings().emergency_number}


@router.post("/{iid}/close")
def close(iid: int, body: CloseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = load(db, iid, user)
    if inc.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "Only the person in the incident can end it")
    r = _care(lambda: care.close(db, inc, body.resolution, body.reason, actor="admin" if user.role == "admin" and inc.user_id != user.id else "user"), db)
    # closing an incident that is still waiting for help also closes the linked help request
    req = db.get(HelpRequest, inc.request_id) if inc.request_id else None
    if req is not None and body.resolution == "CANCELLED" and req.status not in ("COMPLETED", "RATED", "CANCELLED", "EXPIRED"):
        try:
            orch.cancel(db, req, user)
        except orch.FlowError:
            pass
    db.commit()
    return {"speech": r.speech, "incident": r.state, "actions": r.actions}
