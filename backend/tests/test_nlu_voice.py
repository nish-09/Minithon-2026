import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import get_settings
from app.services import nlu
from tests.conftest import km


# ---------------- deterministic NLU ----------------
@pytest.mark.parametrize("text,category,urgency", [
    ("I need someone to help me move a cupboard.", "household_assistance", "normal"),
    ("Nexa, I fell off my bike and my arm is bleeding.", "medical_assistance", "critical"),
    ("my tap is leaking, need a plumber asap", "repair", "urgent"),
    ("Looking for a maths tutor for my daughter", "tutoring", "normal"),
    ("can someone walk my dog tomorrow", "pet_care", "normal"),
    ("I can't breathe and I have chest pain", "medical_assistance", "critical"),
    ("please help me set up my wifi router", "tech_help", "normal"),
    ("I'm locked out of my flat, urgent", "other", "urgent"),
])
def test_rule_understanding(text, category, urgency):
    u = nlu.rule_understand(text)
    assert u.category == category and u.urgency == urgency


def test_extracts_skills_helpers_time_and_context():
    u = nlu.rule_understand("Nexa, I need two people to help me move a wardrobe tomorrow, I'm home alone")
    assert u.num_helpers == 2 and u.time_requirement == "tomorrow" and u.context.get("alone") is True
    assert u.skills_required == ["physical_assistance"] and u.location_required is True
    u = nlu.rule_understand("need help in 30 minutes, my kitchen socket is sparking")
    assert u.time_requirement == "within 30 minutes" and u.skills_required == ["electrical"]
    bike = nlu.rule_understand("Nexa, I fell off my bike and my arm is bleeding.")
    assert bike.skills_required == ["first_aid"] and "fell off my bike" in bike.title.lower() and "nexa" not in bike.description.lower()


def test_to_dict_matches_spec_shape():
    d = nlu.understand("Nexa, I fell off my bike and my arm is bleeding.").to_dict()
    assert {"category", "urgency", "description", "skills_required", "location_required"} <= set(d)
    assert d["category"] == "medical_assistance" and d["urgency"] == "critical" and d["skills_required"] == ["first_aid"]


# ---------------- LLM layer + failure fallbacks ----------------
def fake_anthropic(monkeypatch, *, text=None, raises=None):
    class Client:
        def __init__(self, **kw): pass
        class messages:
            @staticmethod
            def create(**kw):
                if raises:
                    raise raises
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", Client)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")


def test_llm_result_is_used_when_valid(monkeypatch):
    fake_anthropic(monkeypatch, text=json.dumps({"category": "household_assistance", "urgency": "normal", "title": "Move cupboard",
                                                 "description": "Needs help moving a cupboard", "skills_required": ["physical_assistance", "bogus"],
                                                 "time_requirement": None, "num_helpers": 2, "location_required": True, "confidence": 0.9}))
    u = nlu.understand("could somebody lend a hand with my cupboard")
    assert u.source == "llm" and u.num_helpers == 2 and u.skills_required == ["physical_assistance"]  # invalid skill dropped


def test_llm_outage_falls_back_to_rules(monkeypatch):
    fake_anthropic(monkeypatch, raises=httpx.ConnectError("network down"))
    u = nlu.understand("I need someone to help me move a cupboard")
    assert u.source == "rules" and u.category == "household_assistance"


@pytest.mark.parametrize("garbage", ["sorry I cannot help", "{not json", json.dumps({"category": "made_up", "urgency": "normal"}),
                                     json.dumps({"category": "repair", "urgency": "catastrophic"}), ""])
def test_llm_garbage_falls_back_to_rules(monkeypatch, garbage):
    fake_anthropic(monkeypatch, text=garbage)
    assert nlu.understand("I need someone to help me move a cupboard").source == "rules"


def test_llm_can_never_downgrade_a_critical_situation(monkeypatch):
    fake_anthropic(monkeypatch, text=json.dumps({"category": "other", "urgency": "normal", "title": "Hand hurt", "description": "hand",
                                                 "skills_required": [], "num_helpers": 1, "location_required": True, "confidence": 0.9}))
    u = nlu.understand("my hand is bleeding badly and I feel faint, I fell off my bike")
    assert u.urgency == "critical" and u.category == "medical_assistance" and "first_aid" in u.skills_required
    assert u.context.get("urgency_raised_by_safety_floor")


