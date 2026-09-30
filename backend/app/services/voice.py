"""Voice assistant conversation manager (text in, speech text out).

Speech-to-text and text-to-speech happen in the client (Web Speech API) or via a configured STT
provider; this module turns a transcript into an action and the words NEXA should say. The
conversation is stateless on the server: the client echoes back a small validated `context`.
Emergencies never go through a multi-turn questionnaire - they start NEXA CARE immediately.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Assignment, HelpRequest, Incident, RelationshipType, ReqStatus, User
from . import care, nlu
from .nlu import strip_wake_word
from . import circle as circle_svc
from . import orchestrator as orch

YES_RE = re.compile(r"\b(yes|yeah|yep|sure|please do|go ahead|ok(ay)?|do it|confirm|correct)\b", re.I)
NO_RE = re.compile(r"\b(no|nope|nah|don'?t|community|directly|skip)\b", re.I)
CUSTOM_RE = re.compile(r"\b(custom|choose|pick|select)\b", re.I)
CANCEL_RE = re.compile(r"\b(cancel|never ?mind|forget (it|that)|call it off)\b", re.I)
STATUS_RE = re.compile(r"\b(status|what'?s happening|any update|any news|where is|how far|eta|has anyone|did anyone|who is coming|is anyone coming)\b", re.I)
UPDATE_RE = re.compile(r"\b(actually|change|update|make it|instead)\b", re.I)
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def _num(n: int) -> str:
    return WORDS[n] if n < len(WORDS) else str(n)


def circle_summary(db: Session, user: User, lat: float | None, lng: float | None) -> dict:
    members = circle_svc.circle_members(db, user, lat=lat, lng=lng)
    groups = {"family": 0, "friends": 0, "other": 0}
    for m in members:
        rt = db.get(RelationshipType, m.edge.relationship_type)
        groups[rt.group if rt else "other"] += 1
    parts = []
    if groups["family"]:
        parts.append(f"{_num(groups['family'])} relative{'s' if groups['family'] != 1 else ''}")
    if groups["friends"]:
        parts.append(f"{_num(groups['friends'])} trusted friend{'s' if groups['friends'] != 1 else ''}")
    if groups["other"]:
        parts.append(f"{_num(groups['other'])} trusted neighbour{'s' if groups['other'] != 1 else ''}")
    phrase = " and ".join([", ".join(parts[:-1]), parts[-1]] if len(parts) > 1 else parts)
    return {"count": len(members), "groups": groups, "phrase": phrase,
            "members": [{"id": m.user.id, "name": m.user.name, "distance_km": m.distance_km, "available": m.available} for m in members]}


def _latest_request(db: Session, user: User, statuses=None) -> HelpRequest | None:
    q = select(HelpRequest).where(HelpRequest.requester_id == user.id)
    q = q.where(HelpRequest.status.in_(statuses or ReqStatus.ACTIVE))
    return db.scalar(q.order_by(HelpRequest.id.desc()))


def _status_speech(db: Session, req: HelpRequest) -> str:
    asg = db.scalar(select(Assignment).where(Assignment.request_id == req.id, Assignment.status.in_(["ACTIVE", "ARRIVED"])))
    if asg:
        first = asg.helper.name.split()[0]
        if asg.status == "ARRIVED":
            return f"{first} has arrived."
        return f"{first} accepted and is about {asg.eta_minutes:.0f} minutes away." if asg.eta_minutes else f"{first} accepted your request."
    return {
        ReqStatus.TRUSTED_CIRCLE: "I'm waiting to hear back from your trusted circle.",
        ReqStatus.HELPERS_NOTIFIED: "I've asked nearby helpers and I'm waiting for someone to accept.",
        ReqStatus.MATCHING: "I'm still looking for someone suitable nearby.",
        ReqStatus.ESCALATED: "I'm finding a community helper for you.",
    }.get(req.status, f"Your request is {req.status.replace('_', ' ').lower()}.")


def handle(db: Session, user: User, *, text: str, lat: float | None, lng: float | None, share_location: bool, ctx: dict) -> dict:
    text, _ = strip_wake_word(text)
    lat = lat if lat is not None else user.lat
    lng = lng if lng is not None else user.lng
    out = {"speech": "", "context": {}, "actions": [], "data": {}}

    # 0. an active incident owns the conversation
    inc = db.scalar(select(Incident).where(Incident.user_id == user.id, Incident.status == "ACTIVE").order_by(Incident.id.desc()))
    if inc is not None and ctx.get("stage") is None:
        r = care.handle_utterance(db, inc, text)
        return {"speech": r.speech, "context": {}, "actions": r.actions + ["care"], "data": {"incident": r.state}}

    # 1. answers to a pending question
    if ctx.get("stage") == "awaiting_circle_choice" and ctx.get("draft_text"):
        if CUSTOM_RE.search(text):
            return {**out, "speech": "Okay. Choose who should receive this request.", "actions": ["open_custom"],
                    "context": {"stage": "awaiting_circle_choice", "draft_text": ctx["draft_text"]}}
        if NO_RE.search(text) and not YES_RE.search(text):
            return _create(db, user, ctx["draft_text"], lat, lng, share_location, "community")
        if YES_RE.search(text):
            return _create(db, user, ctx["draft_text"], lat, lng, share_location, "circle_first")
        return {**out, "speech": "Sorry, should I ask your trusted circle first? Say yes, or say community to go straight to nearby helpers.",
                "context": ctx}
    if ctx.get("stage") == "awaiting_cancel_confirm" and ctx.get("request_id"):
        if YES_RE.search(text):
            req = db.get(HelpRequest, ctx["request_id"])
            if req and req.requester_id == user.id and req.status not in ReqStatus.TERMINAL:
                orch.cancel(db, req, user)
                return {**out, "speech": "Okay, I've cancelled your request.", "actions": ["request_cancelled"], "data": {"request_id": req.id}}
        return {**out, "speech": "Okay, I'll keep your request open."}

    # 2. intents on existing requests
    req = _latest_request(db, user)
    if req is not None and orch_claims_arrival(text):
        return _arrived(db, user, req)
    if req is not None and CANCEL_RE.search(text):
        return {**out, "speech": f"Do you want me to cancel \"{req.title}\"?", "context": {"stage": "awaiting_cancel_confirm", "request_id": req.id}}
    if req is not None and STATUS_RE.search(text):
        return {**out, "speech": _status_speech(db, req), "data": {"request_id": req.id, "status": req.status}}
    if req is not None and UPDATE_RE.search(text) and req.status not in (ReqStatus.IN_PROGRESS, ReqStatus.ON_THE_WAY):
        u = nlu.rule_understand(text)
        changed = []
        if u.num_helpers != 1 or any(w in text.lower() for w in NUM):
            n = max([int(d) for d in re.findall(r"\d+", text)] + [NUM[w] for w in NUM if re.search(rf"\b{w}\b", text.lower())] + [0])
            if 1 <= n <= 20 and n >= req.filled_slots:
                req.num_helpers = n
                changed.append(f"{_num(n)} helper{'s' if n != 1 else ''}")
        if changed:
            return {**out, "speech": f"Done. I've updated your request to {', '.join(changed)}.", "data": {"request_id": req.id}}
        return {**out, "speech": "What would you like to change? For example, say 'make it two people'."}

    # 3. a new request
    u = nlu.understand(text)
    if u.urgency == "critical":
        if lat is None:
            return {**out, "speech": "I need your location to get help to you. Please allow location access, then tell me again. If this is serious, call the emergency number now.",
                    "actions": ["need_location", "show_emergency_banner"]}
        r = orch.create_request(db, user, text=text, lat=lat, lng=lng, share_location=share_location, routing_mode="community", force_urgency="critical")
        inc = db.get(Incident, r.incident_id)
        reply = care.start_care(db, inc)
        return {**out, "speech": reply.speech, "actions": reply.actions + ["care"], "data": {"incident": reply.state, "request_id": r.id}}
    if lat is None:
        return {**out, "speech": "I can help with that. I need your location first. Please allow location access.", "actions": ["need_location"]}
    summary = circle_summary(db, user, lat, lng)
    if u.urgency == "normal" and summary["count"] > 0:
        speech = (f"I can help with that. You have {summary['phrase']} nearby. Would you like me to ask them first?")
        return {**out, "speech": speech, "context": {"stage": "awaiting_circle_choice", "draft_text": text},
                "data": {"understanding": u.to_dict(), "circle": summary}, "actions": ["choose_routing"]}
    return _create(db, user, text, lat, lng, share_location, "community" if u.urgency == "normal" else "circle_first")


def orch_claims_arrival(text: str) -> bool:
    return care._claims_arrival(text)


def _create(db: Session, user: User, text: str, lat, lng, share_location: bool, mode: str) -> dict:
    req = orch.create_request(db, user, text=text, lat=lat, lng=lng, share_location=share_location, routing_mode=mode)
    if req.status == ReqStatus.TRUSTED_CIRCLE:
        speech = "Okay, I've asked your trusted circle. I'll move on to nearby helpers if nobody answers in time."
    elif req.status == ReqStatus.HELPERS_NOTIFIED:
        speech = "Okay. I've asked suitable helpers nearby. I'll tell you as soon as someone accepts."
    else:
        speech = "I'm looking for someone nearby and I'll keep widening the search."
    return {"speech": speech, "context": {}, "actions": ["request_created"], "data": {"request_id": req.id, "status": req.status}}


def _arrived(db: Session, user: User, req: HelpRequest) -> dict:
    asg = db.scalar(select(Assignment).where(Assignment.request_id == req.id, Assignment.status == "ACTIVE"))
    if asg is None:
        return {"speech": "I don't see a helper assigned yet. Is someone else with you?", "context": {}, "actions": [], "data": {}}
    asg.status = "ARRIVED"
    if req.status in (ReqStatus.ACCEPTED, ReqStatus.ON_THE_WAY):
        orch.transition(db, req, ReqStatus.IN_PROGRESS, user.id, "requester confirmed arrival by voice")
    return {"speech": f"Great, {asg.helper.name.split()[0]} is with you. Tell me when you're done and I'll close the request.",
            "context": {}, "actions": ["helper_arrived"], "data": {"request_id": req.id}}
