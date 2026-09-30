from datetime import timedelta

from app.config import get_settings
from app.models import HelpRequest, utcnow
from app.services import orchestrator as orch
from tests.conftest import SessionLocal

CUPBOARD = "Nexa, I need someone to help me move a cupboard."


def sweep(minutes=0, seconds=0):
    with SessionLocal() as db:
        stats = orch.process_timeouts(db, now=utcnow() + timedelta(minutes=minutes, seconds=seconds))
        db.commit()
    return stats


def create(p, text=CUPBOARD, mode="circle_first", **kw):
    from tests.conftest import km
    lat, lng = km(0, 0)
    r = p.post("/api/requests", {"text": text, "lat": lat, "lng": lng, "share_location": True, "routing_mode": mode, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def status(p, rid):
    return p.get(f"/api/requests/{rid}").json()


# ---------------- relationship lifecycle ----------------
def test_add_accept_relationship_creates_two_verified_edges(make_user):
    a, b = make_user("Nishit Sharma"), make_user("Anita Sharma")
    r = a.post("/api/relationships", {"user_id": b.id, "relationship_type": "mother"})
    assert r.status_code == 201 and r.json()["status"] == "PENDING" and r.json()["direction"] == "outgoing"
    inc = b.get("/api/relationships").json()
    assert len(inc) == 1 and inc[0]["can_respond"] and inc[0]["relationship_type"] == "child"  # inverse label
    # initiator cannot accept their own invitation
    assert a.post(f"/api/relationships/{r.json()['id']}/accept").status_code == 409
    assert b.post(f"/api/relationships/{inc[0]['id']}/accept").status_code == 200
    assert a.get("/api/relationships").json()[0]["status"] == "ACCEPTED"
    assert b.get("/api/relationships").json()[0]["status"] == "ACCEPTED"


def test_add_by_email_does_not_leak_account_existence(make_user):
    a, b = make_user(), make_user()
    ghost = a.post("/api/relationships", {"email": "nobody@nexa-test.app", "relationship_type": "friend"})
    real = a.post("/api/relationships", {"email": b.email, "relationship_type": "friend"})
    assert ghost.status_code == 201 and ghost.json()["status"] == "invited"
    assert real.status_code == 201


def test_decline_remove_block(make_user, befriend):
    a, b, c = make_user(), make_user(), make_user()
    a.post("/api/relationships", {"user_id": b.id, "relationship_type": "cousin"})
    eid = b.get("/api/relationships").json()[0]["id"]
    assert b.post(f"/api/relationships/{eid}/decline").status_code == 200
    assert a.get("/api/relationships").json()[0]["status"] == "DECLINED"
    # after a decline the inviter may try again
    assert a.post("/api/relationships", {"user_id": b.id, "relationship_type": "cousin"}).status_code == 201

    edge = befriend(a, c, "friend")
    assert a.delete(f"/api/relationships/{edge}").status_code == 204
    assert all(e["user"]["id"] != c.id for e in a.get("/api/relationships").json())
    assert all(e["user"]["id"] != a.id for e in c.get("/api/relationships").json())

    edge = befriend(a, c, "friend")
    blocked = a.post(f"/api/relationships/{edge}/block")
    assert blocked.json()["status"] == "BLOCKED"
    assert c.post("/api/relationships", {"user_id": a.id, "relationship_type": "friend"}).status_code == 409  # cannot re-invite
    assert a.delete(f"/api/relationships/{edge}").status_code == 409  # block persists


def test_cannot_touch_other_peoples_edges(make_user, befriend):
    a, b, evil = make_user(), make_user(), make_user()
    edge = befriend(a, b, "friend")
    assert evil.patch(f"/api/relationships/{edge}", {"priority": 1}).status_code == 404
    assert evil.delete(f"/api/relationships/{edge}").status_code == 404
    assert evil.post(f"/api/relationships/{edge}/accept").status_code == 404
    assert evil.post(f"/api/relationships/{edge}/block").status_code == 404


def test_no_self_relationship_and_bad_type(make_user):
    a, b = make_user(), make_user()
    assert a.post("/api/relationships", {"user_id": a.id, "relationship_type": "friend"}).status_code == 400
    assert a.post("/api/relationships", {"user_id": b.id, "relationship_type": "overlord"}).status_code == 400
    assert a.post("/api/relationships", {"relationship_type": "friend"}).status_code == 422  # needs email or user_id


def test_edge_settings_validated(make_user, befriend):
    a, b = make_user(), make_user()
    edge = befriend(a, b, "friend")
    assert a.patch(f"/api/relationships/{edge}", {"priority": 11}).status_code == 422
    assert a.patch(f"/api/relationships/{edge}", {"visibility": "everyone"}).status_code == 422
    ok = a.patch(f"/api/relationships/{edge}", {"priority": 1, "can_receive_requests": False, "visibility": "me"})
    assert ok.status_code == 200 and ok.json()["priority"] == 1 and ok.json()["can_receive_requests"] is False


def test_trusted_circle_groups_and_nearby_count(make_user, befriend):
    me = make_user("Nishit Sharma")
    mom, cousin, friend, far = make_user("Mom", (1, 1)), make_user("Cousin", (1.8, 0)), make_user("Friend", (0, 2)), make_user("Far", (80, 0))
    befriend(me, mom, "mother"); befriend(me, cousin, "cousin"); befriend(me, friend, "friend"); befriend(me, far, "uncle")
    circle = me.get("/api/trusted-circle").json()
    assert len(circle["groups"]["family"]) == 3 and len(circle["groups"]["friends"]) == 1
    assert circle["total"] == 4 and circle["nearby_count"] == 3  # 80 km away is not "nearby"


# ---------------- privacy ----------------
def test_relationships_hidden_from_strangers_and_respect_visibility(make_user, befriend):
    me, mom, member, stranger = make_user("Nishit"), make_user("Mom"), make_user("Trusted Pal"), make_user("Stranger")
    befriend(me, mom, "mother"); befriend(me, member, "friend")
    assert stranger.get(f"/api/users/{me.id}/circle").json() == []  # strangers see nothing
    assert {x["user_id"] for x in member.get(f"/api/users/{me.id}/circle").json()} == {mom.id, member.id}  # circle members do
    assert {x["user_id"] for x in me.get(f"/api/users/{me.id}/circle").json()} == {mom.id, member.id}
    # owner tightens visibility to "me only": even circle members lose visibility
    assert me.patch("/api/users/me", {"relationship_visibility": "me"}).status_code == 200
    assert member.get(f"/api/users/{me.id}/circle").json() == [{"user_id": member.id, "name": member.name, "relationship_type": "friend"}]  # only their own edge
    assert stranger.get(f"/api/users/{me.id}/circle").json() == []


def test_stranger_helper_sees_verified_nearby_helper_not_relationship(make_user, befriend):
    me, rahul = make_user("Nishit Sharma"), make_user("Rahul Shah", (0.7, 0))
    req = create(me, mode="community")
    inbox = rahul.get("/api/requests?scope=invited").json()
    assert len(inbox) == 1
    text = str(inbox[0])
    assert inbox[0]["relationship_label"] is None
    assert inbox[0]["requester"]["name"] == "Nishit"  # first name only for strangers
    assert "cousin" not in text and "Sharma" not in text
    assert inbox[0]["raw_text"] is None  # free text stays private
    # requester sees them as anonymous community helper unless they opt to reveal
    rahul.post(f"/api/matching/{req['id']}/accept")
    a = me.get(f"/api/requests/{req['id']}").json()["assignments"][0]
    assert a["relationship_label"] == "Verified nearby helper"


def test_relationship_revealed_only_if_requester_chooses(make_user, befriend):
    me, cousin = make_user("Nishit Sharma"), make_user("Rohan Verma", (1.8, 0))
    befriend(me, cousin, "cousin")
    req = create(me, mode="circle_first", reveal_relationship=True)
    inbox = cousin.get("/api/requests?scope=invited").json()[0]
    assert inbox["relationship_label"] == "Nishit's cousin" and inbox["requester"]["name"] == "Nishit Sharma"
    cousin.post(f"/api/matching/{req['id']}/accept")
    assert me.get(f"/api/requests/{req['id']}").json()["assignments"][0]["relationship_label"] == "Nishit's cousin"


def test_circle_contact_selection_respected(make_user, befriend):
    me = make_user("Nishit")
    mom, uncle, cousin = make_user("Mom", (1, 0)), make_user("Uncle", (1.4, 0)), make_user("Cousin", (1.8, 0))
    befriend(me, mom, "mother"); befriend(me, uncle, "uncle", can_receive_requests=False); befriend(me, cousin, "cousin")
    req = create(me)
    assert len(mom.get("/api/requests?scope=invited").json()) == 1
    assert len(cousin.get("/api/requests?scope=invited").json()) == 1
    assert uncle.get("/api/requests?scope=invited").json() == []  # unchecked in "Who can be contacted"


def test_contact_can_opt_out_from_their_side(make_user, befriend):
    me, mom = make_user("Nishit"), make_user("Mom", (1, 0))
    befriend(me, mom, "mother")
    back = next(e for e in mom.get("/api/relationships").json() if e["user"]["id"] == me.id)
    assert mom.patch(f"/api/relationships/{back['id']}", {"can_receive_requests": False}).status_code == 200
    create(me)
    assert mom.get("/api/requests?scope=invited").json() == []


# ---------------- Trusted Circle First flow ----------------
def test_no_trusted_contacts_goes_straight_to_community(make_user):
    me, rahul = make_user("Nishit"), make_user("Rahul", (0.7, 0), skills=["physical_assistance"])
    req = create(me, mode="circle_first")
    assert req["status"] == "HELPERS_NOTIFIED" and req["circle_deadline"] is None
    assert [r["channel"] for r in me.get(f"/api/requests/{req['id']}").json()["recipients"]] == ["community"]
    kinds = [n["kind"] for n in me.get("/api/notifications").json()["items"]]
    assert "circle_unavailable" in kinds


def test_circle_first_waits_then_notifies_only_circle(make_user, befriend):
    me = make_user("Nishit")
    mom, stranger = make_user("Mom", (1.2, 0)), make_user("Rahul", (0.7, 0), skills=["physical_assistance"])
    befriend(me, mom, "mother")
    req = create(me)
    assert req["status"] == "TRUSTED_CIRCLE" and req["circle_deadline"]
    assert len(mom.get("/api/requests?scope=invited").json()) == 1
    assert stranger.get("/api/requests?scope=invited").json() == []  # community not contacted yet


def test_trusted_contact_accepts_and_is_assigned(make_user, befriend):
    me, uncle = make_user("Nishit"), make_user("Uncle", (1.4, 0))
    befriend(me, uncle, "uncle")
    req = create(me)
    r = uncle.post(f"/api/matching/{req['id']}/accept")
    assert r.status_code == 200 and r.json()["eta_minutes"] > 0 and abs(r.json()["distance_km"] - 1.4) < 0.05
    cur = status(me, req["id"])
    assert cur["status"] == "ACCEPTED" and cur["assignments"][0]["helper"]["id"] == uncle.id
    assert [h["to"] for h in cur["history"]][-2:] == ["ASSIGNED", "ACCEPTED"]


def test_trusted_contact_declines_then_all_declined_escalates_immediately(make_user, befriend):
    me = make_user("Nishit")
    mom, cousin, rahul = make_user("Mom", (1, 0)), make_user("Cousin", (1.8, 0)), make_user("Rahul", (0.7, 0), skills=["physical_assistance"])
    befriend(me, mom, "mother"); befriend(me, cousin, "cousin")
    req = create(me)
    assert mom.post(f"/api/matching/{req['id']}/reject").status_code == 200
    assert status(me, req["id"])["status"] == "TRUSTED_CIRCLE"  # one still pending
    assert cousin.post(f"/api/matching/{req['id']}/reject").status_code == 200
    cur = status(me, req["id"])
    assert cur["status"] == "HELPERS_NOTIFIED"  # did not wait out the window
    assert len(rahul.get("/api/requests?scope=invited").json()) == 1
    msgs = [n["body"] for n in me.get("/api/notifications").json()["items"] if n["kind"] == "escalated"]
    assert any("Nobody from your trusted circle is available" in m for m in msgs)


def test_timeout_escalates_to_smartmatch_community(make_user, befriend):
    me = make_user("Nishit")
    mom, rahul = make_user("Mom", (1, 0)), make_user("Rahul Shah", (0.7, 0), skills=["physical_assistance"])
    befriend(me, mom, "mother")
    req = create(me)
    assert sweep(minutes=1)["escalated"] == 0  # still inside the 5 minute window
    assert status(me, req["id"])["status"] == "TRUSTED_CIRCLE"
    assert sweep(minutes=6)["escalated"] == 1
    cur = status(me, req["id"])
    assert cur["status"] == "HELPERS_NOTIFIED"
    assert {r["channel"] for r in cur["recipients"] if r["user_id"] == rahul.id} == {"community"}
    assert [r["state"] for r in cur["recipients"] if r["user_id"] == mom.id] == ["EXPIRED"]
    # community helper can now accept and is assigned
    assert rahul.post(f"/api/matching/{req['id']}/accept").status_code == 200
    assert status(me, req["id"])["status"] == "ACCEPTED"


def test_lazy_escalation_on_read_without_sweeper(make_user, befriend):
    me, mom = make_user("Nishit"), make_user("Mom", (1, 0))
    befriend(me, mom, "mother")
    req = create(me)
    with SessionLocal() as db:
        r = db.get(HelpRequest, req["id"])
        r.circle_deadline = utcnow() - timedelta(seconds=1)
        db.commit()
    assert status(me, req["id"])["status"] in ("ESCALATED", "HELPERS_NOTIFIED", "MATCHING")  # escalated when read


def test_response_window_is_configurable(make_user, befriend, monkeypatch):
    me, mom = make_user("Nishit"), make_user("Mom", (1, 0))
    befriend(me, mom, "mother")
    monkeypatch.setattr(get_settings(), "circle_window_normal_s", 30)
    req = create(me)
    assert sweep(seconds=20)["escalated"] == 0
    assert sweep(seconds=40)["escalated"] == 1
    # per-user override
    me2, mom2 = make_user("Nishit Two"), make_user("Mom Two", (1, 0))
    befriend(me2, mom2, "mother")
    assert me2.patch("/api/users/me", {"circle_window_override_s": 900}).status_code == 200
    create(me2)
    assert sweep(minutes=10)["escalated"] == 0 and sweep(minutes=16)["escalated"] == 1


def test_expand_to_community_manually(make_user, befriend):
    me, mom, rahul = make_user("Nishit"), make_user("Mom", (1, 0)), make_user("Rahul", (0.7, 0), skills=["physical_assistance"])
    befriend(me, mom, "mother")
    req = create(me)
    r = me.post(f"/api/requests/{req['id']}/expand-to-community")
    assert r.status_code == 200 and r.json()["status"] == "HELPERS_NOTIFIED"
    assert rahul.post(f"/api/requests/{req['id']}/expand-to-community").status_code in (403, 404)  # only the requester


def test_ask_trusted_circle_after_choosing_community(make_user, befriend):
    me, mom, rahul = make_user("Nishit"), make_user("Mom", (1, 0)), make_user("Rahul", (0.7, 0))
    befriend(me, mom, "mother")
    req = create(me, mode="community")
    r = me.post(f"/api/requests/{req['id']}/trusted-circle")
    assert r.status_code == 200 and r.json()["asked"] == 1
    assert len(mom.get("/api/requests?scope=invited").json()) == 1
    assert me.post(f"/api/requests/{req['id']}/trusted-circle", {"recipient_ids": [rahul.id]}).status_code == 400  # not in circle


def test_custom_recipients_validated(make_user, befriend):
    me, mom, rahul, far = make_user("Nishit"), make_user("Mom", (1, 0)), make_user("Rahul", (0.7, 0)), make_user("Far", (60, 0))
    befriend(me, mom, "mother")
    from tests.conftest import km
    lat, lng = km(0, 0)
    base = {"text": CUPBOARD, "lat": lat, "lng": lng, "routing_mode": "custom"}
    assert me.post("/api/requests", base).status_code == 422  # needs recipients
    assert me.post("/api/requests", {**base, "custom_recipient_ids": [far.id]}).status_code == 400  # unreachable stranger
    ok = me.post("/api/requests", {**base, "custom_recipient_ids": [mom.id, rahul.id]})
    assert ok.status_code == 201
    assert len(mom.get("/api/requests?scope=invited").json()) == 1 and len(rahul.get("/api/requests?scope=invited").json()) == 1


# ---------------- escalation modes ----------------
def test_urgent_notifies_circle_and_community_together(make_user, befriend):
    me, mom, rahul = make_user("Nishit"), make_user("Mom", (1, 0)), make_user("Rahul", (0.7, 0), skills=["physical_assistance"])
    befriend(me, mom, "mother")
    req = create(me, text="I need help urgently right now, my cupboard fell and I am stuck, need someone to lift it")
    assert req["urgency"] == "urgent" and req["status"] == "HELPERS_NOTIFIED"
    channels = {r["user_id"]: r["channel"] for r in me.get(f"/api/requests/{req['id']}").json()["recipients"]}
    assert channels[mom.id] == "circle" and channels[rahul.id] == "community"


def test_critical_does_not_wait_for_circle_and_advises_emergency(make_user, befriend):
    me = make_user("Nishit")
    mom, aarav = make_user("Mom", (1, 0)), make_user("Aarav", (0, 0.5), skills=["first_aid"], certs=["first_aid_cert"], verified=True)
    befriend(me, mom, "mother")
    req = create(me, text="Nexa, I fell off my bike and my arm is bleeding.", mode="circle_first")
    assert req["urgency"] == "critical" and req["status"] == "HELPERS_NOTIFIED" and req["circle_deadline"] is None
    assert req["incident_id"]
    recips = {r["user_id"] for r in me.get(f"/api/requests/{req['id']}").json()["recipients"]}
    assert recips == {mom.id, aarav.id}
    advice = [n for n in me.get("/api/notifications").json()["items"] if n["kind"] == "emergency_advice"]
    assert advice and "does not replace emergency services" in advice[0]["body"]