# ---------------- AI endpoints ----------------
def test_ai_understand_request_includes_circle_prompt(make_user, befriend):
    me = make_user("Nishit")
    mom, cousin, friend = make_user("Mom", (1, 0)), make_user("Cousin", (1.5, 0)), make_user("Pal", (0, 1.5))
    befriend(me, mom, "mother"); befriend(me, cousin, "cousin"); befriend(me, friend, "friend")
    lat, lng = km(0, 0)
    r = me.post("/api/ai/understand-request", {"text": "Nexa, I need someone to help me move a cupboard.", "lat": lat, "lng": lng}).json()
    assert r["understanding"]["category"] == "household_assistance"
    assert r["circle_prompt"] == "You have two relatives and one trusted friend nearby. Would you like me to ask them first?"
    assert r["suggested_routing"] == "circle_first" and r["trusted_circle"]["count"] == 3
    crit = me.post("/api/ai/understand-request", {"text": "I fell and my arm is bleeding", "lat": lat, "lng": lng}).json()
    assert crit["circle_prompt"] is None and crit["suggested_routing"] == "emergency" and "112" in crit["emergency_advice"]


def test_classify_urgency_endpoint(make_user):
    me = make_user("Nishit")
    r = me.post("/api/ai/classify-urgency", {"text": "I can't breathe"}).json()
    assert r["urgency"] == "critical" and "can't breathe" in r["red_flags"] and r["emergency_services_advised"] is True
    assert me.post("/api/ai/classify-urgency", {"text": "x"}).status_code == 422
    assert me.post("/api/ai/classify-urgency", {"text": "y" * 1001}).status_code == 422


def test_transcript_cleanup_strips_wake_word(make_user):
    me = make_user("Nishit")
    r = me.post("/api/voice/transcript", {"transcript": "Hey Nexa, I need help", "confidence": 0.3}).json()
    assert r == {"text": "I need help", "wake_word_detected": True, "low_confidence": True}


def test_server_side_transcription_not_faked(make_user, monkeypatch):
    me = make_user("Nishit")
    files = {"audio": ("a.webm", b"\x00\x01", "audio/webm")}
    r = me.client.post("/api/voice/transcribe", headers=me.h, files=files)
    assert r.status_code == 501 and "not configured" in r.json()["detail"]  # voice failure path: clear message, no fake text

    monkeypatch.setattr(get_settings(), "stt_url", "http://stt.invalid/v1/audio/transcriptions")
    r = me.client.post("/api/voice/transcribe", headers=me.h, files=files)
    assert r.status_code == 502 and "type your request" in r.json()["detail"]  # provider down -> graceful
    big = {"audio": ("a.webm", b"0" * (10 * 1024 * 1024 + 10), "audio/webm")}
    assert me.client.post("/api/voice/transcribe", headers=me.h, files=big).status_code == 413
    assert me.client.post("/api/voice/transcribe", headers=me.h, files={"audio": ("a.webm", b"", "audio/webm")}).status_code == 422


# ---------------- voice assistant ----------------
def vc(p, text, ctx=None, share=False):
    lat, lng = km(0, 0)
    r = p.post("/api/voice/command", {"text": text, "lat": lat, "lng": lng, "share_location": share, "context": ctx or {}})
    assert r.status_code == 200, r.text
    return r.json()


def test_voice_create_asks_circle_then_creates(make_user, befriend):
    me = make_user("Nishit")
    mom, uncle, friend = make_user("Mom", (1, 0)), make_user("Uncle", (1.4, 0)), make_user("Pal", (0, 1.6))
    befriend(me, mom, "mother"); befriend(me, uncle, "uncle"); befriend(me, friend, "friend")
    t1 = vc(me, "Nexa, I need someone to help me move a cupboard.")
    assert t1["speech"] == "I can help with that. You have two relatives and one trusted friend nearby. Would you like me to ask them first?"
    assert t1["context"]["stage"] == "awaiting_circle_choice" and "choose_routing" in t1["actions"]
    unclear = vc(me, "hmm maybe", t1["context"])
    assert "should I ask your trusted circle first" in unclear["speech"] and unclear["context"] == t1["context"]  # asks again, keeps state
    t2 = vc(me, "Yes.", t1["context"])
    assert "trusted circle" in t2["speech"] and t2["data"]["status"] == "TRUSTED_CIRCLE" and "request_created" in t2["actions"]
    assert len(mom.get("/api/requests?scope=invited").json()) == 1


