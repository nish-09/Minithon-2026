from app.protocols_data import PROTOCOLS
from tests.conftest import SessionLocal, km

BIKE = "Nexa, I fell off my bike and my arm is bleeding."
ALL_STEP_TEXT = {ins for _, _, _, _, steps in PROTOCOLS for ins, fb, _ in steps} | {fb for _, _, _, _, steps in PROTOCOLS for ins, fb, _ in steps if fb}


def start(p, text=BIKE, share=True):
    lat, lng = km(0, 0)
    r = p.post("/api/incidents", {"text": text, "lat": lat, "lng": lng, "share_location": share})
    assert r.status_code == 201, r.text
    return r.json()


def say(p, iid, text):
    r = p.post(f"/api/incidents/{iid}/say", {"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_start_incident_matches_spec_state_and_selects_verified_protocol(make_user):
    me = make_user("Nishit")
    out = start(me)
    inc = out["incident"]
    assert inc["incident_id"].startswith("INC-") and inc["status"] == "ACTIVE" and inc["urgency"] == "CRITICAL"
    assert inc["situation"] == "bike_fall" and inc["current_protocol"] == "BLEEDING_ASSISTANCE"
    assert inc["location_shared"] is True and inc["user_responsive"] is True
    assert inc["current_step"] == 1 and inc["completed_steps"] == []
    assert inc["emergency_services_advised"] is True and inc["emergency_number"] == "112"
    assert {"assigned_helper", "helper_eta_minutes", "protocol_version", "total_steps"} <= set(inc)
    assert "call your local emergency number" in inc["current_instruction"].lower()
    assert "does not replace emergency services" in out["speech"]
    assert "show_emergency_banner" in out["actions"]


def test_all_spoken_guidance_comes_only_from_approved_protocols(make_user):
    me = make_user("Nishit")
    out = start(me)
    iid = out["incident"]["id"]
    instr = out["incident"]["current_instruction"]
    assert instr in ALL_STEP_TEXT
    for phrase in ("done", "done", "done"):
        r = say(me, iid, phrase)
        cur = r["incident"]["current_instruction"]
        if cur:
            assert cur in ALL_STEP_TEXT  # never improvised
            assert cur in r["speech"]


def test_step_completion_conversation(make_user):
    me = make_user("Nishit")
    iid = start(me)["incident"]["id"]
    r = say(me, iid, "Okay, I completed that.")
    assert r["incident"]["completed_steps"] == [1] and r["incident"]["current_step"] == 2
    assert r["speech"].startswith("Good. Let's continue with the next step.")
    assert r["incident"]["current_instruction"] in r["speech"]
    r = me.post(f"/api/incidents/{iid}/step-complete", {"step": 2}).json()
    assert r["incident"]["completed_steps"] == [1, 2] and r["incident"]["current_step"] == 3
    assert me.post(f"/api/incidents/{iid}/step-complete", {"step": 1}).status_code == 409  # not the current step


def test_user_cannot_perform_step_gets_fallback_and_guidance_adjusts(make_user):
    me = make_user("Nishit")
    iid = start(me)["incident"]["id"]
    say(me, iid, "done")
    r = say(me, iid, "I can't do that, I don't have a cloth")
    assert r["speech"].startswith("Okay. I'll adjust the guidance.")
    assert "weight on the cloth" in r["speech"] or "keep" in r["speech"].lower()
    inc = r["incident"]
    assert inc["skipped_steps"] == [2] and inc["completed_steps"] == [1] and inc["current_step"] == 3
    # step-complete endpoint with unable=True behaves the same
    r2 = me.post(f"/api/incidents/{iid}/step-complete", {"unable": True}).json()
    assert r2["incident"]["skipped_steps"] == [2, 3]


def test_critical_step_skipped_repeats_emergency_advice(make_user):
    me = make_user("Nishit")
    iid = start(me)["incident"]["id"]
    r = say(me, iid, "I can't")
    assert "emergency number" in r["speech"].lower() or "112" in r["speech"]
    assert "show_emergency_banner" in r["actions"]


def test_situation_changes_dizzy_switches_to_verified_protocol_and_escalates(make_user):
    me = make_user("Nishit")
    iid = start(me)["incident"]["id"]
    say(me, iid, "done")
    r = say(me, iid, "I'm feeling dizzy now")
    inc = r["incident"]
    assert inc["current_protocol"] == "DIZZY_FAINTNESS" and inc["current_step"] == 1 and inc["completed_steps"] == []
    assert inc["escalation_level"] == 1
    assert "sit or lie down" in r["speech"].lower()
    assert "Keep holding pressure on the wound" in r["speech"]  # bleeding care is not forgotten
    log = me.get(f"/api/incidents/{iid}/log").json()
    sw = [x for x in log if x["kind"] == "state_change" and "protocol switched" in x["content"]]
    assert sw and "BLEEDING_ASSISTANCE -> DIZZY_FAINTNESS" in sw[0]["content"]
    # second deterioration raises the emergency advice
    r = say(me, iid, "I'm getting worse")
    assert r["incident"]["escalation_level"] == 2 and "call 112" in r["speech"].lower()


def test_red_flag_phrases_escalate_without_inventing_advice(make_user):
    me = make_user("Nishit")
    iid = start(me)["incident"]["id"]
    r = say(me, iid, "I think I'm going to pass out and I can't breathe properly")
    assert "call 112" in r["speech"].lower()
    assert r["incident"]["emergency_services_advised"] is True
    assert all(s in ALL_STEP_TEXT or len(s) < 200 for s in [r["incident"]["current_instruction"] or ""])


def test_unknown_utterance_does_not_invent_medical_advice(make_user):
    me = make_user("Nishit")
    iid = start(me)["incident"]["id"]
    r = say(me, iid, "should I take some painkillers and a nap")
    assert "approved first-aid guidance" in r["speech"]
    assert "painkiller" not in r["speech"].lower().replace("should i take some painkillers", "")
    assert r["incident"]["current_step"] == 1  # state unchanged


def test_repeat_and_status_questions(make_user):
    me = make_user("Nishit")
    iid = start(me)["incident"]["id"]
    r = say(me, iid, "sorry, can you repeat that?")
    assert r["incident"]["current_instruction"] in r["speech"]
    r = say(me, iid, "how far is the helper? when will someone come")
    assert "still asking helpers" in r["speech"] or "minutes" in r["speech"]


def test_escalate_endpoint_and_user_reported_emergency_call(make_user):
    me = make_user("Nishit")
    near = make_user("Near Helper", (0.3, 0), skills=["first_aid"])
    far = make_user("Farther", (12, 0), skills=["first_aid"])  # outside the initial 10 km radius
    iid = start(me)["incident"]["id"]
    assert far.get("/api/requests?scope=invited").json() == []
    r = me.post(f"/api/incidents/{iid}/escalate", {"emergency_contacted": True, "note": "called 112"}).json()
    assert r["incident"]["emergency_services_contacted"] is True and r["incident"]["escalation_level"] == 1
    assert len(far.get("/api/requests?scope=invited").json()) == 1  # search widened
    say(me, iid, "I called the ambulance, they're coming")
    assert any(x["kind"] == "escalated" for x in me.get(f"/api/incidents/{iid}/log").json())


def test_helper_assignment_updates_incident_state_live(make_user):
    me = make_user("Nishit")
    aarav = make_user("Aarav Mehta", (0, 0.5), skills=["first_aid"], certs=["first_aid_cert"], verified=True)
    out = start(me)
    iid, rid = out["incident"]["id"], out["request_id"]
    assert out["incident"]["assigned_helper"] is None
    assert aarav.post(f"/api/matching/{rid}/accept").status_code == 200
    inc = me.get(f"/api/incidents/{iid}").json()
    assert inc["assigned_helper"] == f"USR-{aarav.id}" and 0 < inc["helper_eta_minutes"] < 5
    r = say(me, iid, "where is the helper")
    assert "Aarav" in r["speech"] and "minutes away" in r["speech"]
    # assigned helper can follow state but not see the person's guidance/audit
    h = aarav.get(f"/api/incidents/{iid}")
    assert h.status_code == 200 and "current_instruction" not in h.json()
    assert aarav.get(f"/api/incidents/{iid}/log").status_code == 403


def test_help_has_arrived_closes_care(make_user):
    me = make_user("Nishit")
    aarav = make_user("Aarav Mehta", (0, 0.5), skills=["first_aid"])
    out = start(me)
    iid, rid = out["incident"]["id"], out["request_id"]
    aarav.post(f"/api/matching/{rid}/accept")
    r = say(me, iid, "Has help arrived?")  # question, not a claim
    assert r["incident"]["status"] == "ACTIVE"
    r = say(me, iid, "Help hasn't arrived yet")
    assert r["incident"]["status"] == "ACTIVE"
    r = say(me, iid, "Help has arrived.")
    assert r["incident"]["status"] == "RESOLVED" and r["incident"]["care_active"] is False
    assert "end NEXA CARE" in r["speech"] and "closed" in r["actions"]
    assert me.get(f"/api/requests/{rid}").json()["status"] == "IN_PROGRESS"  # helper marked as arrived
    after = say(me, iid, "done")
    assert "ended" in after["speech"]
    assert me.post(f"/api/incidents/{iid}/step-complete", {}).status_code == 409  # closed incidents are read-only
    closed = [x for x in me.get(f"/api/incidents/{iid}/log").json() if x["kind"] == "closed"]
    assert closed and closed[0]["meta"]["resolution"] == "RESOLVED"


def test_user_can_stop_care_and_linked_request_is_cancelled(make_user):
    me, h = make_user("Nishit"), make_user("Helper", (0.3, 0), skills=["first_aid"])
    out = start(me)
    iid, rid = out["incident"]["id"], out["request_id"]
    r = me.post(f"/api/incidents/{iid}/close", {"resolution": "CANCELLED", "reason": "false alarm"}).json()
    assert r["incident"]["status"] == "CANCELLED" and "stopped NEXA CARE" in r["speech"]
    assert me.get(f"/api/requests/{rid}").json()["status"] == "CANCELLED"
    assert h.get("/api/requests?scope=invited").json() == []
    assert me.get("/api/incidents/active").json()["incident"] is None


def test_protocol_selection_for_different_situations(make_user):
    me = make_user("Nishit")
    cases = [
        ("I burned my hand with boiling oil", "BURN_CARE"),
        ("I think I broke my ankle, I twisted it badly", "SUSPECTED_FRACTURE"),
        ("I have chest pain and tight chest", "CHEST_PAIN_ALERT"),
        ("I'm having an allergic reaction, my throat is closing", "SEVERE_ALLERGIC_REACTION"),
        ("I feel dizzy and might faint", "DIZZY_FAINTNESS"),
        ("something terrible just happened, please help", "GENERAL_DISTRESS"),
    ]
    for text, expected in cases:
        inc = start(me, text)["incident"]
        assert inc["current_protocol"] == expected, text
        me.post(f"/api/incidents/{inc['id']}/close", {"resolution": "CANCELLED"})


def test_chest_pain_protocol_leads_with_emergency_call_and_no_medication(make_user):
    me = make_user("Nishit")
    inc = start(me, "I have chest pain")["incident"]
    assert "call your local emergency number now" in inc["current_instruction"].lower()
    texts = " ".join(s for _, _, _, _, steps in PROTOCOLS for ins, fb, _ in steps for s in (ins, fb or ""))
    for banned in ("mg", "milligram", "tablet", "aspirin", "ibuprofen", "paracetamol", "tourniquet"):
        assert banned not in texts.lower(), banned  # no dosing/medication/invasive instructions in seed protocols


def test_location_consent_respected(make_user):
    me = make_user("Nishit")
    h = make_user("Helper", (0.3, 0), skills=["first_aid"])
    inc = start(me, share=False)["incident"]
    assert inc["location_shared"] is False
    rid = inc["request_id"]
    h.post(f"/api/matching/{rid}/accept")
    assert h.get(f"/api/requests/{rid}").json()["location_approximate"] is True  # no consent => never exact
    from app.models import Incident
    with SessionLocal() as db:
        i = db.get(Incident, inc["id"])
        assert i.lat is None and i.lng is None


def test_incident_requires_location(client):
    r = client.post("/api/auth/register", json={"name": "No Loc", "email": "nl2@nexa-test.app", "password": "password123"})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.post("/api/incidents", headers=h, json={"text": BIKE}).status_code == 422


def test_incident_access_control(make_user):
    me, stranger, admin = make_user("Nishit"), make_user("Stranger", (30, 0)), make_user("Admin", role="admin", available=False)
    iid = start(me)["incident"]["id"]
    assert stranger.get(f"/api/incidents/{iid}").status_code == 404
    assert stranger.post(f"/api/incidents/{iid}/say", {"text": "done"}).status_code == 404
    assert stranger.post(f"/api/incidents/{iid}/close", {}).status_code == 404
    assert stranger.get(f"/api/incidents/{iid}/log").status_code == 404
    assert admin.get(f"/api/incidents/{iid}/log").status_code == 200
    assert admin.get("/api/admin/incidents?active_only=true").json()[0]["id"] == iid
    assert admin.post(f"/api/incidents/{iid}/say", {"text": "done"}).status_code == 403  # admins observe, they do not speak for the user


def test_audit_log_records_every_turn(make_user):
    me = make_user("Nishit")
    iid = start(me)["incident"]["id"]
    say(me, iid, "done"); say(me, iid, "I can't"); say(me, iid, "I feel dizzy")
    log = me.get(f"/api/incidents/{iid}/log").json()
    kinds = [x["kind"] for x in log]
    assert kinds.count("user_said") == 3 and kinds.count("nexa_said") >= 4
    assert {"protocol_selected", "step_presented", "step_completed", "step_skipped"} <= set(kinds)
    assert all(x["actor"] in ("user", "nexa", "system", "admin") and x["at"] for x in log)


def test_critical_incident_alerts_admin(make_user):
    admin, me = make_user("Admin", role="admin", available=False), make_user("Nishit")
    out = start(me)
    n = [x for x in admin.get("/api/notifications").json()["items"] if x["kind"] == "critical_incident"]
    assert n and out["incident"]["incident_id"] in n[0]["title"]
    assert admin.get("/api/admin/dashboard").json()["critical_incidents"] == 1


def test_admin_protocol_versioning(make_user):
    admin, me = make_user("Admin", role="admin", available=False), make_user("Nishit")
    old = start(me)["incident"]
    new_proto = {
        "slug": "BLEEDING_ASSISTANCE", "title": "Bleeding control v2", "situation_keywords": ["bleed", "bleeding", "blood"],
        "source": "clinical review 2026", "steps": [{"instruction": "Call the emergency number, then press firmly on the wound.", "fallback_instruction": "Keep still.", "is_critical": True}],
    }
    r = admin.post("/api/admin/protocols", new_proto)
    assert r.status_code == 201 and r.json()["version"] == 2
    me.post(f"/api/incidents/{old['id']}/close", {"resolution": "CANCELLED"})
    fresh = start(me)["incident"]
    assert fresh["protocol_version"] == 2 and fresh["total_steps"] == 1
    assert me.get(f"/api/incidents/{old['id']}").json()["protocol_version"] == 1  # old incident keeps the version it used
    # admin can roll back by deactivating v2
    assert admin.post(f"/api/admin/protocols/{r.json()['id']}/active", {"is_active": False}).status_code == 200
    me.post(f"/api/incidents/{fresh['id']}/close", {"resolution": "CANCELLED"})
    assert start(me)["incident"]["protocol_version"] == 1
    # non-admins cannot manage protocols and inputs are validated
    assert me.post("/api/admin/protocols", new_proto).status_code == 403
    assert admin.post("/api/admin/protocols", {**new_proto, "steps": []}).status_code == 422
    assert admin.post("/api/admin/protocols", {**new_proto, "slug": "bad slug"}).status_code == 422


def test_finishing_all_steps(make_user):
    me = make_user("Nishit")
    inc = start(me)["incident"]
    for _ in range(inc["total_steps"]):
        r = say(me, inc["id"], "done")
    assert r["incident"]["protocol_finished"] is True and r["incident"]["status"] == "ACTIVE"
    assert "Help is on the way" in r["speech"]
    assert "stay with you" in r["speech"].lower() or "still" in r["speech"].lower() or "help is on the way" in r["speech"].lower()
