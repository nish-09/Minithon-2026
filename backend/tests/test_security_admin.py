from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import get_settings
from app.main import app
from app.models import User
from tests.conftest import SessionLocal, km

PUBLIC = {("GET", "/api/health"), ("GET", "/api/reference"), ("POST", "/api/auth/register"), ("POST", "/api/auth/login")}


def all_routes():
    out = []
    for path, methods in app.openapi()["paths"].items():
        for m in methods:
            out.append((m.upper(), path))
    return out


def fill(path):
    import re
    return re.sub(r"\{[^}]+\}", "1", path)


# ---------------- authentication & authorization on EVERY route ----------------
@pytest.mark.parametrize("method,path", [r for r in all_routes() if r not in PUBLIC])
def test_every_non_public_route_requires_authentication(client, method, path):
    r = client.request(method, fill(path), json={} if method in ("POST", "PUT", "PATCH") else None)
    assert r.status_code == 401, f"{method} {path} returned {r.status_code}"


@pytest.mark.parametrize("method,path", [r for r in all_routes() if r[1].startswith("/api/admin")])
def test_every_admin_route_rejects_normal_users(make_user, method, path):
    u = make_user("Normal User")
    r = u.client.request(method, fill(path), headers=u.h, json={} if method in ("POST", "PUT", "PATCH") else None)
    assert r.status_code == 403, f"{method} {path} returned {r.status_code}"


def test_tampered_expired_and_foreign_tokens_rejected(client, make_user):
    u = make_user("Victim Person")
    s = get_settings()
    forged = jwt.encode({"sub": str(u.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1), "jti": "x"}, "wrong-secret-wrong-secret-wrong-1234", algorithm="HS256")
    expired = jwt.encode({"sub": str(u.id), "exp": datetime.now(timezone.utc) - timedelta(seconds=5), "jti": "y"}, s.jwt_secret, algorithm="HS256")
    none_alg = jwt.encode({"sub": str(u.id), "jti": "z"}, None, algorithm="none")
    for tok in (forged, expired, none_alg, u.token[:-3] + "abc", ""):
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_deactivated_user_loses_access_immediately(make_user):
    admin, u = make_user("Admin", role="admin", available=False), make_user("Bad Actor")
    assert u.get("/api/auth/me").status_code == 200
    assert admin.patch(f"/api/admin/users/{u.id}/moderate", {"is_active": False}).status_code == 200
    assert u.get("/api/auth/me").status_code == 401
    assert u.client.post("/api/auth/login", json={"email": u.email, "password": "password123"}).status_code == 401
    assert admin.patch(f"/api/admin/users/{admin.id}/moderate", {"is_active": False}).status_code == 400  # cannot lock yourself out


def test_cannot_escalate_role_via_profile_or_register(make_user, client):
    u = make_user("Sneaky")
    assert u.patch("/api/users/me", {"role": "admin"}).status_code == 422
    assert client.post("/api/auth/register", json={"name": "Sneaky Two", "email": "s2@nexa-test.app", "password": "password123", "role": "admin"}).status_code == 422
    assert u.get("/api/admin/dashboard").status_code == 403


# ---------------- user data isolation ----------------
def test_public_profile_leaks_no_private_fields(make_user):
    a, b = make_user("Alice Wonder"), make_user("Bob Builder")
    for url in (f"/api/users/{a.id}", f"/api/users/{a.id}/trust", f"/api/users/{a.id}/trust/explanation"):
        blob = b.get(url).text
        assert a.email not in blob and "password" not in blob and "phone" not in blob and '"lat"' not in blob, url
    assert b.get("/api/users/99999").status_code == 404


def test_notifications_and_credits_are_private(make_user):
    a, b = make_user("Alice Wonder"), make_user("Bob Builder")
    a.post("/api/credits/donate", {"to_user_id": b.id, "amount": 5})
    assert any("donated" in n["title"] for n in b.get("/api/notifications").json()["items"])
    assert all("donated" not in n["title"] for n in a.get("/api/notifications").json()["items"])
    assert a.get("/api/credits").json()["balance"] == 15 and b.get("/api/credits").json()["balance"] == 25


def test_other_users_requests_are_not_readable_or_listable(make_user):
    a, b = make_user("Alice Wonder"), make_user("Bob Builder", (40, 0))
    lat, lng = km(0, 0)
    rid = a.post("/api/requests", {"text": "I need help moving a cupboard", "lat": lat, "lng": lng}).json()["id"]
    assert b.get(f"/api/requests/{rid}").status_code == 404
    assert b.get(f"/api/requests/{rid}/messages").status_code == 404
    assert b.get("/api/requests?scope=mine").json() == []
    assert b.get("/api/requests?scope=all").status_code == 403
    assert b.post(f"/api/requests/{rid}/review", {"helper_id": a.id, "rating": 1}).status_code == 404


