import itertools
import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="nexa-test-")
# Tests DROP ALL TABLES, so they only ever use SQLite or an explicitly opted-in test database.
os.environ["NEXA_DATABASE_URL"] = os.environ.get("NEXA_TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db"
os.environ["NEXA_BCRYPT_ROUNDS"] = "4"
os.environ["NEXA_SWEEPER_INTERVAL_S"] = "0"  # tests drive timeouts explicitly
os.environ["NEXA_ANTHROPIC_API_KEY"] = ""
os.environ["NEXA_JWT_SECRET"] = "test-secret-test-secret-test-secret-123"

from fastapi.testclient import TestClient  # noqa: E402

from app import bootstrap  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.routers import auth as auth_router  # noqa: E402

HOME = (12.9352, 77.6245)
_counter = itertools.count(1)


def km(dx: float = 0.0, dy: float = 0.0) -> tuple[float, float]:
    import math
    return HOME[0] + dy / 111.0, HOME[1] + dx / (111.0 * math.cos(math.radians(HOME[0])))


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        bootstrap.ensure_reference_data(db)
    auth_router._FAILS.clear()
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


class Person:
    def __init__(self, client, id, token, name, email):
        self.client, self.id, self.token, self.name, self.email = client, id, token, name, email

    @property
    def h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, url, **kw):
        return self.client.get(url, headers=self.h, **kw)

    def post(self, url, json=None, **kw):
        return self.client.post(url, headers=self.h, json=json if json is not None else {}, **kw)

    def patch(self, url, json):
        return self.client.patch(url, headers=self.h, json=json)

    def put(self, url, json):
        return self.client.put(url, headers=self.h, json=json)

    def delete(self, url):
        return self.client.delete(url, headers=self.h)


@pytest.fixture()
def make_user(client):
    def _make(name="Test User", where=(0, 0), available=True, skills=(), certs=(), verified=False, role="user", password="password123", circle_pref=True):
        name = name if len(name) >= 2 else f"{name} X"
        n = next(_counter)
        email = f"user{n}@nexa-test.app"
        r = client.post("/api/auth/register", json={"name": name, "email": email, "password": password})
        assert r.status_code == 201, r.text
        p = Person(client, r.json()["user"]["id"], r.json()["token"], name, email)
        lat, lng = km(*where)
        assert p.put("/api/users/me/location", {"lat": lat, "lng": lng}).status_code == 200
        body = {"is_available": available, "prefer_trusted_circle": circle_pref}
        if skills:
            body["skills"] = [{"slug": s, "years_experience": 3} for s in skills]
        if certs:
            body["certifications"] = list(certs)
        assert p.patch("/api/users/me", body).status_code == 200
        with SessionLocal() as db:
            u = db.get(User, p.id)
            if verified:
                u.identity_verified = u.phone_verified = u.email_verified = True
                for uc in u.certifications:
                    uc.verified = True
            if role == "admin":
                u.role = "admin"
            db.commit()
        if verified:
            with SessionLocal() as db:
                from app.services import trust
                trust.refresh_trust(db, p.id)
                db.commit()
        return p

    return _make


@pytest.fixture()
def befriend(client):
    """befriend(a, b, 'cousin', **settings_on_a_edge): create + accept a relationship, return a's edge id."""
    def _do(a: Person, b: Person, rel_type="friend", accept=True, **edge):
        r = a.post("/api/relationships", {"user_id": b.id, "relationship_type": rel_type})
        assert r.status_code == 201, r.text
        a_edge = r.json()["id"]
        if accept:
            b_edge = next(e["id"] for e in b.get("/api/relationships").json() if e["user"]["id"] == a.id)
            assert b.post(f"/api/relationships/{b_edge}/accept").status_code == 200
        if edge:
            assert a.patch(f"/api/relationships/{a_edge}", edge).status_code == 200
        return a_edge
    return _do


@pytest.fixture()
def db():
    with SessionLocal() as s:
        yield s
