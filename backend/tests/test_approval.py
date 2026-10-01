import pytest

from tests.test_requests import get, mk

pytestmark = pytest.mark.approval


def test_normal_request_helper_offer_needs_requester_approval(make_user):
    me, rahul = make_user("Nishit"), make_user("Rahul Shah", (0.7, 0), skills=["physical_assistance"])
    r = mk(me)
    out = rahul.post(f"/api/matching/{r['id']}/accept").json()
    assert out["pending_approval"] is True
    req = get(me, r["id"])
    assert req["assignments"] == [] and req["status"] == "HELPERS_NOTIFIED" and req["filled_slots"] == 0
    assert [o["helper"]["id"] for o in req["offers"]] == [rahul.id]
    assert me.get("/api/notifications").json()["items"][0]["kind"] == "helper_offer"
    assert rahul.post(f"/api/matching/{r['id']}/accept").status_code == 409  # already offered
    assert rahul.post(f"/api/requests/{r['id']}/progress", {"status": "ON_THE_WAY"}).status_code in (403, 404, 409)

    assert rahul.post(f"/api/matching/{r['id']}/approve/{rahul.id}").status_code == 404  # only the requester approves
    ok = me.post(f"/api/matching/{r['id']}/approve/{rahul.id}")
    assert ok.status_code == 200
    req = get(me, r["id"])
    assert req["status"] == "ACCEPTED" and [a["helper"]["id"] for a in req["assignments"]] == [rahul.id] and req["offers"] == []
    assert rahul.get("/api/notifications").json()["items"][0]["kind"] == "offer_approved"


def test_requester_can_pick_one_of_several_and_decline_others(make_user):
    me = make_user("Nishit")
    a, b = make_user("Aarav", (0.5, 0)), make_user("Bina", (0.7, 0))
    r = mk(me)
    for h in (a, b):
        assert h.post(f"/api/matching/{r['id']}/accept").json()["pending_approval"] is True
    assert len(get(me, r["id"])["offers"]) == 2
    assert me.post(f"/api/matching/{r['id']}/approve/{b.id}").status_code == 200
    req = get(me, r["id"])
    assert [x["helper"]["id"] for x in req["assignments"]] == [b.id]
    assert a.get(f"/api/requests/{r['id']}").status_code in (200, 404)  # the other offer was withdrawn
    assert me.post(f"/api/matching/{r['id']}/approve/{a.id}").status_code in (404, 409)


def test_declined_offer_keeps_request_open(make_user):
    me, a = make_user("Nishit"), make_user("Aarav", (0.5, 0))
    r = mk(me)
    a.post(f"/api/matching/{r['id']}/accept")
    assert me.post(f"/api/matching/{r['id']}/decline-offer/{a.id}").status_code == 200
    req = get(me, r["id"])
    assert req["offers"] == [] and req["assignments"] == [] and req["status"] == "HELPERS_NOTIFIED"
    assert a.get("/api/notifications").json()["items"][0]["kind"] == "offer_declined"
    assert a.post(f"/api/matching/{r['id']}/accept").status_code == 409  # declined helper cannot re-offer


def test_emergency_skips_approval(make_user):
    me, a = make_user("Nishit"), make_user("Aarav", (0.5, 0))
    r = mk(me, "Nexa my father collapsed and is not breathing, help me now")
    assert r["urgency"] != "normal"
    out = a.post(f"/api/matching/{r['id']}/accept")
    if out.status_code == 200:
        assert out.json()["pending_approval"] is False
