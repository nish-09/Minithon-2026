import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import km


def drain_until(ws, predicate, limit=12):
    seen = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg)
        if predicate(msg):
            return msg, seen
    raise AssertionError(f"expected event never arrived; saw {seen}")


def test_ws_rejects_bad_or_missing_token(client):
    for url in ("/ws", "/ws?token=garbage"):
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect(url):
                pass
        assert e.value.code == 4401


def test_ws_revoked_token_rejected(client, make_user):
    u = make_user("Logged Out")
    u.post("/api/auth/logout")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws?token={u.token}"):
            pass


def test_ws_ping_pong(client, make_user):
    u = make_user("Pinger Pat")
    with client.websocket_connect(f"/ws?token={u.token}") as ws:
        assert ws.receive_json() == {"type": "hello", "user_id": u.id}
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}


def test_helper_gets_live_notification_and_requester_gets_live_acceptance(client, make_user):
    me, helper = make_user("Nishit Sharma"), make_user("Rahul Shah", (0.7, 0))
    lat, lng = km(0, 0)
    with client.websocket_connect(f"/ws?token={helper.token}") as hws, client.websocket_connect(f"/ws?token={me.token}") as mws:
        hws.receive_json(); mws.receive_json()  # hello
        rid = me.post("/api/requests", {"text": "I need someone to help me move a cupboard", "lat": lat, "lng": lng}).json()["id"]
        note, _ = drain_until(hws, lambda m: m["type"] == "notification" and m["kind"] == "new_request")
        assert note["data"]["request_id"] == rid and "cupboard" in note["title"].lower()
        assert "Sharma" not in str(note)  # live payload respects the same privacy rules
        helper.post(f"/api/matching/{rid}/accept")
        ev, seen = drain_until(mws, lambda m: m["type"] == "notification" and m["kind"] == "helper_accepted")
        assert ev["data"]["helper_id"] == helper.id and ev["data"]["eta_minutes"] > 0
        updates = [m for m in seen if m["type"] == "request_update"]
        assert [u["status"] for u in updates][-2:] == ["ASSIGNED", "ACCEPTED"] and all(u["request_id"] == rid for u in updates)


def test_losing_helpers_are_told_request_is_filled_live(client, make_user):
    me, h1, h2 = make_user("Nishit Sharma"), make_user("Helper One", (0.5, 0)), make_user("Helper Two", (0.6, 0))
    lat, lng = km(0, 0)
    rid = me.post("/api/requests", {"text": "I need someone to help me move a cupboard", "lat": lat, "lng": lng}).json()["id"]
    with client.websocket_connect(f"/ws?token={h2.token}") as ws:
        ws.receive_json()
        h1.post(f"/api/matching/{rid}/accept")
        ev, _ = drain_until(ws, lambda m: m["type"] == "notification" and m["kind"] == "request_filled")
        assert ev["data"]["request_id"] == rid


def test_no_event_is_pushed_when_the_transaction_rolls_back(client, make_user):
    me, helper = make_user("Nishit Sharma"), make_user("Rahul Shah", (0.7, 0))
    lat, lng = km(0, 0)
    with client.websocket_connect(f"/ws?token={helper.token}") as ws:
        ws.receive_json()
        # a request that fails validation must not leak a notification to anyone
        bad = me.post("/api/requests", {"text": "I need someone to help me move a cupboard", "lat": lat, "lng": lng, "routing_mode": "custom",
                                        "custom_recipient_ids": [999999]})
        assert bad.status_code == 400
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}  # the very next message is the pong, nothing was queued before it
    assert helper.get("/api/notifications").json()["items"] == []


def test_incident_updates_push_to_user_and_assigned_helper(client, make_user):
    me, aarav = make_user("Nishit Sharma"), make_user("Aarav Mehta", (0, 0.5), skills=["first_aid"], certs=["first_aid_cert"], verified=True)
    lat, lng = km(0, 0)
    with client.websocket_connect(f"/ws?token={me.token}") as ws:
        ws.receive_json()
        out = me.post("/api/incidents", {"text": "I fell off my bike and my arm is bleeding", "lat": lat, "lng": lng, "share_location": True}).json()
        drain_until(ws, lambda m: m["type"] == "incident_update")
        aarav.post(f"/api/matching/{out['request_id']}/accept")
        ev, _ = drain_until(ws, lambda m: m["type"] == "incident_update")
        assert ev["incident_id"] == out["incident"]["id"]
        assert me.get(f"/api/incidents/{out['incident']['id']}").json()["assigned_helper"] == f"USR-{aarav.id}"