def test_voice_decline_circle_goes_to_community_and_custom_opens_picker(make_user, befriend):
    me, mom, rahul = make_user("Nishit"), make_user("Mom", (1, 0)), make_user("Rahul", (0.7, 0))
    befriend(me, mom, "mother")
    t1 = vc(me, "I need someone to help me move a cupboard")
    custom = vc(me, "let me choose", t1["context"])
    assert "open_custom" in custom["actions"]
    t2 = vc(me, "No, find community help directly", t1["context"])
    assert t2["data"]["status"] == "HELPERS_NOTIFIED" and len(rahul.get("/api/requests?scope=invited").json()) == 1


def test_voice_without_circle_creates_immediately(make_user):
    me, h = make_user("Nishit"), make_user("Rahul", (0.7, 0))
    t = vc(me, "Nexa, I need someone to help me move this table")
    assert t["context"] == {} and t["data"]["status"] == "HELPERS_NOTIFIED"


def test_voice_status_update_cancel_and_arrival(make_user):
    me, h = make_user("Nishit"), make_user("Rahul Shah", (0.7, 0))
    t = vc(me, "I need someone to help me move a cupboard")
    rid = t["data"]["request_id"]
    assert "waiting for someone to accept" in vc(me, "what's the status?")["speech"]
    upd = vc(me, "Actually make it three people")
    assert "three helpers" in upd["speech"] and me.get(f"/api/requests/{rid}").json()["num_helpers"] == 3
    h.post(f"/api/matching/{rid}/accept")
    st = vc(me, "where is my helper")
    assert "Rahul accepted" in st["speech"] and "minutes away" in st["speech"]
    arr = vc(me, "Help has arrived")
    assert "Rahul is with you" in arr["speech"] and me.get(f"/api/requests/{rid}").json()["status"] == "IN_PROGRESS"
    c1 = vc(me, "cancel my request")
    assert c1["context"]["stage"] == "awaiting_cancel_confirm"
    c2 = vc(me, "yes", c1["context"])
    assert "cancelled" in c2["speech"]
    assert me.get(f"/api/requests/{rid}").json()["status"] == "CANCELLED"


def test_voice_cancel_confirmation_can_be_declined(make_user):
    me, h = make_user("Nishit"), make_user("Rahul", (0.7, 0))
    rid = vc(me, "I need someone to help me move a cupboard")["data"]["request_id"]
    c1 = vc(me, "never mind")
    c2 = vc(me, "no keep it", c1["context"])
    assert "keep your request open" in c2["speech"] and me.get(f"/api/requests/{rid}").json()["status"] != "CANCELLED"


def test_voice_emergency_skips_questions_and_starts_care(make_user):
    me = make_user("Nishit")
    mom = make_user("Mom", (1, 0))
    out = vc(me, "Nexa, I need help. I fell off my bike and my arm is bleeding.", share=True)
    assert "care" in out["actions"] and "show_emergency_banner" in out["actions"]
    assert out["data"]["incident"]["status"] == "ACTIVE" and out["data"]["incident"]["current_protocol"] == "BLEEDING_ASSISTANCE"
    # follow-up turns are handled by NEXA CARE without any context from the client
    nxt = vc(me, "okay I completed that")
    assert nxt["data"]["incident"]["completed_steps"] == [1] and "Let's continue" in nxt["speech"]
    end = vc(me, "help has arrived")
    assert end["data"]["incident"]["status"] == "RESOLVED" and "end NEXA CARE" in end["speech"]


def test_voice_needs_location_gracefully(client):
    r = client.post("/api/auth/register", json={"name": "No Loc", "email": "vl@nexa-test.app", "password": "password123"})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    out = client.post("/api/voice/command", headers=h, json={"text": "I need help moving a cupboard"}).json()
    assert "need_location" in out["actions"]
    crit = client.post("/api/voice/command", headers=h, json={"text": "I fell and I'm bleeding"}).json()
    assert "need_location" in crit["actions"] and "emergency number" in crit["speech"]


def test_voice_input_validation(make_user):
    me = make_user("Nishit")
    assert me.post("/api/voice/command", {"text": ""}).status_code == 422
    assert me.post("/api/voice/command", {"text": "hi", "context": {"stage": "hacked"}}).status_code == 422
    assert me.post("/api/voice/command", {"text": "hi", "lat": 999}).status_code == 422
