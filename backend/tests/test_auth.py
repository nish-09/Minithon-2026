def test_register_login_me_logout(client):
    r = client.post("/api/auth/register", json={"name": "Asha Rao", "email": "Asha@Example.com", "password": "supersecret1", "phone": "+91 99999 11111"})
    assert r.status_code == 201
    token = r.json()["token"]
    assert r.json()["user"]["email"] == "asha@example.com"  # normalised
    assert "password" not in r.text and "password_hash" not in r.text
    assert r.json()["user"]["credits"] == 20  # starting Help Credits

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["name"] == "Asha Rao"

    login = client.post("/api/auth/login", json={"email": "asha@example.com", "password": "supersecret1"})
    assert login.status_code == 200
    t2 = login.json()["token"]

    assert client.post("/api/auth/logout", headers={"Authorization": f"Bearer {t2}"}).status_code == 204
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {t2}"}).status_code == 401  # revoked
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200  # other session unaffected


def test_duplicate_email_and_phone(client):
    body = {"name": "A B", "email": "dup@example.com", "password": "password123", "phone": "+91 98888 77777"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json={**body, "phone": None}).status_code == 409
    assert client.post("/api/auth/register", json={**body, "email": "other@example.com"}).status_code == 409


def test_invalid_credentials_generic_message(client):
    client.post("/api/auth/register", json={"name": "A B", "email": "a@example.com", "password": "password123"})
    wrong_pw = client.post("/api/auth/login", json={"email": "a@example.com", "password": "nope-nope-1"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-1"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()  # no account enumeration


def test_login_rate_limit(client):
    client.post("/api/auth/register", json={"name": "A B", "email": "rl@example.com", "password": "password123"})
    for _ in range(8):
        assert client.post("/api/auth/login", json={"email": "rl@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "rl@example.com", "password": "password123"}).status_code == 429


def test_registration_validation(client):
    bad = [
        {"name": "A", "email": "a@example.com", "password": "password123"},  # name too short
        {"name": "Ab", "email": "not-an-email", "password": "password123"},
        {"name": "Ab", "email": "b@example.com", "password": "short"},
        {"name": "Ab", "email": "c@example.com", "password": "password123", "phone": "abc"},
        {"name": "Ab", "email": "d@example.com", "password": "password123", "role": "admin"},  # unknown field rejected
    ]
    for body in bad:
        r = client.post("/api/auth/register", json=body)
        assert r.status_code == 422, body
        assert r.json()["detail"] == "Validation failed"


def test_protected_routes_need_auth(client):
    for path in ("/api/auth/me", "/api/requests", "/api/relationships", "/api/trusted-circle", "/api/credits", "/api/notifications"):
        assert client.get(path).status_code == 401, path
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_health_and_reference_public(client):
    assert client.get("/api/health").json()["status"] == "ok"
    ref = client.get("/api/reference").json()
    assert {"medical_assistance", "household_assistance"} <= {c["slug"] for c in ref["categories"]}
    assert "cousin" in {r["slug"] for r in ref["relationship_types"]}
