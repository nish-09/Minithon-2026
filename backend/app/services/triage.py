"""Assistive first-aid triage: observable signs + the person's description + targeted answers -> a conservative level.

This is NOT diagnosis. It never names a condition from a camera frame; it reports what was *observed*,
what is only *inferred* and what is *unknown*, and always keeps professional help one tap away.
The red-flag layer runs first and short-circuits to CRITICAL. Step wording is fixed, conservative, and
carries no dosing, medication or invasive instructions (same policy as protocols_data.py).
Wording must be reviewed by a qualified clinician before real-world deployment.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import urllib.request
from dataclasses import asdict, dataclass, field

from ..config import get_settings

log = logging.getLogger("nexa.triage")

LIMITS = ("NEXA gives general first-aid guidance from what is visible and what you tell me. It cannot diagnose, "
          "cannot confirm how serious something is, and does not replace emergency services or a healthcare professional.")

# what a camera / the person can report as visible (closed vocabulary; also the only keys the vision model may return)
OBSERVATIONS = {
    "heavy_bleeding": "heavy bleeding",
    "bleeding": "bleeding",
    "open_wound": "an open wound",
    "swelling": "swelling",
    "bruising": "bruising",
    "redness": "redness",
    "burn": "a possible burn",
    "deformity": "an unusual shape or position of a limb",
    "foreign_object": "an object in the wound",
    "unresponsive": "a person who does not respond",
    "distress": "visible distress",
    "cannot_move_part": "difficulty moving the affected part",
}

# follow-up questions: key -> (question, topic)
QUESTIONS = {
    "bleeding_heavy": ("Is the bleeding heavy, or is it slowing down?", "bleeding"),
    "soaking_through": ("Is blood soaking through the cloth or dressing?", "bleeding"),
    "faint": ("Are you feeling faint or unusually weak?", "bleeding"),
    "can_move": ("Can you move the injured part?", "limb"),
    "can_bear_weight": ("Can you put weight on it?", "limb"),
    "heard_snap": ("Did you hear or feel a snap when it happened?", "limb"),
    "lost_consciousness": ("Did you lose consciousness, even briefly?", "head"),
    "confused": ("Are you confused or unusually sleepy?", "head"),
    "vomited": ("Have you vomited since?", "head"),
    "worsening_headache": ("Is your headache getting worse?", "head"),
    "breathing_difficulty": ("Are you having difficulty breathing right now?", "breathing"),
    "speak_sentences": ("Can you speak normally in full sentences?", "breathing"),
    "burn_large": ("Is the burn bigger than your hand, or on your face, hands, feet or groin?", "burn"),
    "severe_pain": ("Is the pain severe?", "general"),
}

TOPIC_WORDS = {
    "bleeding": ("bleed", "blood", "cut", "gash", "wound", "laceration"),
    "limb": ("ankle", "arm", "leg", "wrist", "knee", "foot", "hand", "shoulder", "swollen", "swelling", "sprain",
             "can't move", "cannot move", "fell", "fall"),
    "head": ("head", "concussion", "knocked"),
    "breathing": ("breath", "chest", "wheez"),
    "burn": ("burn", "scald"),
}

# text red-flag layer: any hit is CRITICAL (label shown to the user)
CRITICAL_PHRASES = {
    "unconscious": "unconscious or unresponsive", "unresponsive": "unconscious or unresponsive",
    "collapsed": "unconscious or unresponsive", "not breathing": "not breathing", "stopped breathing": "not breathing",
    "can't breathe": "difficulty breathing", "cannot breathe": "difficulty breathing", "trouble breathing": "difficulty breathing",
    "difficulty breathing": "difficulty breathing", "struggling to breathe": "difficulty breathing", "choking": "choking",
    "chest pain": "chest pain", "chest hurts": "chest pain", "crushing chest": "chest pain",
    "won't stop bleeding": "severe bleeding", "wont stop bleeding": "severe bleeding", "spurting": "severe bleeding",
    "heavy bleeding": "severe bleeding", "bleeding a lot": "severe bleeding", "bleeding badly": "severe bleeding",
    "seizure": "seizure", "convuls": "seizure",
    "face is drooping": "possible stroke signs", "slurred speech": "possible stroke signs", "can't speak": "possible stroke signs",
    "allergic reaction": "possible severe allergic reaction", "anaphyla": "possible severe allergic reaction",
    "throat is closing": "possible severe allergic reaction",
    "neck pain": "possible spinal injury", "can't feel my legs": "possible spinal injury", "cannot feel my legs": "possible spinal injury",
    "back injury": "possible spinal injury",
    "car accident": "possible major trauma", "hit by a car": "possible major trauma", "fell from": "possible major trauma",
    "overdose": "possible poisoning or overdose",
}

TRIGGER = re.compile(
    r"\b(fell|fall|fallen|bleed\w*|blood|burn\w*|scald\w*|swollen|swelling|hit my head|head injury|unconscious|unresponsive|"
    r"can'?t move|cannot move|got cut|cut my|chest (hurts|pain)|trouble breathing|can'?t breathe|difficulty breathing|"
    r"injur\w+|broke\w*|sprain\w*|seizure|collapsed|choking|allergic)\b", re.I)

# fixed, conservative wording: key -> (icon, text)
STEPS = {
    "emergency": ("phone", "Call your local emergency number now. Say where you are and what happened."),
    "safe": ("shield", "Stay in a safe place away from traffic or hazards. Sit or lie down if you feel faint."),
    "pressure": ("hand", "Press firmly on the bleeding with a clean cloth or gauze. Keep pressing without lifting to check."),
    "keep_pressure": ("hand", "If blood soaks through, add more cloth on top. Do not remove the first one."),
    "still_limb": ("pause", "Keep the injured part as still as you can. Do not try to straighten it or move it into position."),
    "no_weight": ("footprints", "Do not put weight on the injured leg or foot."),
    "ice_wrapped": ("snowflake", "You can rest it and hold something cold, wrapped in cloth, on it for short periods. Never put ice straight on skin."),
    "cool": ("droplet", "Hold a burn under cool (not ice-cold) running water for 20 minutes, then cover loosely with a clean cloth. No creams or ice."),
    "head_rest": ("pause", "Rest somewhere safe and keep still. Do not drive. Have someone stay with you."),
    "no_move_neck": ("shield", "Do not move your head, neck or back. Stay as still as you can until help arrives."),
    "breath_sit": ("wind", "Sit upright, loosen tight clothing, and breathe slowly and steadily."),
    "recovery": ("shield", "If the person is breathing but will not wake, and there is no sign of a neck injury, roll them onto their side and stay with them."),
    "see_clinician": ("stethoscope", "Have a healthcare professional look at this. If you cannot get there safely, ask a helper or someone nearby."),
    "monitor": ("eye", "Keep watching how it changes. Tell me if it gets worse, or if you feel faint, confused or short of breath."),
}


@dataclass
class Triage:
    level: str
    summary: str
    reasons: list[str]
    red_flags: list[str]
    observed: list[str]
    inferred: list[str]
    unknown: list[str]
    questions: list[dict]
    steps: list[dict]
    call_emergency: bool
    notify_circle: bool
    topics: list[str] = field(default_factory=list)
    limits: str = LIMITS

    def to_dict(self) -> dict:
        return asdict(self)


def needs_visual_assessment(text: str) -> bool:
    return bool(TRIGGER.search(text or ""))


def _topics(t: str, obs: set[str], ans: dict[str, bool]) -> list[str]:
    out = [k for k, words in TOPIC_WORDS.items() if any(w in t for w in words)]
    extra = [("bleeding", {"heavy_bleeding", "bleeding", "open_wound"}), ("limb", {"deformity", "swelling", "cannot_move_part"}),
             ("burn", {"burn"})]
    for topic, keys in extra:
        if obs & keys and topic not in out:
            out.append(topic)
    for k in ans:
        topic = QUESTIONS[k][1]
        if topic != "general" and topic not in out:
            out.append(topic)
    return out


def assess(text: str, observations: list[str], answers: dict[str, bool]) -> Triage:
    t = (text or "").lower()
    obs = {o for o in observations if o in OBSERVATIONS}
    ans = {k: v for k, v in answers.items() if k in QUESTIONS}
    topics = _topics(t, obs, ans)

    # ---- red-flag layer: runs first; any hit short-circuits to CRITICAL ----
    red = {label for phrase, label in CRITICAL_PHRASES.items() if phrase in t}
    if "unresponsive" in obs:
        red.add("unconscious or unresponsive")
    if "heavy_bleeding" in obs or ans.get("bleeding_heavy"):
        red.add("severe bleeding")
    if ans.get("breathing_difficulty") or ans.get("speak_sentences") is False:
        red.add("difficulty breathing")
    if ans.get("lost_consciousness") and (ans.get("confused") or ans.get("vomited") or ans.get("worsening_headache")):
        red.add("severe head injury symptoms")
    red_flags = sorted(red)

    # ---- observable factors behind the level (shown as "why") ----
    reasons: list[str] = []
    signals = 0

    def sig(cond: bool, why: str) -> None:
        nonlocal signals
        if cond:
            reasons.append(why)
            signals += 1

    sig(bool(ans.get("soaking_through")), "Blood is soaking through the dressing")
    sig(bool(ans.get("faint")), "Feeling faint or weak")
    sig("deformity" in obs, "An unusual shape or position of the limb is visible")
    sig(ans.get("can_bear_weight") is False, "Unable to put weight on it")
    sig(ans.get("can_move") is False or "cannot_move_part" in obs, "Difficulty moving the injured part")
    sig(bool(ans.get("heard_snap")), "A snap was heard or felt at the time")
    sig("foreign_object" in obs, "An object appears to be in the wound")
    sig(bool(ans.get("burn_large")), "The burn is large or in a sensitive area")
    sig(bool(ans.get("severe_pain")), "Pain reported as severe")
    sig("head" in topics and bool(ans.get("confused") or ans.get("vomited") or ans.get("worsening_headache") or ans.get("lost_consciousness")),
        "Head injury with confusion, vomiting, worsening headache or lost consciousness")
    mild = [OBSERVATIONS[o] for o in ("bleeding", "open_wound", "swelling", "bruising", "redness", "burn") if o in obs]

    if red_flags:
        level = "CRITICAL"
        reasons = [f"Warning sign: {r}" for r in red_flags] + reasons
    elif signals >= 2 or (signals == 1 and "deformity" in obs):
        level = "URGENT"
    elif signals == 1 or mild or topics:
        level = "MODERATE"
        if not reasons:
            reasons = [f"Visible: {m}" for m in mild[:3]] or ["An injury was reported and should be looked at"]
    else:
        level = "LOW"
        reasons = ["No emergency warning signs reported or visible so far"]

    # ---- observed vs inferred vs unknown: never a diagnosis ----
    observed = [f"Visible: {OBSERVATIONS[o]}" for o in sorted(obs)]
    inferred: list[str] = []
    if "deformity" in obs or ans.get("heard_snap"):
        inferred.append("This may indicate a significant limb injury. I can't tell from the camera whether a bone is broken.")
    if "swelling" in obs and "limb" in topics:
        inferred.append("Swelling after a fall may indicate an injury that needs checking.")
    if ans.get("soaking_through"):
        inferred.append("The bleeding may not be under control yet.")
    unknown = ["Whether anything is broken or damaged inside", "How serious this is without a professional assessment"]
    if not obs:
        unknown.insert(0, "Anything visible: no camera observations were used")

    # ---- targeted follow-ups: at most two, never during a critical alert ----
    asked: list[dict] = []
    if level != "CRITICAL":
        order: list[str] = []
        for tp in topics:
            order += [k for k, (_, topic) in QUESTIONS.items() if topic == tp]
        order.append("severe_pain")
        for k in order:
            if k not in ans and all(k != q["key"] for q in asked):
                asked.append({"key": k, "text": QUESTIONS[k][0]})
            if len(asked) == 2:
                break

    # ---- first-aid steps: short, shown one at a time, conservative ----
    if level == "CRITICAL":
        keys = ["emergency", "safe"]
        if "head" in topics or "possible spinal injury" in red_flags:
            keys.append("no_move_neck")
        if "bleeding" in topics or "severe bleeding" in red_flags:
            keys += ["pressure", "keep_pressure"]
        if {"difficulty breathing", "chest pain"} & red:
            keys.append("breath_sit")
        if "unconscious or unresponsive" in red:
            keys.append("recovery")
    else:
        keys = ["emergency"] if level == "URGENT" else []
        keys.append("safe")
        if "bleeding" in topics:
            keys += ["pressure", "keep_pressure"]
        if "limb" in topics:
            keys.append("still_limb")
            if "deformity" in obs or ans.get("can_bear_weight") is False or not ans:
                keys.append("no_weight")
            if "deformity" not in obs and not ans.get("heard_snap"):
                keys.append("ice_wrapped")
        if "burn" in topics:
            keys.append("cool")
        if "head" in topics:
            keys.append("head_rest")
        if "breathing" in topics:
            keys.append("breath_sit")
        if level != "LOW":
            keys.append("see_clinician")
    keys.append("monitor")
    steps, seen = [], set()
    for k in keys:
        if k not in seen:
            seen.add(k)
            icon, text_ = STEPS[k]
            steps.append({"key": k, "icon": icon, "text": text_})

    summary = {
        "LOW": "No obvious emergency signs so far.",
        "MODERATE": "This may need medical evaluation.",
        "URGENT": "This could require urgent medical attention.",
        "CRITICAL": "Possible life-threatening signs. Get emergency help now.",
    }[level]
    if mild and level != "CRITICAL":
        summary += f" I can see {', '.join(mild[:3])}."
    urgent = level in ("URGENT", "CRITICAL")
    return Triage(level, summary, reasons, red_flags, observed, inferred, unknown, asked, steps,
                  call_emergency=urgent, notify_circle=urgent, topics=topics)


_VISION_SYSTEM = (
    "You look at ONE photo for a first-aid assistant. Report ONLY clearly visible signs, using only these keys: "
    + ", ".join(OBSERVATIONS) + ". Never diagnose, never name a condition, never identify the person. "
    'If unsure, leave the key out. Reply with JSON only: {"observations": ["key"]}.'
)


def _parse_observations(raw: str) -> list[str]:
    m = re.search(r"\{.*\}", raw, re.S)
    got = json.loads(m.group(0)).get("observations", []) if m else []
    return [o for o in got if isinstance(o, str) and o in OBSERVATIONS]


def _vision_anthropic(s, image_b64: str, media_type: str) -> list[str]:
    import anthropic

    client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=12.0, max_retries=0)
    msg = client.messages.create(
        model=s.llm_model, max_tokens=150, system=_VISION_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
            {"type": "text", "text": "List the visible signs."}]}],
    )
    return _parse_observations("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))


def _ollama_models(base: str) -> list[str] | None:
    """Names of locally installed models, or None when Ollama is not running."""
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/api/tags", timeout=2) as r:
            return [m.get("name", "") for m in json.load(r).get("models", [])]
    except Exception:
        return None


def _vision_ollama(s, image_b64: str) -> list[str]:
    body = json.dumps({
        "model": s.vision_model, "stream": False, "format": "json", "options": {"temperature": 0},
        "messages": [{"role": "user", "content": _VISION_SYSTEM + " List the visible signs.", "images": [image_b64]}],
    }).encode()
    req = urllib.request.Request(s.ollama_url.rstrip("/") + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=s.vision_timeout_s) as r:
        return _parse_observations(json.load(r).get("message", {}).get("content", ""))


def vision_observe(image_b64: str, media_type: str = "image/jpeg") -> dict:
    """Optional single-frame analysis. Sent only on an explicit user action; never stored or logged.
    Uses Claude when NEXA_ANTHROPIC_API_KEY is set, otherwise a local Ollama vision model (nothing leaves the machine)."""
    s = get_settings()
    try:
        base64.b64decode(image_b64, validate=True)
        if s.anthropic_api_key:
            return {"available": True, "source": "claude", "observations": _vision_anthropic(s, image_b64, media_type)}
        models = _ollama_models(s.ollama_url)
        if models is None:
            return {"available": False, "reason": "not_configured", "observations": []}
        if not any(n == s.vision_model or n.split(":")[0] == s.vision_model.split(":")[0] for n in models):
            return {"available": False, "reason": "model_missing", "model": s.vision_model, "observations": []}
        return {"available": True, "source": "local", "observations": _vision_ollama(s, image_b64)}
    except Exception as e:  # never surface provider details; the manual checklist always works
        log.warning("vision analysis unavailable: %s", type(e).__name__)
        return {"available": False, "reason": "failed", "observations": []}
