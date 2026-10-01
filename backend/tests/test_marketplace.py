from tests.conftest import km


def post(p, **kw):
    body = {"kind": "gift", "category": "furniture", "title": "Old sofa", "description": "Free to a good home"}
    body.update(kw)
    return p.post("/api/marketplace", body)


def test_gift_flow_claim_accept_reserves_and_notifies(make_user):
    giver, taker, other = make_user("Giver G"), make_user("Taker T", where=(0.5, 0)), make_user("Other O", where=(0.3, 0.3))
    lid = post(giver).json()["id"]

    r = taker.post(f"/api/marketplace/{lid}/claims", {"message": "I can collect today"})
    assert r.status_code == 201
    assert other.post(f"/api/marketplace/{lid}/claims", {}).status_code == 201
    assert taker.post(f"/api/marketplace/{lid}/claims", {}).status_code == 409  # only once

    detail = giver.get(f"/api/marketplace/{lid}").json()
    assert detail["claim_count"] == 2 and len(detail["claims"]) == 2
    assert "claims" not in taker.get(f"/api/marketplace/{lid}").json()  # others' requests stay private

    assert taker.post(f"/api/marketplace/{lid}/claims/{r.json()['id']}/accept").status_code == 403  # only the owner decides
    assert giver.post(f"/api/marketplace/{lid}/claims/{r.json()['id']}/accept").status_code == 200

    d = taker.get(f"/api/marketplace/{lid}").json()
    assert d["status"] == "reserved" and d["reserved_for_me"] is True
    assert other.post(f"/api/marketplace/{lid}/claims", {}).status_code == 409  # now taken
    assert any(n["kind"] == "marketplace_accepted" for n in taker.get("/api/notifications").json()["items"])


def test_listing_validation_rules(make_user):
    u = make_user("Seller S")
    assert post(u, kind="sell").status_code == 422                       # needs a price
    assert post(u, kind="gift", price=10).status_code == 422             # gifts are free
    assert post(u, kind="service", category="pest_control").status_code == 422  # needs a phone
    assert post(u, category="pest_control").status_code == 422           # category not valid for gifts
    assert post(u, kind="service", category="pest_control", contact_phone="+91 98200 11111", price=500).status_code == 201


def test_browse_filters_distance_and_privacy(make_user):
    a, b = make_user("Alice A"), make_user("Bob B", where=(40, 0))
    near = post(a, title="Near item").json()
    post(b, title="Far item")
    post(a, kind="service", category="pest_control", title="Pest control", contact_phone="+91 98200 11111")
    post(a, kind="sell", category="books", title="Novel set", price=200)

    titles = {x["title"] for x in a.get("/api/marketplace").json()}
    assert "Near item" in titles and "Far item" not in titles
    assert [x["title"] for x in a.get("/api/marketplace?kind=service").json()] == ["Pest control"]
    assert [x["title"] for x in a.get("/api/marketplace?q=novel").json()] == ["Novel set"]
    assert a.get("/api/marketplace?kind=bogus").status_code == 422

    seen = b.get(f"/api/marketplace/{near['id']}").json()
    assert seen["owner"]["name"] == "Alice"           # first name only
    assert seen["contact_phone"] is None              # private items never expose a phone


def test_only_owner_can_edit_close_or_delete(make_user):
    a, b = make_user("Alice A"), make_user("Bob B")
    lid = post(a).json()["id"]
    assert b.patch(f"/api/marketplace/{lid}", {"status": "closed"}).status_code == 403
    assert b.delete(f"/api/marketplace/{lid}").status_code == 403
    assert a.patch(f"/api/marketplace/{lid}", {"status": "closed"}).status_code == 200
    assert a.get("/api/marketplace").json() == []     # closed listings leave the feed
    assert a.delete(f"/api/marketplace/{lid}").status_code == 204


def test_withdraw_releases_reservation(make_user):
    a, b = make_user("Alice A"), make_user("Bob B")
    lid = post(a).json()["id"]
    cid = b.post(f"/api/marketplace/{lid}/claims", {}).json()["id"]
    a.post(f"/api/marketplace/{lid}/claims/{cid}/accept")
    assert b.post(f"/api/marketplace/{lid}/claims/{cid}/withdraw").status_code == 200
    assert a.get(f"/api/marketplace/{lid}").json()["status"] == "available"
    mine = b.get("/api/marketplace/mine").json()
    assert mine["requested"][0]["my_claim"]["status"] == "withdrawn"