def test_cannot_rate_unless_requester_and_helper_actually_helped(make_user):
    a, h, other = make_user("Alice Wonder"), make_user("Helper Hal", (0.5, 0)), make_user("Other Person", (0.6, 0))
    lat, lng = km(0, 0)
    rid = a.post("/api/requests", {"text": "I need help moving a cupboard", "lat": lat, "lng": lng}).json()["id"]
    assert a.post(f"/api/requests/{rid}/review", {"helper_id": h.id, "rating": 5}).status_code == 409  # not completed yet
    h.post(f"/api/matching/{rid}/accept")
    a.post(f"/api/requests/{rid}/complete")
    assert a.post(f"/api/requests/{rid}/review", {"helper_id": other.id, "rating": 5}).status_code == 400  # did not help
    assert h.post(f"/api/requests/{rid}/review", {"helper_id": a.id, "rating": 5}).status_code == 403  # helpers cannot rate themselves up
    assert a.post(f"/api/requests/{rid}/review", {"helper_id": h.id, "rating": 6}).status_code == 422


# ---------------- location privacy ----------------
def test_location_sharing_off_blocks_location_and_hides_from_maps(make_user):
    me, h = make_user("Nishit Sharma"), make_user("Private Helper", (0.5, 0), skills=["first_aid"])
    assert any(x["id"] == h.id for x in me.get("/api/helpers/nearby?radius_km=5").json())
    assert h.patch("/api/users/me", {"location_sharing": "off"}).status_code == 200
    assert h.put("/api/users/me/location", {"lat": 12.9, "lng": 77.6}).status_code == 403
    assert all(x["id"] != h.id for x in me.get("/api/helpers/nearby?radius_km=5").json())
    assert h.delete("/api/users/me/location").status_code == 204
    me_out = h.get("/api/auth/me").json()
    assert me_out["lat"] is None and me_out["is_available"] is False


def test_helper_map_markers_are_anonymised(make_user):
    me, h = make_user("Nishit Sharma"), make_user("Exact Location Helper", (0.5, 0))
    marker = me.get("/api/helpers/nearby?radius_km=5").json()[0]
    assert set(marker) == {"id", "lat", "lng", "distance_km", "trust_score", "skills", "verified"}
    with SessionLocal() as db:
        u = db.get(User, h.id)
        assert marker["lat"] == round(u.lat, 2) != u.lat  # ~1 km precision only


def test_requester_sees_helper_location_only_while_assigned(make_user):
    me, h = make_user("Nishit Sharma"), make_user("Helper Hal", (0.5, 0))
    lat, lng = km(0, 0)
    rid = me.post("/api/requests", {"text": "I need help moving a cupboard", "lat": lat, "lng": lng}).json()["id"]
    assert me.get(f"/api/requests/{rid}").json()["assignments"] == []
    h.post(f"/api/matching/{rid}/accept")
    a = me.get(f"/api/requests/{rid}").json()["assignments"][0]
    assert a["lat"] is not None
    h.patch("/api/users/me", {"location_sharing": "off"})
    assert me.get(f"/api/requests/{rid}").json()["assignments"][0]["lat"] is None


# ---------------- input validation / injection ----------------
def test_injection_strings_are_inert(make_user):
    me = make_user("Nishit Sharma")
    lat, lng = km(0, 0)
    evil = "'; DROP TABLE users; -- <script>alert(1)</script>"
    r = me.post("/api/requests", {"text": evil + " move cupboard", "lat": lat, "lng": lng})
    assert r.status_code == 201
    assert me.get("/api/auth/me").status_code == 200
    assert me.get(f"/api/admin/users?q={evil}").status_code == 403
    assert me.get("/api/directory?q=%27%3B%20DROP%20TABLE").status_code == 200
    assert me.patch("/api/users/me", {"bio": evil}).json()["bio"] == evil  # stored as data, rendered escaped by the UI


