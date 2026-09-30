"""Natural-language request understanding.

Two layers:
  1. `rule_understand` - deterministic keyword/pattern NLU. Always available; used as the fallback.
  2. `llm_understand`  - optional Claude call that returns strict JSON validated against our enums.

Safety floor: whichever layer runs, `apply_safety_floor` raises urgency to "critical" when red-flag
phrases are present. An LLM can raise urgency, but never lower it below the deterministic floor.
"""
import json
import logging
import re
from dataclasses import asdict, dataclass, field

from ..config import get_settings
from ..protocols_data import RED_FLAG_PHRASES
from ..taxonomy import CATEGORIES, SKILLS, URGENCIES

log = logging.getLogger("nexa.nlu")

CATEGORY_SLUGS = [c[0] for c in CATEGORIES]
SKILL_SLUGS = {s[0] for s in SKILLS}
DEFAULT_SKILLS = {c[0]: c[2] for c in CATEGORIES}

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "medical_assistance": ["bleed", "blood", "injur", "hurt", "fell", "fall", "fainted", "dizzy", "pain", "burn", "broke",
                           "fracture", "sprain", "first aid", "ambulance", "wound", "cut my", "unconscious", "allerg",
                           "chest", "breath", "sick", "medical", "seizure", "choking"],
    "household_assistance": ["move", "moving", "lift", "carry", "cupboard", "furniture", "table", "sofa", "couch", "wardrobe",
                             "fridge", "shift", "heavy", "box", "boxes", "rearrange", "mattress", "cabinet"],
    "repair": ["fix", "repair", "leak", "leaking", "plumb", "tap", "pipe", "electric", "wiring", "switch", "socket",
               "bulb", "fuse", "carpent", "door", "hinge", "broken fan", "ac not"],
    "tutoring": ["tutor", "teach", "homework", "exam", "lesson", "maths", "math", "physics", "chemistry", "study", "learn"],
    "pet_care": ["dog", "cat", "pet", "puppy", "kitten", "walk my", "vet", "feed my"],
    "errands": ["groceries", "grocery", "pick up", "pickup", "deliver", "medicine from", "pharmacy run", "errand", "buy", "parcel", "post office"],
    "transport": ["ride", "lift to", "drop me", "drive me", "cab", "airport", "hospital ride", "drop off"],
    "tech_help": ["wifi", "wi-fi", "laptop", "computer", "phone setup", "printer", "password", "app", "tv setup", "router"],
    "elder_care": ["elderly", "grandmother", "grandfather", "grandma", "grandpa", "companion", "old man", "old woman", "check on my mother", "check on my father"],
}

URGENT_WORDS = ["urgent", "urgently", "asap", "right now", "immediately", "emergency", "hurry", "quickly", "as soon as possible",
                "locked out", "flooding", "flooded", "gas leak", "stuck", "trapped", "no power", "right away"]
CRITICAL_INJURY = ["bleed", "blood", "unconscious", "fainted", "collapsed", "burn", "broke my", "broken bone", "fracture",
                   "can't breathe", "cannot breathe", "chest pain", "allergic reaction", "seizure", "choking", "heart attack", "stroke", "fell off"]

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "a couple of": 2, "couple of": 2, "a few": 2, "both": 2}


WAKE_RE = re.compile(r"^\s*(?:hey\s+|ok(?:ay)?\s+)?nexa\b[\s,:.!-]*", re.I)


def strip_wake_word(text: str) -> tuple[str, bool]:
    m = WAKE_RE.match(text)
    if m is None:
        return text.strip(), False
    return (text[m.end():].strip() or text.strip(), True)


@dataclass
class Understanding:
    intent: str = "create_request"
    category: str = "other"
    urgency: str = "normal"
    description: str = ""
    title: str = ""
    skills_required: list[str] = field(default_factory=list)
    time_requirement: str | None = None
    num_helpers: int = 1
    location_required: bool = True
    context: dict = field(default_factory=dict)
    confidence: float = 0.5
    source: str = "rules"

    def to_dict(self) -> dict:
        return asdict(self)


def detect_red_flags(text: str) -> list[str]:
    t = text.lower()
    return [p for p in RED_FLAG_PHRASES if p in t]


def _score_category(t: str) -> tuple[str, int]:
    best, best_n = "other", 0
    for cat, kws in CATEGORY_KEYWORDS.items():
        n = sum(1 for k in kws if k in t)
        if n > best_n:
            best, best_n = cat, n
    return best, best_n


def _num_helpers(t: str) -> int:
    m = re.search(r"\b(\d{1,2})\s+(?:people|persons|helpers|volunteers|hands)\b", t)
    if m:
        return max(1, min(20, int(m.group(1))))
    for w, n in NUMBER_WORDS.items():
        if re.search(rf"\b{re.escape(w)}\s+(?:more\s+)?(?:people|persons|helpers|hands|volunteers)\b", t) or (
            w in ("a couple of", "couple of", "a few") and w in t and re.search(r"people|helpers|hands", t)
        ):
            return n
    if any(k in t for k in ("wardrobe", "fridge", "piano", "sofa set", "washing machine")):
        return 2
    return 1


