"""The two end-to-end scenarios from the product brief, driven through the public API only."""
from datetime import timedelta

from app.models import utcnow
from app.services import orchestrator as orch
from tests.conftest import SessionLocal, km
from tests.test_trust import add_history


def world(make_user, befriend):
    nishit = make_user("Nishit Sharma")
    uncle = make_user("Suresh Sharma", (1.4, 0), skills=["physical_assistance"], verified=True)
    mom = make_user("Anita Sharma", (0.85, 0.85), verified=True)
    kabir = make_user("Kabir Malhotra", (-2.4, -2.4), verified=True)
    rahul = make_user("Rahul Shah", (0.7, 0), skills=["physical_assistance", "carpentry"], verified=True)
    aarav = make_user("Aarav Mehta", (0, 0.5), skills=["first_aid", "cpr"], certs=["first_aid_cert", "cpr_cert"], verified=True)
    client = make_user("Past Client", (20, 20))
    befriend(nishit, uncle, "uncle", priority=1); befriend(nishit, mom, "mother", priority=2); befriend(nishit, kabir, "friend", priority=3)
    add_history(rahul.id, client.id, n=14, rating=5, cat="household_assistance")
    add_history(aarav.id, client.id, n=23, rating=5, cat="medical_assistance")
    with SessionLocal() as db:
        from app.services import trust
        for u in (rahul, aarav, uncle):
            trust.refresh_trust(db, u.id)
        db.commit()
    return nishit, uncle, mom, kabir, rahul, aarav


def vc(p, text, ctx=None, share=True):
    lat, lng = km(0, 0)
    r = p.post("/api/voice/command", {"text": text, "lat": lat, "lng": lng, "share_location": share, "context": ctx or {}})
    assert r.status_code == 200, r.text
    return r.json()


def test_scenario_1_home_alone_trusted_circle_accepts(make_user, befriend):
    nishit, uncle, mom, kabir, rahul, aarav = world(make_user, befriend)

    t1 = vc(nishit, "Nexa, I need someone to help me move a cupboard.")
    u = t1["data"]["understanding"]
    assert (u["category"], u["urgency"], u["skills_required"]) == ("household_assistance", "normal", ["physical_assistance"])
    assert t1["speech"] == "I can help with that. You have two relatives and one trusted friend nearby. Would you like me to ask them first?"

    t2 = vc(nishit, "Yes.", t1["context"])
    rid = t2["data"]["request_id"]
    assert t2["data"]["status"] == "TRUSTED_CIRCLE"
    assert rahul.get("/api/requests?scope=invited").json() == []  # community not contacted while the circle decides

    accepted = uncle.post(f"/api/matching/{rid}/accept").json()
    req = nishit.get(f"/api/requests/{rid}").json()
    a = req["assignments"][0]
    assert req["status"] == "ACCEPTED" and a["helper"]["name"] == "Suresh Sharma" and a["channel"] == "circle"
    assert abs(a["distance_km"] - 1.4) < 0.05 and 3 <= a["eta_minutes"] <= 8 and a["helper"]["trust_score"] > 40  # verified, but no history yet: provisional
    assert nishit.get("/api/notifications").json()["items"][0]["kind"] == "helper_accepted"
    # mom and the friend are released
    assert mom.get("/api/requests?scope=invited").json() == []

    uncle.post(f"/api/requests/{rid}/progress", {"status": "ON_THE_WAY"})
    uncle.post(f"/api/requests/{rid}/progress", {"status": "IN_PROGRESS"})
    assert nishit.post(f"/api/requests/{rid}/complete").json()["status"] == "COMPLETED"
    assert nishit.post(f"/api/requests/{rid}/review", {"helper_id": uncle.id, "rating": 5, "comment": "Thanks uncle!"}).status_code == 201
    assert nishit.get(f"/api/requests/{rid}").json()["status"] == "RATED"
    assert uncle.get("/api/credits").json()["balance"] == 30


