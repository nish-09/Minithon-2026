from app.models import Assignment, HelpRequest, Review, utcnow
from app.services import trust as T
from tests.conftest import SessionLocal


def add_history(helper_id, requester_id, n=5, rating=5, cat="household_assistance"):
    with SessionLocal() as db:
        for _ in range(n):
            r = HelpRequest(requester_id=requester_id, raw_text="old", title="old", category=cat, urgency="normal", status="RATED",
                            lat=12.9, lng=77.6, expires_at=utcnow(), completed_at=utcnow())
            db.add(r); db.flush()
            db.add(Assignment(request_id=r.id, helper_id=helper_id, status="DONE"))
            db.add(Review(request_id=r.id, reviewer_id=requester_id, reviewee_id=helper_id, rating=rating, category=cat))
            T.record_event(db, helper_id, "completed", category=cat, request_id=r.id, counterparty_id=requester_id)
        db.commit()


def events(uid, **counts):
    with SessionLocal() as db:
        for kind, n in counts.items():
            for _ in range(n):
                T.record_event(db, uid, kind, category="household_assistance", value=60.0 if kind == "responded" else None)
        T.refresh_trust(db, uid)
        db.commit()


def card(p, uid=None):
    return p.get(f"/api/users/{uid or p.id}/trust").json()


def test_new_user_no_ratings_is_provisional_not_punished(make_user):
    new = make_user("Newbie")
    c = card(new)
    assert 20 <= c["score"] <= 60
    assert c["confidence"] < 0.3
    assert any(f["key"] == "confidence" for f in c["factors"])
    assert any(f["label"] == "No reviews yet" for f in c["factors"])
    assert c["stats"]["rating"] is None and c["stats"]["review_count"] == 0


def test_few_interactions_shrinks_toward_prior(make_user):
    a, b, client_user = make_user("Few Helps"), make_user("Many Helps"), make_user("Client")
    add_history(a.id, client_user.id, n=1, rating=5)
    add_history(b.id, client_user.id, n=15, rating=5)
    with SessionLocal() as db:
        T.refresh_trust(db, a.id); T.refresh_trust(db, b.id); db.commit()
    ca, cb = card(a), card(b)
    assert cb["score"] > ca["score"]
    assert ca["confidence"] < cb["confidence"]
    # one 5-star review should not be treated like fifteen
    rep_a = next(c for c in ca["components"] if c["key"] == "community_reputation")["score"]
    rep_b = next(c for c in cb["components"] if c["key"] == "community_reputation")["score"]
    assert rep_a < rep_b and rep_a < 75


def test_high_cancellation_rate_lowers_score(make_user):
    good, flaky = make_user("Reliable"), make_user("Flaky")
    events(good.id, notified=10, responded=10, accepted=10)
    events(flaky.id, notified=10, responded=10, accepted=10, cancelled=6, no_show=2)
    g, f = card(good), card(flaky)
    assert f["score"] < g["score"] - 10
    assert f["stats"]["cancellation_rate"] == 60 and f["stats"]["no_show_rate"] == 20
    assert any(x["key"] == "cancel" and x["impact"] == "negative" for x in f["factors"])
    assert any(x["key"] == "noshow" for x in f["factors"])


def test_high_response_rate_raises_score(make_user):
    fast, ghost = make_user("Responsive"), make_user("Ghost")
    events(fast.id, notified=20, responded=19, accepted=15)
    events(ghost.id, notified=20, responded=2, accepted=1)
    assert card(fast)["score"] > card(ghost)["score"]
    assert card(fast)["stats"]["response_rate"] == 95
    assert card(ghost)["stats"]["response_rate"] == 10


def test_multiple_verified_certifications_raise_credentials_and_category_trust(make_user):
    plain = make_user("No Certs", skills=["first_aid"], verified=True)
    pro = make_user("Paramedic", skills=["first_aid", "cpr"], certs=["first_aid_cert", "cpr_cert"], verified=True)
    cp, cc = card(plain), card(pro)
    comp = lambda c, k: next(x for x in c["components"] if x["key"] == k)["score"]
    assert comp(cc, "credentials") > comp(cp, "credentials")
    assert cc["score"] > cp["score"]
    cat = {x["category"]: x["score"] for x in cc["categories"]}
    assert "medical_assistance" in cat and cat["medical_assistance"] > {x["category"]: x["score"] for x in cp["categories"]}["medical_assistance"]
    assert "First Aid Certificate" in cc["certifications"]
    assert "certified" in cc["badges"]


