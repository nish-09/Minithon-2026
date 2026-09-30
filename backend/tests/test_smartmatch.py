
from app.models import Assignment, HelpRequest, utcnow
from tests.conftest import SessionLocal, km
from tests.test_trust import add_history


def request(p, text="I need someone to help me move a cupboard", **kw):
    lat, lng = km(0, 0)
    r = p.post("/api/requests", {"text": text, "lat": lat, "lng": lng, "routing_mode": "community", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def ranking(p, rid, limit=10):
    return p.get(f"/api/matching/{rid}?limit={limit}").json()["matches"]


def order(p, rid):
    return [m["helper"]["id"] for m in ranking(p, rid)]


def test_closer_helper_ranks_higher_all_else_equal(make_user):
    me = make_user("Nishit")
    near, mid, far = make_user("Near", (0.4, 0)), make_user("Mid", (3, 0)), make_user("Far", (8, 0))
    r = request(me)
    assert order(me, r["id"]) == [near.id, mid.id, far.id]
    m = ranking(me, r["id"])
    assert m[0]["eta_minutes"] < m[1]["eta_minutes"] < m[2]["eta_minutes"]
    assert m[0]["distance_km"] == 0.4 and m[0]["match_score"] > m[2]["match_score"]


def test_radius_respected(make_user):
    me, inside, outside = make_user("Nishit"), make_user("Inside", (9, 0)), make_user("Outside", (12, 0))
    assert order(me, request(me)["id"]) == [inside.id]


def test_skills_matter_certified_beats_declared_beats_none(make_user):
    me = make_user("Nishit")
    none = make_user("No Skill", (0.5, 0))
    declared = make_user("Declared", (0.5, 0.1), skills=["electrical"])
    licensed = make_user("Licensed", (0.5, 0.2), skills=["electrical"], certs=["electrician_license"], verified=True)
    r = request(me, "the wiring in my kitchen socket is sparking, I need an electrician")
    assert r["category"] == "repair" and "electrical" in r["skills_required"]
    o = order(me, r["id"])
    assert o.index(licensed.id) < o.index(declared.id) < o.index(none.id)
    top = ranking(me, r["id"])[0]
    assert any("Certified" in x for x in top["reasons"])


def test_unavailable_and_busy_helpers_excluded(make_user):
    me = make_user("Nishit")
    off, ok, busy = make_user("Offline", (0.3, 0), available=False), make_user("Online", (0.4, 0)), make_user("Busy", (0.2, 0))
    with SessionLocal() as db:
        for i in range(2):  # two active assignments => at capacity
            r = HelpRequest(requester_id=me.id, raw_text="x", title="x", category="other", urgency="normal", status="ACCEPTED", expires_at=utcnow(), lat=1, lng=1)
            db.add(r); db.flush()
            db.add(Assignment(request_id=r.id, helper_id=busy.id, status="ACTIVE"))
        db.commit()
    assert order(me, request(me)["id"]) == [ok.id]


def test_availability_schedule_lowers_score_outside_hours(make_user):
    me = make_user("Nishit")
    always, never = make_user("Always", (0.5, 0)), make_user("Nine To Five", (0.5, 0))
    never.patch("/api/users/me", {"availability_schedule": {"mon": ["03:00-03:30"]}})
    r = request(me)
    rk = {m["helper"]["id"]: m for m in ranking(me, r["id"])}
    assert rk[always.id]["breakdown"]["availability"] > rk[never.id]["breakdown"]["availability"]
    assert rk[always.id]["match_score"] > rk[never.id]["match_score"]


def test_trust_influences_ranking(make_user):
    me, client = make_user("Nishit"), make_user("Client", (20, 20))
    trusted = make_user("Trusted", (0.5, 0), verified=True)
    unknown = make_user("Unknown", (0.5, 0))
    add_history(trusted.id, client.id, n=12, rating=5)
    with SessionLocal() as db:
        from app.services import trust
        trust.refresh_trust(db, trusted.id); db.commit()
    m = {x["helper"]["id"]: x for x in ranking(me, request(me)["id"])}
    assert m[trusted.id]["trust_score"] > m[unknown.id]["trust_score"]
    assert m[trusted.id]["match_score"] > m[unknown.id]["match_score"]


def test_match_score_and_trust_score_are_separate_concepts(make_user):
    """Higher trust does not automatically mean a better match for THIS request."""
    me, client = make_user("Nishit"), make_user("Client", (20, 20))
    veteran = make_user("Trusted Far", (7, 0), verified=True)          # very trusted but far
    decent = make_user("Decent Near", (0.3, 0), skills=["physical_assistance"])  # less trusted but right here
    add_history(veteran.id, client.id, n=25, rating=5)
    with SessionLocal() as db:
        from app.services import trust
        trust.refresh_trust(db, veteran.id); db.commit()
    m = {x["helper"]["id"]: x for x in ranking(me, request(me)["id"])}
    assert m[veteran.id]["trust_score"] > m[decent.id]["trust_score"]
    assert m[decent.id]["match_score"] > m[veteran.id]["match_score"]


def test_relationship_priority_is_separate_from_match_suitability(make_user, befriend):
    me = make_user("Nishit")
    uncle, stranger = make_user("Uncle", (5, 0)), make_user("Stranger", (0.5, 0), skills=["physical_assistance"])
    befriend(me, uncle, "uncle", priority=1)
    r = request(me)
    m = {x["helper"]["id"]: x for x in ranking(me, r["id"])}
    assert m[uncle.id]["in_circle"] and m[uncle.id]["relationship_priority"] == 1 and m[uncle.id]["breakdown"]["relationship"] == 100
    assert not m[stranger.id]["in_circle"] and m[stranger.id]["breakdown"]["relationship"] == 0
    assert m[uncle.id]["relationship_label"] == "Nishit's uncle" and m[stranger.id]["relationship_label"] == "Verified nearby helper"
    assert m[stranger.id]["match_score"] > m[uncle.id]["match_score"]  # a close skilled neighbour beats family 5 km away


def test_user_controls_whether_trusted_circle_is_preferred(make_user, befriend):
    on, off = make_user("Prefers Circle"), make_user("Ignores Circle", circle_pref=False)
    outcomes = {}
    for who, (dx) in ((on, 0), (off, 0)):
        relative = make_user(f"Relative {who.name}", (2, 0))
        stranger = make_user(f"Stranger {who.name}", (2, 0.05))
        befriend(who, relative, "cousin", priority=1)
        r = request(who)
        m = {x["helper"]["id"]: x for x in ranking(who, r["id"])}
        outcomes[who.name] = (m[relative.id]["breakdown"]["relationship"], m[relative.id]["match_score"] - m[stranger.id]["match_score"])
    assert outcomes["Prefers Circle"][0] == 100 and outcomes["Prefers Circle"][1] > 0
    assert outcomes["Ignores Circle"][1] <= 0.5  # relationship weight is zeroed, only tiny noise differences remain


def test_critical_verified_nearby_first_aider_beats_uncle_five_km_away(make_user, befriend):
    me = make_user("Nishit")
    uncle = make_user("Uncle", (5, 0), skills=["first_aid"])
    aarav = make_user("Aarav Mehta", (0.5, 0), skills=["first_aid"], certs=["first_aid_cert"], verified=True)
    befriend(me, uncle, "uncle", priority=1)
    r = request(me, "Nexa, I fell off my bike and my arm is bleeding")
    assert r["urgency"] == "critical"
    m = ranking(me, r["id"])
    assert m[0]["helper"]["id"] == aarav.id
    assert m[0]["eta_minutes"] < m[1]["eta_minutes"]
    assert any("Certified in first aid" in x for x in m[0]["reasons"])


def test_critical_medical_excludes_helpers_with_no_first_aid(make_user):
    me = make_user("Nishit")
    strong, none = make_user("Strong Mover", (0.3, 0), skills=["physical_assistance"]), make_user("First Aider", (2, 0), skills=["first_aid"])
    ids = order(me, request(me, "I fell and I'm bleeding, there is a lot of blood")["id"])
    assert ids == [none.id]


def test_urgency_tightens_eta_scoring(make_user):
    me, h = make_user("Nishit"), make_user("Helper", (6, 0), skills=["first_aid"])
    normal = request(me, "I need someone to help me move a cupboard", overrides={"category": "medical_assistance", "skills_required": ["first_aid"]})
    urgent_req = request(me, "urgent: I need someone to help me move a cupboard asap", overrides={"category": "medical_assistance", "skills_required": ["first_aid"]})
    assert urgent_req["urgency"] == "urgent" and normal["urgency"] == "normal"
    n = ranking(me, normal["id"])[0]["breakdown"]["distance"]
    u = ranking(me, urgent_req["id"])[0]["breakdown"]["distance"]
    assert u < n  # the same distance counts for less when time is tighter


def test_blocked_and_declined_never_matched(make_user, befriend):
    me = make_user("Nishit")
    blocked, declined, ok = make_user("Blocked", (0.3, 0)), make_user("Declined", (0.4, 0)), make_user("Fine", (0.5, 0))
    edge = befriend(me, blocked, "friend")
    me.post(f"/api/relationships/{edge}/block")
    r = request(me)
    declined.post(f"/api/matching/{r['id']}/reject")
    assert order(me, r["id"]) == [ok.id]


def test_requester_can_handpick_helper_from_list(make_user):
    me, a, b = make_user("Nishit"), make_user("A One", (0.3, 0)), make_user("B Two", (0.4, 0))
    r = request(me, "I need someone to help me move a cupboard", overrides={"num_helpers": 1})
    # batch size is 3 so both are already asked; pick one who was never asked by widening with a far helper
    far = make_user("Far Pick", (9, 0))
    assert me.post(f"/api/matching/{r['id']}/invite/{far.id}").status_code == 200
    assert me.post(f"/api/matching/{r['id']}/invite/{far.id}").status_code == 409
    assert a.post(f"/api/matching/{r['id']}/invite/{far.id}").status_code == 404  # not their request
    assert len(far.get("/api/requests?scope=invited").json()) == 1


def test_matching_endpoints_owner_only(make_user):
    me, other = make_user("Nishit"), make_user("Nosy", (0.3, 0))
    r = request(me)
    assert other.get(f"/api/matching/{r['id']}").status_code == 404
    assert other.post("/api/matching/find", {"request_id": r["id"]}).status_code == 404
    assert me.post("/api/matching/find", {"request_id": r["id"], "limit": 100}).status_code == 422