def test_wrong_types_and_oversized_bodies_rejected(make_user):
    me = make_user("Nishit Sharma")
    assert me.post("/api/requests", {"text": 123, "lat": "x"}).status_code == 422
    assert me.client.post("/api/requests", headers={**me.h, "Content-Type": "application/json"}, content=b"{not json").status_code == 422
    assert me.patch("/api/users/me", {"skills": [{"slug": "nope"}]}).status_code == 422
    assert me.patch("/api/users/me", {"availability_schedule": {"funday": ["09:00-10:00"]}}).status_code == 422
    assert me.patch("/api/users/me", {"availability_schedule": {"mon": ["9am-5pm"]}}).status_code == 422
    assert me.patch("/api/users/me", {"avatar_url": "javascript:alert(1)"}).status_code == 422
    assert me.patch("/api/users/me", {"bio": "x" * 1001}).status_code == 422
    assert me.get("/api/requests?scope=bogus").status_code == 422
    assert me.get("/api/requests/radar?radius_km=9999&lat=1&lng=1").status_code == 422
    assert me.get("/api/directory?lat=500").status_code == 422


def test_security_headers_and_no_stack_traces(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"
    assert "*" not in r.headers.get("access-control-allow-origin", "")
    bad = client.get("/api/auth/me", headers={"Authorization": "Bearer x"})
    assert "Traceback" not in bad.text


def test_cors_only_allows_configured_origin(client):
    ok = client.options("/api/auth/login", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    bad = client.options("/api/auth/login", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers


def test_reports_validation(make_user):
    a, b = make_user("Alice Wonder"), make_user("Bob Builder")
    assert a.post("/api/reports", {"reason": "spam"}).status_code == 422  # needs a target
    assert a.post("/api/reports", {"target_user_id": a.id, "reason": "spam"}).status_code == 400
    assert a.post("/api/reports", {"target_user_id": b.id, "reason": "made-up"}).status_code == 422
    assert a.post("/api/reports", {"target_user_id": 9999, "reason": "spam"}).status_code == 404
    assert a.post("/api/reports", {"target_user_id": b.id, "reason": "harassment", "details": "rude"}).status_code == 201


# ---------------- admin features ----------------
def test_dashboard_metrics_reflect_reality(make_user):
    admin = make_user("Admin", role="admin", available=False)
    me, h = make_user("Alice Wonder"), make_user("Helper Hal", (0.5, 0))
    lat, lng = km(0, 0)
    rid = me.post("/api/requests", {"text": "I need help moving a cupboard", "lat": lat, "lng": lng}).json()["id"]
    me.post("/api/requests", {"text": "urgent, my basement is flooding right now", "lat": lat, "lng": lng})
    d = admin.get("/api/admin/dashboard").json()
    assert d["active_requests"] == 2 and d["urgent_requests"] == 1 and d["helpers_online"] == 2 and d["critical_incidents"] == 0
    h.post(f"/api/matching/{rid}/accept")
    me.post(f"/api/requests/{rid}/complete")
    d = admin.get("/api/admin/dashboard").json()
    assert d["completed_today"] == 1 and d["active_requests"] == 1 and d["avg_response_seconds"] is not None
    me.post("/api/incidents", {"text": "I am bleeding badly", "lat": lat, "lng": lng})
    assert admin.get("/api/admin/dashboard").json()["critical_incidents"] == 1


def test_analytics_heatmap_gaps_and_response_times(make_user):
    admin = make_user("Admin", role="admin", available=False)
    me, h = make_user("Alice Wonder"), make_user("Helper Hal", (0.5, 0), skills=["physical_assistance"])
    lat, lng = km(0, 0)
    for text in ("move a cupboard for me", "I need a plumber, my tap is leaking", "my pipe is leaking badly, plumber please"):
        me.post("/api/requests", {"text": text, "lat": lat, "lng": lng})
    a = admin.get("/api/admin/analytics").json()
    cats = {c["category"]: c["count"] for c in a["categories"]}
    assert cats == {"household_assistance": 1, "repair": 2} and a["total_requests"] == 3
    assert a["heatmap"] and a["heatmap"][0]["weight"] == 1.0 and a["heatmap"][0]["count"] >= 3
    assert any(g["category"] == "repair" for g in a["resource_gaps"])  # demand with no plumbers available
    assert a["volunteer_availability"].get("household_assistance") == 1
    assert "lat" in a["heatmap"][0] and "user" not in str(a)  # aggregated only
    assert admin.get("/api/admin/analytics?days=0").status_code == 422


def test_admin_verification_changes_trust_and_certs(make_user):
    admin, u = make_user("Admin", role="admin", available=False), make_user("Claims Cert", skills=["first_aid"], certs=["first_aid_cert"])
    before = u.get(f"/api/users/{u.id}/trust").json()
    assert before["certifications"] == []
    assert admin.post(f"/api/admin/users/{u.id}/verify", {"kind": "identity"}).status_code == 200
    assert admin.post(f"/api/admin/users/{u.id}/certifications", {"certification": "first_aid_cert"}).status_code == 200
    after = u.get(f"/api/users/{u.id}/trust").json()
    assert after["score"] > before["score"] and after["certifications"] == ["First Aid Certificate"] and "identity_verified" in after["badges"]
    assert admin.post(f"/api/admin/users/{u.id}/certifications", {"certification": "cpr_cert"}).status_code == 404  # never claimed
    assert admin.post(f"/api/admin/users/{u.id}/verify", {"kind": "passport"}).status_code == 422


def test_admin_trust_review_flags_anomalies(make_user):
    from tests.test_trust import events
    admin, flaky, fine = make_user("Admin", role="admin", available=False), make_user("Flaky Fred"), make_user("Fine Fran")
    events(flaky.id, notified=10, responded=8, accepted=8, cancelled=5, no_show=2)
    events(fine.id, notified=10, responded=9, accepted=9)
    flagged = admin.get("/api/admin/trust-review").json()
    assert [f["user_id"] for f in flagged] == [flaky.id]
    assert any("No-show" in r for r in flagged[0]["reasons"])


def test_admin_moderation_of_requests_and_users_list(make_user):
    admin, me, h = make_user("Admin", role="admin", available=False), make_user("Alice Wonder"), make_user("Helper Hal", (0.5, 0))
    lat, lng = km(0, 0)
    rid = me.post("/api/requests", {"text": "I need help moving a cupboard", "lat": lat, "lng": lng}).json()["id"]
    assert admin.get("/api/admin/requests?status=HELPERS_NOTIFIED").json()[0]["id"] == rid
    assert admin.get(f"/api/requests/{rid}").json()["viewer_role"] == "admin"
    assert admin.post(f"/api/admin/requests/{rid}/cancel").json()["status"] == "CANCELLED"
    users = admin.get("/api/admin/users?q=helper").json()
    assert [u["name"] for u in users] == ["Helper Hal"] and "password" not in str(users)
    assert admin.get("/api/admin/users?limit=1000").status_code == 422


def test_admin_reports_queue(make_user):
    admin, a, b = make_user("Admin", role="admin", available=False), make_user("Alice Wonder"), make_user("Bob Builder")
    a.post("/api/reports", {"target_user_id": b.id, "reason": "fraud", "details": "asked for money"})
    assert any(n["kind"] == "user_report" for n in admin.get("/api/notifications").json()["items"])
    q = admin.get("/api/admin/reports").json()
    assert len(q) == 1 and q[0]["reason"] == "fraud"
    admin.post(f"/api/admin/reports/{q[0]['id']}/resolve", {"status": "DISMISSED"})
    assert admin.get("/api/admin/reports").json() == []


def test_admin_directory_management_and_public_listing(make_user):
    admin, u = make_user("Admin", role="admin", available=False), make_user("Regular Rita")
    body = {"name": "Night Pharmacy", "category": "pharmacy", "phone": "+91 80 1111 2222", "lat": 12.93, "lng": 77.62, "is_24h": True}
    eid = admin.post("/api/admin/directory", body).json()["id"]
    admin.post("/api/admin/directory", {"name": "Police", "category": "emergency", "phone": "100", "is_24h": True})
    listing = u.get("/api/directory").json()
    assert listing[0]["category"] == "emergency"  # emergency numbers always first and always included
    assert u.get("/api/directory?category=pharmacy&q=night").json()[0]["name"] == "Night Pharmacy"
    assert admin.put(f"/api/admin/directory/{eid}", {**body, "name": "Day Pharmacy"}).status_code == 200
    assert u.post("/api/admin/directory", body).status_code == 403
    assert admin.post("/api/admin/directory", {**body, "category": "casino"}).status_code == 422
    assert admin.delete(f"/api/admin/directory/{eid}").status_code == 204
    assert admin.delete(f"/api/admin/directory/{eid}").status_code == 404


def test_notification_read_flow(make_user):
    me = make_user("Alice Wonder")
    lat, lng = km(0, 0)
    me.post("/api/requests", {"text": "I need help moving a cupboard", "lat": lat, "lng": lng})
    assert me.get("/api/notifications").json()["unread"] >= 1
    assert me.post("/api/notifications/read").status_code == 204
    assert me.get("/api/notifications").json()["unread"] == 0
    assert me.get("/api/notifications?limit=0").status_code == 422
