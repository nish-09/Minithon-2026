import threading
from datetime import timedelta

from app.models import Assignment, HelpRequest, utcnow
from app.services import orchestrator as orch
from tests.conftest import SessionLocal, km

CUPBOARD = "I need someone to help me move a cupboard"


def mk(p, text=CUPBOARD, mode="community", **kw):
    lat, lng = km(0, 0)
    r = p.post("/api/requests", {"text": text, "lat": lat, "lng": lng, "routing_mode": mode, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def get(p, rid):
    return p.get(f"/api/requests/{rid}").json()


def test_create_understands_text_and_sets_lifecycle(make_user):
    me, rahul = make_user("Nishit"), make_user("Rahul", (0.7, 0), skills=["physical_assistance"])
    r = mk(me, "Nexa, I need someone to help me move a cupboard.")
    assert r["category"] == "household_assistance" and r["urgency"] == "normal" and r["skills_required"] == ["physical_assistance"]
    assert r["status"] == "HELPERS_NOTIFIED"
    hist = [h["to"] for h in get(me, r["id"])["history"]]
    assert hist[:4] == ["CREATED", "ANALYZING", "MATCHING", "HELPERS_NOTIFIED"]


def test_full_lifecycle_to_rated_with_credits_and_trust(make_user):
    me, rahul = make_user("Nishit"), make_user("Rahul Shah", (0.7, 0), skills=["physical_assistance"], verified=True)
    r = mk(me)
    before = rahul.get("/api/users/%d/trust" % rahul.id).json()["score"]
    assert rahul.post(f"/api/matching/{r['id']}/accept").status_code == 200
    assert rahul.post(f"/api/requests/{r['id']}/progress", {"status": "ON_THE_WAY"}).json()["my_assignment"]["status"] == "ACTIVE"
    assert get(me, r["id"])["status"] == "ON_THE_WAY"
    assert rahul.post(f"/api/requests/{r['id']}/progress", {"status": "IN_PROGRESS"}).status_code == 200
    assert get(me, r["id"])["status"] == "IN_PROGRESS"
    done = me.post(f"/api/requests/{r['id']}/complete")
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
    assert rahul.get("/api/credits").json()["balance"] == 30  # 20 starting + 10 earned
    assert me.get("/api/credits").json()["balance"] == 10  # 20 - 10
    rv = me.post(f"/api/requests/{r['id']}/review", {"helper_id": rahul.id, "rating": 5, "comment": "Great"})
    assert rv.status_code == 201
    assert get(me, r["id"])["status"] == "RATED"
    assert me.post(f"/api/requests/{r['id']}/review", {"helper_id": rahul.id, "rating": 4}).status_code == 409  # one review per helper
    after = rahul.get("/api/users/%d/trust" % rahul.id).json()
    assert after["score"] > before and after["stats"]["completed"] == 1 and after["stats"]["rating"] == 5.0
    assert rahul.get(f"/api/users/{rahul.id}/reviews").json()[0]["comment"] == "Great"


def test_credits_never_block_help_or_go_negative(make_user):
    me, h = make_user("Broke"), make_user("Helper", (0.7, 0))
    for _ in range(4):  # drain credits: each completed request costs 10, floor is 0
        r = mk(me)
        h.post(f"/api/matching/{r['id']}/accept")
        assert me.post(f"/api/requests/{r['id']}/complete").status_code == 200
    assert me.get("/api/credits").json()["balance"] == 0  # clamped, requests still worked
    assert mk(me)["status"] == "HELPERS_NOTIFIED"  # zero credits never blocks a request


def test_donate_credits(make_user):
    a, b = make_user("A B"), make_user("C D")
    assert a.post("/api/credits/donate", {"to_user_id": b.id, "amount": 15}).status_code == 200
    assert a.get("/api/credits").json()["balance"] == 5 and b.get("/api/credits").json()["balance"] == 35
    assert a.post("/api/credits/donate", {"to_user_id": b.id, "amount": 6}).status_code == 400  # insufficient
    assert a.post("/api/credits/donate", {"to_user_id": a.id, "amount": 1}).status_code == 400
    assert a.post("/api/credits/donate", {"to_user_id": b.id, "amount": 0}).status_code == 422
    assert a.post("/api/credits/donate", {"to_user_id": 9999, "amount": 1}).status_code == 400


def test_edit_request(make_user):
    me, h = make_user("Nishit"), make_user("Rahul", (0.7, 0))
    r = mk(me)
    p = me.patch(f"/api/requests/{r['id']}", {"title": "Move wardrobe", "num_helpers": 2})
    assert p.status_code == 200 and p.json()["title"] == "Move wardrobe" and p.json()["num_helpers"] == 2
    assert h.patch(f"/api/requests/{r['id']}", {"title": "Hacked"}).status_code == 403
    assert me.patch(f"/api/requests/{r['id']}", {"num_helpers": 0}).status_code == 422
    h.post(f"/api/matching/{r['id']}/accept")
    assert me.patch(f"/api/requests/{r['id']}", {"num_helpers": 1}).status_code == 200  # == filled slots is fine
    me.post(f"/api/requests/{r['id']}/cancel")
    assert me.patch(f"/api/requests/{r['id']}", {"title": "Too late"}).status_code == 409


def test_cancel_notifies_and_withdraws(make_user):
    me, h1, h2 = make_user("Nishit"), make_user("H1", (0.7, 0)), make_user("H2", (0, 0.7))
    r = mk(me)
    c = me.post(f"/api/requests/{r['id']}/cancel")
    assert c.status_code == 200 and c.json()["status"] == "CANCELLED"
    assert h1.get("/api/requests?scope=invited").json() == []  # no longer open to anyone
    kinds = [n["kind"] for n in h1.get("/api/notifications").json()["items"]]
    assert "request_cancelled" in kinds
    assert me.post(f"/api/requests/{r['id']}/cancel").status_code == 409  # already cancelled
    assert me.post(f"/api/requests/{r['id']}/complete").status_code == 409


def test_cancel_after_assignment_notifies_helper_and_frees_them(make_user):
    me, h = make_user("Nishit"), make_user("H1", (0.7, 0))
    r = mk(me)
    h.post(f"/api/matching/{r['id']}/accept")
    assert me.post(f"/api/requests/{r['id']}/cancel").status_code == 200
    assert any(n["kind"] == "request_cancelled" for n in h.get("/api/notifications").json()["items"])
    assert h.post(f"/api/requests/{r['id']}/progress", {"status": "ON_THE_WAY"}).status_code in (403, 404)


def test_only_requester_can_cancel_or_complete(make_user):
    me, h, nearby, stranger = make_user("Nishit"), make_user("H", (0.7, 0)), make_user("Nearby", (0.5, 0.5)), make_user("Far Away", (30, 0))
    r = mk(me)
    h.post(f"/api/matching/{r['id']}/accept")
    assert h.post(f"/api/requests/{r['id']}/cancel").status_code == 403
    assert h.post(f"/api/requests/{r['id']}/complete").status_code == 403
    assert nearby.post(f"/api/requests/{r['id']}/cancel").status_code == 403  # was notified, but is not the requester
    assert stranger.post(f"/api/requests/{r['id']}/cancel").status_code == 404  # existence not revealed


def test_request_expires(make_user):
    me, h = make_user("Nishit"), make_user("H", (0.7, 0))
    r = mk(me)
    with SessionLocal() as db:
        stats = orch.process_timeouts(db, now=utcnow() + timedelta(hours=3))
        db.commit()
    assert stats["expired_requests"] == 1
    assert get(me, r["id"])["status"] == "EXPIRED"
    assert any(n["kind"] == "request_expired" for n in me.get("/api/notifications").json()["items"])
    assert h.post(f"/api/matching/{r['id']}/accept").status_code == 409


def test_helper_window_expiry_then_next_batch_then_widen(make_user):
    me = make_user("Nishit")
    near = [make_user(f"Near{i}", (0.3 + i / 10, 0)) for i in range(3)]
    second = make_user("Second Batch", (1.0, 1.0))
    far = make_user("Far Helper", (14, 0))  # outside 10 km, inside widened 20 km
    r = mk(me)
    assert {x["user_id"] for x in get(me, r["id"])["recipients"]} == {h.id for h in near}  # batch of 3
    with SessionLocal() as db:
        orch.process_timeouts(db, now=utcnow() + timedelta(minutes=4)); db.commit()
    rec = {x["user_id"] for x in get(me, r["id"])["recipients"]}
    assert second.id in rec  # next batch notified after the first batch timed out
    with SessionLocal() as db:
        orch.process_timeouts(db, now=utcnow() + timedelta(minutes=9)); db.commit()
    assert far.id in {x["user_id"] for x in get(me, r["id"])["recipients"]}  # radius widened


def test_unmatched_request_alerts_admin_for_urgent(make_user):
    admin = make_user("Admin", role="admin", available=False)
    me = make_user("Lonely")  # nobody around
    lat, lng = km(0, 0)
    r = me.post("/api/requests", {"text": "urgent, my basement is flooding right now", "lat": lat, "lng": lng})
    assert r.status_code == 201 and r.json()["urgency"] == "urgent"
    assert any(n["kind"] == "unmatched_urgent" for n in admin.get("/api/notifications").json()["items"])
    assert admin.get("/api/admin/dashboard").json()["unmatched_requests"] == 1


# ---------------- race conditions ----------------
def test_simultaneous_acceptance_only_one_wins(make_user):
    me = make_user("Nishit")
    helpers = [make_user(f"Helper{i}", (0.3 + i / 10, 0)) for i in range(3)]
    r = mk(me)
    results, barrier = [], threading.Barrier(3)

    def go(h):
        with SessionLocal() as db:
            from app.models import User
            barrier.wait()
            try:
                orch.helper_accept(db, r["id"], db.get(User, h.id))
                db.commit()
                results.append("ok")
            except orch.FlowError as e:
                db.rollback()
                results.append(e.status)
            except Exception as e:  # sqlite "database is locked" also means the loser lost
                db.rollback()
                results.append(type(e).__name__)

    ts = [threading.Thread(target=go, args=(h,)) for h in helpers]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert results.count("ok") == 1, results
    with SessionLocal() as db:
        assert db.query(Assignment).filter_by(request_id=r["id"]).count() == 1
        assert db.get(HelpRequest, r["id"]).filled_slots == 1
    cur = get(me, r["id"])
    assert cur["status"] == "ACCEPTED"
    # the two losers were told the request was filled and their notifications were withdrawn
    losers = [h for h in helpers if not any(a["helper"]["id"] == h.id for a in cur["assignments"])]
    assert all(any(n["kind"] == "request_filled" for n in l.get("/api/notifications").json()["items"]) for l in losers)


def test_multi_helper_request_fills_exactly_n_slots(make_user):
    me = make_user("Nishit")
    hs = [make_user(f"H{i}", (0.3 + i / 10, 0)) for i in range(5)]
    lat, lng = km(0, 0)
    r = me.post("/api/requests", {"text": "I need two people to help me move a sofa", "lat": lat, "lng": lng, "routing_mode": "community",
                                  "overrides": {"num_helpers": 2}}).json()
    # only 3 are notified per batch; all three try
    invited = [h for h in hs if h.get("/api/requests?scope=invited").json()]
    assert len(invited) == 3
    codes = [h.post(f"/api/matching/{r['id']}/accept").status_code for h in invited]
    assert codes.count(200) == 2 and codes.count(409) == 1
    assert len(get(me, r["id"])["assignments"]) == 2
    assert me.post(f"/api/requests/{r['id']}/complete").status_code == 200
    assert all(h.get("/api/credits").json()["balance"] in (20, 30) for h in hs)


def test_double_accept_and_unrelated_accept_rejected(make_user):
    me, h, other = make_user("Nishit"), make_user("H", (0.7, 0)), make_user("Other", (30, 0))
    r = mk(me)
    assert h.post(f"/api/matching/{r['id']}/accept").status_code == 200
    assert h.post(f"/api/matching/{r['id']}/accept").status_code == 409
    assert other.post(f"/api/matching/{r['id']}/accept").status_code == 404  # never notified => cannot even learn it exists
    assert me.post(f"/api/matching/{r['id']}/accept").status_code == 404  # requester was never a recipient


def test_helper_withdraw_reopens_matching(make_user):
    me, h1, h2 = make_user("Nishit"), make_user("H1", (0.3, 0)), make_user("H2", (0.4, 0))
    r = mk(me)
    h1.post(f"/api/matching/{r['id']}/accept")
    assert h1.post(f"/api/requests/{r['id']}/withdraw").status_code == 200
    cur = get(me, r["id"])
    assert cur["filled_slots"] == 0 and cur["status"] in ("MATCHING", "HELPERS_NOTIFIED")
    assert h1.get(f"/api/users/{h1.id}/trust").json()["stats"]["cancellation_rate"] == 100


def test_no_show_recorded_and_request_reopens(make_user):
    me, h1, h2 = make_user("Nishit"), make_user("H1", (0.3, 0)), make_user("H2", (0.4, 0))
    r = mk(me)
    h1.post(f"/api/matching/{r['id']}/accept")
    assert me.post(f"/api/requests/{r['id']}/no-show", {"helper_id": h1.id}).status_code == 200
    assert h1.get(f"/api/users/{h1.id}/trust").json()["stats"]["no_show_rate"] == 100
    assert get(me, r["id"])["filled_slots"] == 0


# ---------------- chat & privacy ----------------
def test_chat_only_between_requester_and_assigned_helper(make_user):
    me, h, other = make_user("Nishit"), make_user("H", (0.7, 0)), make_user("Other", (30, 0))
    r = mk(me)
    assert me.post(f"/api/requests/{r['id']}/messages", {"body": "hello"}).status_code == 403  # nobody assigned yet
    h.post(f"/api/matching/{r['id']}/accept")
    assert me.post(f"/api/requests/{r['id']}/messages", {"body": "Door is on the left"}).status_code == 201
    assert h.post(f"/api/requests/{r['id']}/messages", {"body": "On my way"}).status_code == 201
    assert [m["body"] for m in me.get(f"/api/requests/{r['id']}/messages").json()] == ["Door is on the left", "On my way"]
    assert other.get(f"/api/requests/{r['id']}/messages").status_code == 404
    assert me.post(f"/api/requests/{r['id']}/messages", {"body": ""}).status_code == 422


def test_location_privacy_fuzzed_for_recipients_exact_for_assigned_when_shared(make_user):
    me, h, h2 = make_user("Nishit"), make_user("H", (0.7, 0)), make_user("H2", (0.8, 0))
    lat, lng = km(0.123, 0.456)
    r = me.post("/api/requests", {"text": CUPBOARD, "lat": lat, "lng": lng, "routing_mode": "community", "share_location": True}).json()
    seen = h.get(f"/api/requests/{r['id']}").json()
    assert seen["location_approximate"] is True and seen["lat"] == round(lat, 2) != lat
    h.post(f"/api/matching/{r['id']}/accept")
    assigned = h.get(f"/api/requests/{r['id']}").json()
    assert assigned["lat"] == lat and assigned["location_approximate"] is False  # consented exact location
    # a second request WITHOUT consent stays approximate even for the assigned helper
    r2 = me.post("/api/requests", {"text": CUPBOARD, "lat": lat, "lng": lng, "routing_mode": "community", "share_location": False}).json()
    h2.post(f"/api/matching/{r2['id']}/accept")
    assert h2.get(f"/api/requests/{r2['id']}").json()["location_approximate"] is True


def test_radar_is_anonymised_and_hides_critical(make_user):
    me, viewer = make_user("Nishit Sharma"), make_user("Viewer", (1, 0))
    mk(me)
    me_crit = make_user("Hurt Person", (0.2, 0.2))
    lat, lng = km(0.2, 0.2)
    me_crit.post("/api/requests", {"text": "I fell and my arm is bleeding badly", "lat": lat, "lng": lng, "routing_mode": "community"})
    radar = viewer.get("/api/requests/radar?radius_km=10").json()
    assert all(x["urgency"] != "critical" for x in radar if not x["invited"])
    blob = str(radar)
    assert "Nishit" not in blob and "cupboard" not in blob  # no names or free text
    assert all(set(x) >= {"lat", "lng", "category", "urgency"} for x in radar)


def test_request_validation(make_user):
    me = make_user("Nishit")
    lat, lng = km(0, 0)
    bad = [
        {"text": "hi", "lat": lat, "lng": lng},  # too short
        {"text": CUPBOARD, "lat": 123, "lng": lng},  # out-of-range latitude
        {"text": CUPBOARD, "lat": lat, "lng": lng, "routing_mode": "teleport"},
        {"text": CUPBOARD, "lat": lat, "lng": lng, "overrides": {"num_helpers": 99}},
        {"text": CUPBOARD, "lat": lat, "lng": lng, "hack": True},
        {"text": "x" * 2000, "lat": lat, "lng": lng},
    ]
    for b in bad:
        assert me.post("/api/requests", b).status_code == 422, b
    assert me.post("/api/requests", {"text": CUPBOARD, "lat": lat}).status_code == 422  # lat without lng
    assert me.post("/api/requests", {"text": CUPBOARD, "lat": lat, "lng": lng, "overrides": {"category": "nonsense"}}).status_code == 400


def test_request_needs_location(client):
    r = client.post("/api/auth/register", json={"name": "No Loc", "email": "noloc@nexa-test.app", "password": "password123"})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.post("/api/requests", headers=h, json={"text": CUPBOARD}).status_code == 422


def test_critical_urgency_cannot_be_lowered_by_override(make_user):
    me = make_user("Nishit")
    lat, lng = km(0, 0)
    r = me.post("/api/requests", {"text": "I can't breathe and have chest pain", "lat": lat, "lng": lng, "overrides": {"urgency": "normal"}})
    assert r.status_code == 201 and r.json()["urgency"] == "critical"


def test_api_timestamps_are_timezone_aware(make_user, befriend):
    """SQLite returns naive datetimes; the API must still emit explicit UTC offsets so browsers parse them correctly."""
    me, mom = make_user("Nishit"), make_user("Mom", (1, 0))
    befriend(me, mom, "mother")
    r = mk(me, mode="circle_first")
    for key in ("created_at", "updated_at", "expires_at", "circle_deadline"):
        assert r[key].endswith("+00:00"), (key, r[key])
    assert get(me, r["id"])["history"][0]["at"].endswith("+00:00")