def test_unverified_certificate_claim_does_not_count_as_verified(make_user):
    claim = make_user("Claimer", skills=["first_aid"], certs=["first_aid_cert"], verified=False)
    assert card(claim)["certifications"] == []  # only admin-verified certs are displayed
    assert "certified" not in card(claim)["badges"]


def test_negative_reports_reduce_trust_only_when_upheld(make_user):
    admin, victim, reporter = make_user("Admin", role="admin", available=False), make_user("Reported"), make_user("Reporter")
    add_history(victim.id, reporter.id, n=6, rating=5)
    with SessionLocal() as db:
        T.refresh_trust(db, victim.id); db.commit()
    before = card(victim)["score"]
    rid = reporter.post("/api/reports", {"target_user_id": victim.id, "reason": "unsafe", "details": "made me uncomfortable"}).json()["id"]
    assert card(victim)["score"] == before  # an open report alone changes nothing
    assert admin.post(f"/api/admin/reports/{rid}/resolve", {"status": "UPHELD"}).status_code == 200
    after = card(victim)
    assert after["score"] < before - 10
    assert any(f["key"] == "reports" and f["impact"] == "negative" for f in after["factors"])
    rid2 = reporter.post("/api/reports", {"target_user_id": victim.id, "reason": "spam"}).json()["id"]
    n = card(victim)["score"]
    admin.post(f"/api/admin/reports/{rid2}/resolve", {"status": "DISMISSED"})
    assert card(victim)["score"] == n  # dismissed reports do not count
    assert admin.post(f"/api/admin/reports/{rid}/resolve", {"status": "UPHELD"}).status_code == 409


def test_explanation_is_complete_and_not_a_black_box(make_user):
    h, c = make_user("Explained", skills=["first_aid"], certs=["first_aid_cert"], verified=True), make_user("Client")
    add_history(h.id, c.id, n=8, rating=5, cat="medical_assistance")
    with SessionLocal() as db:
        T.refresh_trust(db, h.id); db.commit()
    e = h.get(f"/api/users/{h.id}/trust/explanation").json()
    assert e["factors"] and all({"label", "impact", "detail"} <= set(f) for f in e["factors"])
    assert {x["key"] for x in e["components"]} == set(T.COMPONENT_WEIGHTS)
    assert abs(sum(x["weight"] for x in e["components"]) - 1.0) < 1e-9
    assert "not guarantees" in e["disclaimer"]
    # the overall score is reproducible from the published components and weights (minus penalties, none here)
    recomputed = sum(x["score"] * x["weight"] for x in e["components"])
    assert abs(recomputed - e["score"]) < 0.2
    assert e["model_version"].startswith("heuristic")


def test_contextual_trust_is_not_inherited_from_overall(make_user):
    h, c = make_user("First Aid Star", skills=["first_aid", "plumbing"], certs=["first_aid_cert"], verified=True), make_user("Client")
    add_history(h.id, c.id, n=10, rating=5, cat="medical_assistance")
    with SessionLocal() as db:
        T.refresh_trust(db, h.id); db.commit()
    cats = {x["category"]: x["score"] for x in card(h)["categories"]}
    overall = card(h)["score"]
    assert cats["medical_assistance"] > cats["repair"] + 15  # proven + certified vs merely claimed
    assert cats["repair"] < overall  # declared plumbing skill alone does not earn overall-level trust


def test_model_is_swappable(make_user):
    class Fixed:
        version = "fixed-test"
        def score(self, f, categories):
            return T.TrustResult(0, 77.0, 1.0, {k: 77.0 for k in T.COMPONENT_WEIGHTS}, {}, [], [], self.version, {})
    orig = T.get_model()
    try:
        T.set_model(Fixed())
        u = make_user("Swapped")
        c = card(u)
        assert c["score"] == 77.0 and c["model_version"] == "fixed-test"
    finally:
        T.set_model(orig)


def test_trust_card_contains_no_private_data(make_user):
    u = make_user("Private Person")
    blob = str(card(u))
    assert u.email not in blob and "lat" not in card(u) and "phone" not in blob