def _time_requirement(t: str) -> str | None:
    m = re.search(r"\b(?:in|within)\s+(\d{1,3})\s*(minutes?|mins?|hours?|hrs?)\b", t)
    if m:
        return f"within {m.group(1)} {m.group(2)}"
    m = re.search(r"\bfor\s+(?:about\s+)?(\d{1,2}|an|one|two|three)\s*(hours?|hrs?|minutes?|mins?)\b", t)
    if m:
        return f"for {m.group(1)} {m.group(2)}"
    for k in ("right now", "now", "immediately", "asap", "tonight", "today", "tomorrow", "this evening", "this weekend", "this morning"):
        if re.search(rf"\b{k}\b", t):
            return k
    return None


def _title(category: str, text: str) -> str:
    base = re.sub(r"^(nexa[,:]?\s*)", "", text.strip(), flags=re.I)
    base = re.sub(r"^(i need|i want|can (?:you|someone)|could (?:you|someone)|please)\s+", "", base, flags=re.I)
    base = base.strip(" .!?")
    base = base[:1].upper() + base[1:] if base else "Help needed"
    return base[:90]


def rule_understand(text: str) -> Understanding:
    text, _ = strip_wake_word(text)
    t = " ".join(text.lower().split())
    category, n = _score_category(t)
    flags = detect_red_flags(t)
    injury = any(k in t for k in CRITICAL_INJURY)
    urgent = any(k in t for k in URGENT_WORDS)

    if category == "medical_assistance" and (injury or flags):
        urgency = "critical"
    elif flags or (injury and category != "household_assistance"):
        urgency, category = "critical", "medical_assistance"
    elif urgent:
        urgency = "urgent"
    else:
        urgency = "normal"

    skills = list(DEFAULT_SKILLS.get(category, []))
    if category == "repair":  # narrow repair to the trade actually mentioned
        narrowed = [s for s, kws in (("plumbing", ("leak", "plumb", "tap", "pipe")), ("electrical", ("electric", "wiring", "switch", "socket", "bulb", "fuse")),
                                     ("carpentry", ("carpent", "door", "hinge", "cabinet"))) if any(k in t for k in kws)]
        skills = narrowed or skills
    if "cpr" in t and "cpr" not in skills:
        skills.append("cpr")

    conf = 0.45 + min(0.4, n * 0.12) + (0.1 if urgency != "normal" else 0)
    ctx: dict = {}
    if flags:
        ctx["red_flags"] = flags
    if "alone" in t or "home alone" in t:
        ctx["alone"] = True
    return Understanding(
        intent="create_request", category=category, urgency=urgency, description=text.strip()[:500],
        title=_title(category, text), skills_required=skills, time_requirement=_time_requirement(t),
        num_helpers=_num_helpers(t), location_required=True, context=ctx, confidence=round(min(conf, 0.95), 2), source="rules",
    )


def apply_safety_floor(u: Understanding, text: str) -> Understanding:
    floor = rule_understand(text)
    if URGENCIES.index(floor.urgency) > URGENCIES.index(u.urgency) and (
        floor.urgency == "critical" or detect_red_flags(text)
    ):
        u.urgency = floor.urgency
        u.context["urgency_raised_by_safety_floor"] = True
        if floor.category == "medical_assistance":
            u.category = "medical_assistance"
            if "first_aid" not in u.skills_required:
                u.skills_required.append("first_aid")
    return u


_LLM_SYSTEM = """You convert a neighbour's help request into JSON for the NEXA assistance platform.
Return ONLY a JSON object with keys:
category (one of %s), urgency (normal|urgent|critical), title (<=90 chars), description (short, factual),
skills_required (subset of %s), time_requirement (string or null), num_helpers (integer 1-20),
location_required (boolean), confidence (0-1).
Rules: urgency "critical" for injury, bleeding, breathing problems, chest pain, unconsciousness, fire or any risk to life.
Never add medical advice. Do not invent facts that were not stated.""" % (CATEGORY_SLUGS, sorted(SKILL_SLUGS))


def llm_understand(text: str) -> Understanding | None:
    s = get_settings()
    if not s.anthropic_api_key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=8.0, max_retries=1)
        msg = client.messages.create(
            model=s.llm_model, max_tokens=400, system=_LLM_SYSTEM,
            messages=[{"role": "user", "content": text[:1000]}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
        return _validate_llm(data, text)
    except Exception as e:  # network, auth, parse: always fall back
        log.warning("LLM understanding failed, using rules: %s", e)
        return None


def _validate_llm(data: dict, text: str) -> Understanding | None:
    cat = data.get("category")
    urg = data.get("urgency")
    if cat not in CATEGORY_SLUGS or urg not in URGENCIES:
        return None
    skills = [x for x in (data.get("skills_required") or []) if x in SKILL_SLUGS]
    try:
        n = max(1, min(20, int(data.get("num_helpers", 1))))
    except (TypeError, ValueError):
        n = 1
    tr = data.get("time_requirement")
    return Understanding(
        category=cat, urgency=urg, title=str(data.get("title") or text)[:90],
        description=str(data.get("description") or text)[:500],
        skills_required=skills or list(DEFAULT_SKILLS.get(cat, [])),
        time_requirement=str(tr)[:64] if tr else None, num_helpers=n,
        location_required=bool(data.get("location_required", True)),
        confidence=float(min(1, max(0, data.get("confidence", 0.7)))), source="llm",
    )


def understand(text: str) -> Understanding:
    text, _ = strip_wake_word(text or "")
    u = llm_understand(text) or rule_understand(text)
    return apply_safety_floor(u, text)