def test_scenario_1b_nobody_in_circle_available_falls_back_to_smartmatch(make_user, befriend):
    nishit, uncle, mom, kabir, rahul, aarav = world(make_user, befriend)
    t1 = vc(nishit, "Nexa, I need someone to help me move a cupboard.")
    rid = vc(nishit, "Yes.", t1["context"])["data"]["request_id"]

    # nobody answers inside the 5 minute window
    with SessionLocal() as db:
        stats = orch.process_timeouts(db, now=utcnow() + timedelta(minutes=5, seconds=5))
        db.commit()
    assert stats["escalated"] == 1
    msgs = [n["body"] for n in nishit.get("/api/notifications").json()["items"] if n["kind"] == "escalated"]
    assert msgs == ["Nobody from your trusted circle is available. I'll find a nearby community helper."]
    assert nishit.get(f"/api/requests/{rid}").json()["status"] == "HELPERS_NOTIFIED"

    best = nishit.get(f"/api/matching/{rid}").json()["matches"]
    top = best[0]
    assert top["helper"]["name"] == "Rahul Shah" and top["relationship_label"] == "Verified nearby helper"
    assert abs(top["distance_km"] - 0.7) < 0.05 and top["eta_minutes"] <= 4
    assert top["trust_score"] > 60 and top["category_trust"] > top["trust_score"] - 20
    assert any("similar help" in r for r in top["reasons"])  # relevant experience: furniture assistance
    assert top["match_score"] != top["trust_score"]  # two different measures

    assert rahul.post(f"/api/matching/{rid}/accept").status_code == 200
    final = nishit.get(f"/api/requests/{rid}").json()
    assert final["status"] == "ACCEPTED" and final["assignments"][0]["channel"] == "community"
    # earlier circle members who did not answer can no longer accept
    assert uncle.post(f"/api/matching/{rid}/accept").status_code in (200, 409)  # open slot already taken => 409
    assert len(nishit.get(f"/api/requests/{rid}").json()["assignments"]) == 1


def test_scenario_2_critical_bike_fall_nexa_care_end_to_end(make_user, befriend):
    nishit, uncle, mom, kabir, rahul, aarav = world(make_user, befriend)

    understood = nishit.post("/api/ai/understand-request", {"text": "Nexa, I fell off my bike and my arm is bleeding."}).json()
    assert understood["understanding"]["urgency"] == "critical" and understood["understanding"]["skills_required"] == ["first_aid"]
    assert understood["suggested_routing"] == "emergency" and "112" in understood["emergency_advice"]

    out = vc(nishit, "Nexa, I fell off my bike and my arm is bleeding.")
    inc = out["data"]["incident"]
    rid = out["data"]["request_id"]
    assert inc["status"] == "ACTIVE" and inc["urgency"] == "CRITICAL" and inc["current_protocol"] == "BLEEDING_ASSISTANCE" and inc["location_shared"]
    assert "emergency" in out["speech"].lower() and "does not replace emergency services" in out["speech"]

    # circle + first-aid-trained helper are notified together; Rahul has no first-aid skill and is NOT bothered
    req = nishit.get(f"/api/requests/{rid}").json()
    notified = {r["user_id"] for r in req["recipients"]}
    assert aarav.id in notified and uncle.id in notified and mom.id in notified and rahul.id not in notified
    assert req["status"] == "HELPERS_NOTIFIED"

    # user follows the verified steps by voice
    s1 = vc(nishit, "Okay, I completed that.")
    assert s1["data"]["incident"]["current_step"] == 2
    s2 = vc(nishit, "I can't do that, I don't have a cloth")
    assert s2["speech"].startswith("Okay. I'll adjust the guidance.")

    # first suitable acceptance wins and everyone else is released
    assert aarav.post(f"/api/matching/{rid}/accept").status_code == 200
    assert uncle.post(f"/api/matching/{rid}/accept").status_code == 409
    state = nishit.get(f"/api/incidents/{inc['id']}").json()
    assert state["assigned_helper"] == f"USR-{aarav.id}" and 0 < state["helper_eta_minutes"] <= 3
    assert state["current_protocol"] == "BLEEDING_ASSISTANCE" and state["completed_steps"] == [1] and state["skipped_steps"] == [2]
    assert "Aarav is about" in vc(nishit, "how far is he?")["speech"]

    dz = vc(nishit, "I'm feeling dizzy now")
    assert dz["data"]["incident"]["current_protocol"] == "DIZZY_FAINTNESS" and dz["data"]["incident"]["escalation_level"] == 1

    aarav.post(f"/api/requests/{rid}/progress", {"status": "IN_PROGRESS"})
    done = vc(nishit, "Help has arrived.")
    assert done["data"]["incident"]["status"] == "RESOLVED" and "end NEXA CARE" in done["speech"]

    log = nishit.get(f"/api/incidents/{inc['id']}/log").json()
    assert {"protocol_selected", "step_completed", "step_skipped", "closed"} <= {x["kind"] for x in log}
    # the audit trail contains only approved protocol text as guidance
    from tests.test_care import ALL_STEP_TEXT
    presented = [x["content"] for x in log if x["kind"] == "step_presented"]
    assert presented and all(p in ALL_STEP_TEXT for p in presented)
