"""NEXA CARE - voice-guided support during an incident.

Safety design:
  * Medical content comes ONLY from admin-managed, versioned `protocols`. No LLM writes instructions.
  * The conversation layer is deterministic: it detects what the user said (done / can't / dizzy /
    help arrived ...), moves through approved steps, and wraps them in short conversational framing.
  * Emergency services are advised for every critical incident. NEXA never claims to replace them
    and cannot dial on the user's behalf; it shows the number and records what the user reports.
  * Every turn and state change is written to `incident_steps` (audit log).
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Assignment, HelpRequest, Incident, IncidentStep, Protocol, ReqStatus, User, utcnow
from . import nlu
from .realtime import emit, notify

DISCLAIMER = "NEXA connects you with neighbours and guides you with approved first-aid steps. It does not replace emergency services."

CHANGE_PATTERNS = ["dizzy", "faint", "lightheaded", "light-headed", "worse", "numb", "confus", "pass out", "passing out",
                   "blurry", "can't see", "cold", "shaking", "sick", "nausea", "vomit", "sleepy", "weak"]
DONE_RE = re.compile(r"\b(done|completed?|finished|did (it|that)|i('ve| have) (done|applied|pressed)|okay,? i (did|completed|have)|got it|ok(ay)? i did|pressing|applied)\b", re.I)
CANT_RE = re.compile(r"\b(can'?t|cannot|unable|not able|don'?t have|do not have|no (cloth|water|ice)|won'?t work|too painful|hurts too much)\b", re.I)
ARRIVED_RE = re.compile(r"\b(help (has |have )?arrived|(they|he|she|someone|helper|ambulance|paramedics?|neighbou?rs?) (is|are|has|have)? ?(arrived|here)|(they'?re|he'?s|she'?s) here|arrived|is here now)\b", re.I)
STATUS_RE = re.compile(r"\b(where (is|are)|how (far|long)|eta|when will|how soon|any(one| one) coming|status)\b", re.I)
REPEAT_RE = re.compile(r"\b(repeat|again|what did you say|say that|didn'?t (hear|catch)|pardon)\b", re.I)
STOP_RE = re.compile(r"\b(stop|cancel|end (it|this|care)|never ?mind|false alarm|i'?m (fine|okay|ok|safe) now)\b", re.I)
CALLED_RE = re.compile(r"\b(i )?(called|rang|dialed|dialled|phoned) (the )?(ambulance|emergency|112|911|999|100|108|police)|(ambulance|paramedics?) (is|are) (coming|on (the|their) way)", re.I)
NEED_EMERGENCY_RE = re.compile(r"\b(call (an )?ambulance|need (an )?ambulance|call emergency|emergency services)\b", re.I)


@dataclass
class CareReply:
    speech: str
    state: dict
    actions: list[str] = field(default_factory=list)  # UI hints: show_emergency_banner, closed, step_advanced ...


def audit(db: Session, incident_id: int, kind: str, actor: str = "system", content: str = "",
          step: int | None = None, meta: dict | None = None) -> None:
    db.add(IncidentStep(incident_id=incident_id, kind=kind, step_position=step, actor=actor, content=content, meta=meta or {}))


def emergency_advice() -> str:
    n = get_settings().emergency_number
    return f"If this is serious, call {n} now. {DISCLAIMER}"


# ---- protocol selection (controlled) ------------------------------------------------------
def active_protocols(db: Session) -> list[Protocol]:
    latest = select(Protocol.slug, func.max(Protocol.version).label("v")).where(Protocol.is_active.is_(True)).group_by(Protocol.slug).subquery()
    return list(db.scalars(select(Protocol).join(latest, (Protocol.slug == latest.c.slug) & (Protocol.version == latest.c.v))
                           .where(Protocol.is_active.is_(True))))


def select_protocol(db: Session, text: str, *, exclude_slug: str | None = None) -> tuple[Protocol | None, int]:
    """Returns (protocol, keyword hits). Falls back to GENERAL_DISTRESS with 0 hits."""
    t = text.lower()
    best, best_hits = None, 0
    protos = active_protocols(db)
    for p in protos:
        if p.slug == exclude_slug:
            continue
        hits = sum(1 for k in p.situation_keywords if k in t)
        if hits > best_hits or (hits == best_hits and hits > 0 and best and p.requires_emergency_services and not best.requires_emergency_services):
            best, best_hits = p, hits
    if best is None:
        best = next((p for p in protos if p.slug == "GENERAL_DISTRESS"), None)
    return best, best_hits


def situation_slug(text: str, protocol: Protocol | None) -> str:
    t = text.lower()
    if any(w in t for w in ("bike", "bicycle", "cycle", "scooter", "motorbike")) and any(w in t for w in ("fell", "fall", "crash", "skid", "accident")):
        return "bike_fall"
    if "fell" in t or "fall" in t:
        return "fall"
    return protocol.slug.lower() if protocol else "unknown"


# ---- state ---------------------------------------------------------------------------------
def display_id(i: Incident) -> str:
    return f"INC-{10000 + i.id}"


def _step_list(i: Incident):
    return i.protocol.steps if i.protocol else []


def _active_assignment(db: Session, i: Incident) -> Assignment | None:
    if not i.request_id:
        return None
    return db.scalar(select(Assignment).where(Assignment.request_id == i.request_id, Assignment.status.in_(["ACTIVE", "ARRIVED"]))
                     .order_by(Assignment.accepted_at))


def skipped_steps(db: Session, i: Incident) -> list[int]:
    db.flush()  # autoflush is off; include audit rows written earlier in this transaction
    rows = db.scalars(select(IncidentStep).where(IncidentStep.incident_id == i.id, IncidentStep.kind == "step_skipped")).all()
    return sorted({r.step_position for r in rows if r.step_position and (r.meta or {}).get("protocol_id") == i.protocol_id})


def incident_state(db: Session, i: Incident) -> dict:
    steps = _step_list(i)
    cur = next((s for s in steps if s.position == i.current_step), None)
    asg = _active_assignment(db, i)
    return {
        "incident_id": display_id(i), "id": i.id, "status": i.status, "urgency": i.urgency.upper(),
        "location_shared": i.location_shared, "situation": i.situation, "user_responsive": i.user_responsive,
        "current_protocol": i.protocol.slug if i.protocol else None, "protocol_title": i.protocol.title if i.protocol else None,
        "protocol_version": i.protocol.version if i.protocol else None,
        "current_step": i.current_step, "total_steps": len(steps), "completed_steps": list(i.completed_steps or []),
        "skipped_steps": skipped_steps(db, i),
        "current_instruction": cur.instruction if cur and i.status == "ACTIVE" else None,
        "protocol_finished": bool(steps) and i.current_step > len(steps),
        "assigned_helper": f"USR-{asg.helper_id}" if asg else None, "assigned_helper_name": asg.helper.name if asg else None,
        "helper_eta_minutes": asg.eta_minutes if asg else None,
        "helper_arrived": bool(asg and asg.status == "ARRIVED"),
        "emergency_services_advised": i.emergency_services_advised, "emergency_services_contacted": i.emergency_services_contacted,
        "emergency_number": get_settings().emergency_number, "escalation_level": i.escalation_level,
        "care_active": i.care_active, "request_id": i.request_id, "started_at": i.started_at.isoformat() if i.started_at else None,
        "disclaimer": DISCLAIMER,
    }


def _push(db: Session, i: Incident) -> None:
    uids = {i.user_id}
    asg = _active_assignment(db, i)
    if asg:
        uids.add(asg.helper_id)
    for uid in uids:
        emit(db, uid, {"type": "incident_update", "incident_id": i.id})


# ---- lifecycle -----------------------------------------------------------------------------
def ensure_incident(db: Session, req: HelpRequest) -> Incident:
    if req.incident_id:
        return db.get(Incident, req.incident_id)
    proto, hits = select_protocol(db, req.raw_text)
    i = Incident(user_id=req.requester_id, urgency="critical", situation=situation_slug(req.raw_text, proto), description=req.description,
                 location_shared=req.location_shared, lat=req.lat if req.location_shared else None, lng=req.lng if req.location_shared else None,
                 protocol_id=proto.id if proto else None, current_step=1 if proto else 0, completed_steps=[],
                 emergency_services_advised=True, care_active=True, request_id=req.id)
    db.add(i)
    db.flush()
    db.refresh(i)
    req.incident_id = i.id
    audit(db, i.id, "protocol_selected", "nexa", f"{proto.slug} v{proto.version}" if proto else "none",
          meta={"keyword_hits": hits, "protocol_id": proto.id if proto else None, "source_text": req.raw_text[:300]})
    audit(db, i.id, "state_change", "system", "emergency services advised", meta={"number": get_settings().emergency_number})
    if proto and proto.steps:
        audit(db, i.id, "step_presented", "nexa", proto.steps[0].instruction, step=1, meta={"protocol_id": proto.id})
    notify(db, req.requester_id, "emergency_advice", f"Call {get_settings().emergency_number} if this is serious",
           f"{DISCLAIMER} NEXA CARE is with you.", {"incident_id": i.id, "request_id": req.id})
    for admin in db.scalars(select(User).where(User.role == "admin")):
        notify(db, admin.id, "critical_incident", f"Critical incident {display_id(i)}", req.title, {"incident_id": i.id})
    _push(db, i)
    return i


def present_current(db: Session, i: Incident) -> str:
    steps = _step_list(i)
    cur = next((s for s in steps if s.position == i.current_step), None)
    return cur.instruction if cur else ""


def start_care(db: Session, i: Incident) -> CareReply:
    i.care_active = True
    if i.protocol_id is None:
        proto, _ = select_protocol(db, i.description or "")
        i.protocol_id = proto.id if proto else None
        db.flush(); db.refresh(i)
    if i.current_step < 1:
        i.current_step = 1
    audit(db, i.id, "state_change", "system", "care started")
    speech = ("I'm here with you. " + emergency_advice() + " Here is your first step. " + present_current(db, i)).strip()
    audit(db, i.id, "nexa_said", "nexa", speech, step=i.current_step)
    _push(db, i)
    return CareReply(speech, incident_state(db, i), ["show_emergency_banner"])


def _advance(db: Session, i: Incident, completed: bool) -> str:
    steps = _step_list(i)
    pos = i.current_step
    if completed and pos not in (i.completed_steps or []):
        i.completed_steps = sorted({*(i.completed_steps or []), pos})
    i.current_step = pos + 1
    if i.current_step > len(steps):
        msg = "That was the last step. Keep still and stay where you are. Help is on the way, and I'll stay with you."
        audit(db, i.id, "state_change", "nexa", "protocol finished", step=pos)
        return msg
    nxt = present_current(db, i)
    audit(db, i.id, "step_presented", "nexa", nxt, step=i.current_step, meta={"protocol_id": i.protocol_id})
    return nxt


def step_complete(db: Session, i: Incident, step: int | None = None) -> CareReply:
    _require_active(i)
    if step is not None and step != i.current_step:
        raise CareError("That is not the current step", 409)
    if i.current_step > len(_step_list(i)):
        return CareReply("You have completed all steps. Help is on the way. Tell me if anything changes.", incident_state(db, i))
    audit(db, i.id, "step_completed", "user", "", step=i.current_step, meta={"protocol_id": i.protocol_id})
    nxt = _advance(db, i, completed=True)
    speech = f"Good. Let's continue with the next step. {nxt}" if i.current_step <= len(_step_list(i)) else nxt
    audit(db, i.id, "nexa_said", "nexa", speech, step=i.current_step)
    _push(db, i)
    return CareReply(speech, incident_state(db, i), ["step_advanced"])


def step_unable(db: Session, i: Incident) -> CareReply:
    _require_active(i)
    steps = _step_list(i)
    cur = next((s for s in steps if s.position == i.current_step), None)
    if cur is None:
        return CareReply("There are no more steps. Help is on the way.", incident_state(db, i))
    audit(db, i.id, "step_skipped", "user", "user unable to perform step", step=cur.position, meta={"protocol_id": i.protocol_id})
    fb = cur.fallback_instruction or "That's okay."
    extra = ""
    actions = ["step_advanced"]
    if cur.is_critical:
        extra = f" This step matters, so please call {get_settings().emergency_number} if you can, or ask anyone nearby to."
        i.emergency_services_advised = True
        actions.append("show_emergency_banner")
    nxt = _advance(db, i, completed=False)
    speech = f"Okay. I'll adjust the guidance. {fb}{extra}" + (f" When you're ready: {nxt}" if i.current_step <= len(steps) else f" {nxt}")
    audit(db, i.id, "nexa_said", "nexa", speech, step=i.current_step)
    _push(db, i)
    return CareReply(speech, incident_state(db, i), actions)


def report_change(db: Session, i: Incident, text: str) -> CareReply:
    """Situation changed (e.g. 'I'm feeling dizzy'). Switch to a verified protocol; raise escalation."""
    _require_active(i)
    i.escalation_level += 1
    flags = nlu.detect_red_flags(text)
    prev = i.protocol
    # Only switch when the text really matches another approved protocol; otherwise stay on the
    # current one and raise the emergency advice (never improvise guidance).
    new, hits = select_protocol(db, text, exclude_slug=prev.slug if prev else None)
    if hits == 0:
        new = None
    i.user_responsive = True
    audit(db, i.id, "state_change", "user", "situation change reported", meta={"red_flags": flags, "text": text[:300]})
    parts = []
    if flags or i.escalation_level >= 2:
        i.emergency_services_advised = True
        parts.append(f"This sounds more serious. Please call {get_settings().emergency_number} now if you haven't already.")
    if new is not None and (prev is None or new.id != prev.id):
        audit(db, i.id, "state_change", "nexa", f"protocol switched {prev.slug if prev else None} -> {new.slug}",
              meta={"from_step": i.current_step, "from_completed": list(i.completed_steps or []), "protocol_id": new.id})
        i.protocol_id, i.current_step, i.completed_steps = new.id, 1, []
        db.flush(); db.refresh(i)
        if prev and prev.slug == "BLEEDING_ASSISTANCE":
            parts.append("Keep holding pressure on the wound.")
        parts.append(f"Thanks for telling me. Let's follow the guidance for {new.title.lower()}. " + present_current(db, i))
        audit(db, i.id, "step_presented", "nexa", present_current(db, i), step=1, meta={"protocol_id": new.id})
    else:
        parts.append("Thanks for telling me. Stay still and keep doing the current step." + (" " + present_current(db, i) if present_current(db, i) else ""))
    speech = " ".join(parts)
    audit(db, i.id, "nexa_said", "nexa", speech, step=i.current_step)
    _widen_help(db, i)
    _push(db, i)
    return CareReply(speech, incident_state(db, i), ["show_emergency_banner", "situation_changed"])


def _widen_help(db: Session, i: Incident) -> None:
    """On escalation, notify more suitable helpers and tell admins."""
    req = db.get(HelpRequest, i.request_id) if i.request_id else None
    if req is None or req.status not in ReqStatus.OPEN:
        return
    from . import orchestrator  # local import to avoid cycle

    s = get_settings()
    req.search_radius_km = min(s.max_search_radius_km, (req.search_radius_km or s.community_radius_km) * 1.5)
    orchestrator._notify_community(db, req, s.broadcast_size)
    for admin in db.scalars(select(User).where(User.role == "admin")):
        notify(db, admin.id, "incident_escalated", f"{display_id(i)} escalated", f"Level {i.escalation_level}", {"incident_id": i.id})


def escalate(db: Session, i: Incident, emergency_contacted: bool = False, note: str = "") -> CareReply:
    _require_active(i)
    i.escalation_level += 1
    i.emergency_services_advised = True
    if emergency_contacted:
        i.emergency_services_contacted = True
    audit(db, i.id, "escalated", "user", note or "user escalated", meta={"emergency_contacted": emergency_contacted, "level": i.escalation_level})
    _widen_help(db, i)
    n = get_settings().emergency_number
    speech = ("Okay, noted that you've contacted emergency services. I'm asking more helpers nearby and I'll stay with you." if emergency_contacted
              else f"Please call {n} now. I'm asking more helpers nearby and I'll stay with you.")
    audit(db, i.id, "nexa_said", "nexa", speech)
    _push(db, i)
    return CareReply(speech, incident_state(db, i), ["show_emergency_banner"])


def close(db: Session, i: Incident, resolution: str = "RESOLVED", reason: str = "", actor: str = "user") -> CareReply:
    if i.status != "ACTIVE":
        return CareReply("This care session has already ended.", incident_state(db, i), ["closed"])
    i.status = resolution
    i.care_active = False
    i.closed_at = utcnow()
    audit(db, i.id, "closed", actor, reason or resolution, meta={"resolution": resolution})
    _push(db, i)
    speech = ("Okay. I'll end NEXA CARE. I'm glad help is with you. Please follow their guidance." if resolution == "RESOLVED"
              else "Okay. I've stopped NEXA CARE. If you need help again, I'm here.")
    return CareReply(speech, incident_state(db, i), ["closed"])


class CareError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _require_active(i: Incident) -> None:
    if i.status != "ACTIVE":
        raise CareError("This incident is closed", 409)


# ---- conversation --------------------------------------------------------------------------
def handle_utterance(db: Session, i: Incident, text: str) -> CareReply:
    text = (text or "").strip()
    if not text:
        raise CareError("Say or type something")
    if i.status != "ACTIVE":
        return CareReply("This care session has ended. Start a new one if you need help.", incident_state(db, i), ["closed"])
    audit(db, i.id, "user_said", "user", text)

    if _claims_arrival(text):
        return _on_user_says_arrived(db, i)
    if STOP_RE.search(text) and not CANT_RE.search(text):
        return close(db, i, "CANCELLED", text)
    if CALLED_RE.search(text):
        return escalate(db, i, emergency_contacted=True, note=text)
    if NEED_EMERGENCY_RE.search(text):
        return escalate(db, i, emergency_contacted=False, note=text)
    if nlu.detect_red_flags(text) or any(k in text.lower() for k in CHANGE_PATTERNS):
        return report_change(db, i, text)
    if CANT_RE.search(text):
        return step_unable(db, i)
    if DONE_RE.search(text):
        return step_complete(db, i)
    if STATUS_RE.search(text):
        return _status_reply(db, i)
    if REPEAT_RE.search(text):
        cur = present_current(db, i)
        speech = f"Sure. {cur}" if cur else "You have completed all the steps. Help is on the way."
        audit(db, i.id, "nexa_said", "nexa", speech, step=i.current_step)
        return CareReply(speech, incident_state(db, i))
    cur = present_current(db, i)
    speech = ("I can only give approved first-aid guidance. " + (f"Your current step: {cur} " if cur else "") +
              f"Say 'done' when finished, or 'I can't' if you can't. If you're unsure, call {get_settings().emergency_number}.")
    audit(db, i.id, "nexa_said", "nexa", speech, step=i.current_step)
    return CareReply(speech, incident_state(db, i))


NEGATION_RE = re.compile(r"\b(not|no one|nobody|yet|when|still waiting)\b|n't", re.I)


def _claims_arrival(text: str) -> bool:
    """'Help has arrived' closes care; 'hasn't arrived yet' or 'has help arrived?' must not."""
    if not ARRIVED_RE.search(text) or NEGATION_RE.search(text):
        return False
    return not (text.rstrip().endswith("?") or re.match(r"\s*(has|is|are|did|will)\b", text, re.I))


def _status_reply(db: Session, i: Incident) -> CareReply:
    asg = _active_assignment(db, i)
    if asg and asg.eta_minutes:
        speech = f"{asg.helper.name.split()[0]} is about {asg.eta_minutes:.0f} minutes away. I'll keep you updated."
    elif asg:
        speech = f"{asg.helper.name.split()[0]} is on the way."
    else:
        speech = "I'm still asking helpers nearby. I'll tell you as soon as someone accepts."
    speech += f" Please also call {get_settings().emergency_number} if you haven't."
    audit(db, i.id, "nexa_said", "nexa", speech)
    return CareReply(speech, incident_state(db, i))


def _on_user_says_arrived(db: Session, i: Incident) -> CareReply:
    req = db.get(HelpRequest, i.request_id) if i.request_id else None
    if req is not None:
        asg = _active_assignment(db, i)
        if asg is not None and asg.status == "ACTIVE":
            asg.status, asg.arrived_at = "ARRIVED", utcnow()
            if req.status in (ReqStatus.ACCEPTED, ReqStatus.ON_THE_WAY):
                from . import orchestrator
                orchestrator.transition(db, req, ReqStatus.IN_PROGRESS, i.user_id, "user confirmed help arrived")
    reply = close(db, i, "RESOLVED", "user confirmed help arrived")
    audit(db, i.id, "nexa_said", "nexa", reply.speech)
    return reply


# ---- hooks called by orchestrator ----------------------------------------------------------
def on_helper_assigned(db: Session, req: HelpRequest, asg: Assignment) -> None:
    i = db.get(Incident, req.incident_id)
    audit(db, i.id, "state_change", "system", f"helper USR-{asg.helper_id} assigned", meta={"eta_minutes": asg.eta_minutes})
    _push(db, i)


def on_helper_arrived(db: Session, req: HelpRequest) -> None:
    i = db.get(Incident, req.incident_id)
    audit(db, i.id, "state_change", "system", "helper marked arrived")
    _push(db, i)


def on_request_closed(db: Session, req: HelpRequest, resolution: str) -> None:
    i = db.get(Incident, req.incident_id)
    if i and i.status == "ACTIVE":
        close(db, i, resolution, f"request {resolution.lower()}", actor="system")
