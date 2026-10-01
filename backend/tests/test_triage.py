from app.services import triage
from tests.conftest import km

BANNED = ("fracture", "fractured", "broken bone", "you have", "diagnos")


def test_red_flag_text_is_critical_and_leads_with_emergency():
    r = triage.assess("I'm having trouble breathing and my chest hurts", [], {})
    assert r.level == "CRITICAL" and r.call_emergency and r.notify_circle
    assert r.steps[0]["key"] == "emergency" and r.questions == []
    assert any("breathing" in x or "chest" in x for x in r.red_flags)


def test_visual_swelling_and_deformity_is_urgent_never_a_diagnosis():
    r = triage.assess("I fell and my leg hurts", ["swelling", "deformity"], {"can_bear_weight": False})
    assert r.level == "URGENT"
    text = " ".join(r.reasons + r.inferred + [r.summary] + [s["text"] for s in r.steps]).lower()
    assert not any(b in text for b in BANNED)
    assert any("can't tell from the camera" in i for i in r.inferred)
    assert r.observed and "Whether anything is broken or damaged inside" in r.unknown
    assert any(s["key"] == "no_weight" for s in r.steps)


def test_minor_report_is_moderate_or_low_and_asks_at_most_two_questions():
    r = triage.assess("I got a small cut on my finger", ["bleeding"], {})
    assert r.level == "MODERATE" and not r.call_emergency and len(r.questions) <= 2
    assert triage.assess("", [], {}).level == "LOW"


def test_answers_escalate_and_head_injury_symptoms_are_critical():
    assert triage.assess("I hit my head", [], {"lost_consciousness": True, "vomited": True}).level == "CRITICAL"
    assert triage.assess("my arm is bleeding", ["bleeding"], {"soaking_through": True, "faint": True}).level == "URGENT"


def test_unknown_observation_keys_are_ignored_and_trigger_detection():
    assert triage.assess("x", ["cancer"], {}).observed == []
    assert triage.needs_visual_assessment("I burned my hand") and not triage.needs_visual_assessment("find me a plumber")


def test_api_requires_consent_logs_and_escalates_critical(make_user):
    me = make_user("Tri")
    lat, lng = km(0, 0)
    inc = me.post("/api/incidents", {"text": "I fell and my ankle is swollen", "lat": lat, "lng": lng, "share_location": True}).json()["incident"]
    r = me.post("/api/triage/assess", {"text": "I fell, my ankle is swollen", "observations": ["swelling"], "answers": {}, "incident_id": inc["id"]})
    assert r.status_code == 200 and r.json()["level"] in ("MODERATE", "URGENT") and r.json()["suggest_visual"] is True
    assert me.post("/api/triage/vision", {"image_b64": "A" * 200, "consent": False}).status_code == 403
    ok = me.post("/api/triage/vision", {"image_b64": "A" * 200, "consent": True})
    assert ok.status_code == 200 and ok.json()["observations"] == []  # no LLM key in tests: manual checklist fallback
    assert me.post("/api/triage/assess", {"text": "x", "incident_id": 99999}).status_code == 404


def test_local_vision_model_is_used_without_a_claude_key_and_output_is_filtered(monkeypatch):
    monkeypatch.setattr(triage, "_ollama_models", lambda base: ["qwen2.5vl:3b"])
    monkeypatch.setattr(triage, "_vision_ollama", lambda s, b64: triage._parse_observations('noise {"observations": ["swelling", "cancer", 7]} more'))
    r = triage.vision_observe("QUJD" * 20)
    assert r == {"available": True, "source": "local", "observations": ["swelling"]}


def test_local_vision_reports_missing_runtime_and_missing_model(monkeypatch):
    monkeypatch.setattr(triage, "_ollama_models", lambda base: None)
    assert triage.vision_observe("QUJD" * 20)["reason"] == "not_configured"
    monkeypatch.setattr(triage, "_ollama_models", lambda base: ["llama3.2:latest"])
    r = triage.vision_observe("QUJD" * 20)
    assert r["reason"] == "model_missing" and r["model"] == "qwen2.5vl:3b"
