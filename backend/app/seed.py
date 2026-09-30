"""Demo data. `python -m app.seed [--reset]`

Everything here goes through the real tables and the real Trust Engine: there are no hard-coded trust
scores. Histories are generated as completed requests + reviews + behaviour events, and the engine
computes the scores from them. Replace with real data/services in production.
Demo password for every seeded account: nexa1234
"""
import math
import random
import sys
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import bootstrap
from .db import Base, SessionLocal, engine
from .models import (
    Assignment, Certification, CommunityEvent, DirectoryEntry, HelpRequest, Profile, RelationshipPreference, RelStatus, Relationship,
    Review, Role, Skill, TrustEvent, User, UserCertification, UserSkill, utcnow,
)
from .security import hash_password
from .services import credits as credits_svc
from .services import trust as trust_svc

PASSWORD = "nexa1234"
HOME = (12.9352, 77.6245)  # Koramangala, Bengaluru (sample area)


def offset(dx_km: float, dy_km: float) -> tuple[float, float]:
    lat = HOME[0] + dy_km / 111.0
    lng = HOME[1] + dx_km / (111.0 * math.cos(math.radians(HOME[0])))
    return round(lat, 5), round(lng, 5)


# key, name, email, phone, (dx, dy) km from home, available, skills[(slug, years)], certs[slug], bio, verified(identity, phone, email), account age days
PEOPLE = [
    ("nishit", "Nishit Sharma", "nishit@nexa-demo.app", "+91 98000 00001", (0, 0), False, [("physical_assistance", 1)], [], "Lives alone near Koramangala.", (True, True, True), 200),
    ("mom", "Anita Sharma", "anita@nexa-demo.app", "+91 98000 00002", (0.85, 0.85), True, [("elder_care", 3)], [], "Nishit's mother.", (True, True, True), 400),
    ("uncle", "Suresh Sharma", "suresh@nexa-demo.app", "+91 98000 00003", (1.0, -1.0), True, [("physical_assistance", 10), ("driving", 20)], [], "Retired, happy to help family.", (True, True, True), 380),
    ("cousin", "Rohan Verma", "rohan@nexa-demo.app", "+91 98000 00004", (-1.3, 1.2), True, [("physical_assistance", 4), ("tech_support", 6)], [], "Software engineer and cousin.", (True, True, True), 300),
    ("kabir", "Kabir Malhotra", "kabir@nexa-demo.app", "+91 98000 00005", (-2.4, -2.4), False, [("carpentry", 5)], [], "Close friend.", (True, True, True), 500),
    ("aarav", "Aarav Mehta", "aarav@nexa-demo.app", "+91 98000 00006", (0.0, 0.5), True, [("first_aid", 6), ("cpr", 4)], ["first_aid_cert", "cpr_cert"], "Paramedic student. Happy to help neighbours.", (True, True, True), 700),
    ("rahul", "Rahul Shah", "rahul@nexa-demo.app", "+91 98000 00007", (0.7, 0.0), True, [("physical_assistance", 5), ("carpentry", 3)], [], "Moves furniture for a living. Friendly neighbour.", (True, True, True), 500),
    ("dev", "Dev Patel", "dev@nexa-demo.app", "+91 98000 00008", (0.0, -0.9), True, [("physical_assistance", 1)], [], "New to NEXA.", (False, True, True), 3),
    ("meera", "Meera Kulkarni", "meera@nexa-demo.app", "+91 98000 00009", (-1.1, 0.0), True, [("physical_assistance", 2)], [], "", (False, True, True), 120),
    ("priya", "Priya Nair", "priya@nexa-demo.app", "+91 98000 00010", (1.2, 0.9), True, [("teaching", 8)], ["teaching_cert"], "Maths and physics tutor.", (True, True, True), 600),
    ("vikram", "Vikram Rao", "vikram@nexa-demo.app", "+91 98000 00011", (1.8, -0.9), True, [("electrical", 12)], ["electrician_license"], "Licensed electrician.", (True, True, True), 650),
    ("sneha", "Sneha Iyer", "sneha@nexa-demo.app", "+91 98000 00012", (-2.0, 1.0), True, [("pet_care", 5)], ["vet_assistant_cert"], "Vet assistant. Dog lover.", (True, True, True), 450),
    ("arjun", "Arjun Singh", "arjun@nexa-demo.app", "+91 98000 00013", (2.6, 2.4), True, [("physical_assistance", 6)], [], "Gym trainer.", (True, True, True), 250),
    ("admin", "NEXA Admin", "admin@nexa-demo.app", "+91 98000 00099", (0.3, 0.2), False, [], [], "Platform administrator.", (True, True, True), 900),
]

# helper key -> (completed helps, avg rating target, category, responded/notified, cancels, no_shows, avg response secs)
HISTORY = {
    "aarav": (23, 4.8, "medical_assistance", (46, 50), 0, 0, 55),
    "rahul": (14, 4.6, "household_assistance", (30, 36), 1, 0, 90),
    "uncle": (9, 4.9, "household_assistance", (12, 13), 0, 0, 70),
    "mom": (6, 5.0, "elder_care", (9, 10), 0, 0, 40),
    "cousin": (7, 4.7, "tech_help", (11, 14), 0, 0, 180),
    "priya": (18, 4.9, "tutoring", (25, 28), 0, 0, 120),
    "vikram": (30, 4.7, "repair", (38, 45), 2, 0, 200),
    "sneha": (11, 4.6, "pet_care", (15, 18), 0, 0, 150),
    "arjun": (5, 4.2, "household_assistance", (8, 12), 1, 0, 260),
    "kabir": (4, 4.8, "repair", (6, 7), 0, 0, 100),
    "meera": (6, 3.0, "household_assistance", (8, 20), 6, 2, 700),
}

CIRCLE = [  # (owner, other, owner's label for other, priority, can_receive)
    ("nishit", "mom", "mother", 1, True), ("nishit", "uncle", "uncle", 2, True), ("nishit", "cousin", "cousin", 3, True),
    ("nishit", "kabir", "friend", 4, True),
]

RATING_COMMENTS = {5: "Excellent, arrived quickly and was very kind.", 4: "Helpful and on time.", 3: "Got it done but was late.", 2: "Not great.", 1: "Did not show up properly."}


def _cents(target: float, n: int, rng: random.Random) -> list[int]:
    """n integer ratings 1..5 whose mean is close to target."""
    base = int(target)
    hi = round((target - base) * n)
    ratings = [min(5, base + 1)] * hi + [base] * (n - hi)
    if target < 4 and n > 2:
        ratings[-1] = 2
    rng.shuffle(ratings)
    return [max(1, min(5, r)) for r in ratings]


def seed(db: Session, reset: bool = False) -> None:
    rng = random.Random(42)
    if reset:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    bootstrap.ensure_reference_data(db)
    if db.scalar(select(User.id).where(User.email == "nishit@nexa-demo.app")):
        print("Seed data already present (use --reset to rebuild).")
        return

    skills = {s.slug: s for s in db.scalars(select(Skill))}
    certs = {c.slug: c for c in db.scalars(select(Certification))}
    users: dict[str, User] = {}
    for key, name, email, phone, (dx, dy), avail, sk, cs, bio, (ident, ph, em), age in PEOPLE:
        lat, lng = offset(dx, dy)
        u = User(name=name, email=email, phone=phone, password_hash=hash_password(PASSWORD), role=Role.ADMIN if key == "admin" else Role.USER,
                 identity_verified=ident, phone_verified=ph, email_verified=em, lat=lat, lng=lng, is_available=avail,
                 created_at=utcnow() - timedelta(days=age), location_updated_at=utcnow())
        u.profile = Profile(bio=bio)
        db.add(u)
        db.flush()
        for slug, yrs in sk:
            db.add(UserSkill(user_id=u.id, skill_id=skills[slug].id, years_experience=yrs))
        for c in cs:
            db.add(UserCertification(user_id=u.id, certification_id=certs[c].id, verified=True, issued_at=utcnow() - timedelta(days=200)))
        db.add(RelationshipPreference(user_id=u.id))
        credits_svc.ensure_account(db, u.id)
        users[key] = u
    db.flush()

    # Trusted circle edges (both directions, accepted)
    from .models import RelationshipType
    inverse = {r.slug: r.inverse_slug for r in db.scalars(select(RelationshipType))}
    for owner, other, label, prio, can in CIRCLE:
        a, b = users[owner], users[other]
        db.add(Relationship(user_id=a.id, related_user_id=b.id, relationship_type=label, status=RelStatus.ACCEPTED, initiated_by_id=a.id,
                            priority=prio, can_receive_requests=can, is_trusted=True))
        db.add(Relationship(user_id=b.id, related_user_id=a.id, relationship_type=inverse.get(label) or "other", status=RelStatus.ACCEPTED,
                            initiated_by_id=a.id, priority=2, can_receive_requests=True, is_trusted=True))

    # Realistic histories -> real events -> engine-computed trust
    requesters = [users[k] for k in ("nishit", "priya", "cousin", "vikram", "sneha")]
    now = utcnow()
    for hk, (done, avg, cat, (resp, notif), cancels, no_shows, resp_s) in HISTORY.items():
        h = users[hk]
        ratings = _cents(avg, done, rng)
        for i in range(done):
            client = requesters[i % len(requesters)]
            if client.id == h.id:
                client = users["nishit"]
            when = now - timedelta(days=rng.randint(3, 180), hours=rng.randint(0, 20))
            r = HelpRequest(requester_id=client.id, raw_text=f"Past {cat} request", title=f"Past {cat.replace('_', ' ')} help", description="",
                            category=cat, urgency="normal", skills_required=[], lat=client.lat, lng=client.lng, status="RATED",
                            routing_mode="community", created_at=when, completed_at=when + timedelta(hours=1), filled_slots=1,
                            expires_at=when + timedelta(hours=2), search_radius_km=10)
            db.add(r)
            db.flush()
            db.add(Assignment(request_id=r.id, helper_id=h.id, status="DONE", accepted_at=when, completed_at=r.completed_at, eta_minutes=6))
            db.add(Review(request_id=r.id, reviewer_id=client.id, reviewee_id=h.id, rating=ratings[i], comment=RATING_COMMENTS[ratings[i]],
                          category=cat, created_at=r.completed_at))
            db.add(TrustEvent(user_id=h.id, kind="completed", category=cat, request_id=r.id, counterparty_id=client.id, created_at=r.completed_at))
        for _ in range(notif):
            db.add(TrustEvent(user_id=h.id, kind="notified", category=cat))
        for _ in range(resp):
            db.add(TrustEvent(user_id=h.id, kind="responded", category=cat, value=max(10.0, rng.gauss(resp_s, resp_s * 0.2))))
            db.add(TrustEvent(user_id=h.id, kind="accepted", category=cat))
        for _ in range(cancels):
            db.add(TrustEvent(user_id=h.id, kind="cancelled", category=cat))
        for _ in range(no_shows):
            db.add(TrustEvent(user_id=h.id, kind="no_show", category=cat))
    db.flush()
    for u in users.values():
        trust_svc.refresh_trust(db, u.id)

    # Directory (SAMPLE data: replace with verified local listings)
    def add_dir(name, cat, phone, dx, dy, h24=False, notes="Sample entry - replace with verified local data"):
        lat, lng = offset(dx, dy)
        db.add(DirectoryEntry(name=name, category=cat, phone=phone, lat=lat, lng=lng, is_24h=h24, notes=notes))

    for name, phone, note in [("Unified Emergency Response (India)", "112", "All emergencies"), ("Police", "100", ""), ("Fire", "101", ""),
                              ("Ambulance", "108", ""), ("Women Helpline", "1091", "")]:
        db.add(DirectoryEntry(name=name, category="emergency", phone=phone, is_24h=True, notes=note or None))
    add_dir("Koramangala Community Hospital", "hospital", "+91 80 0000 0001", 1.5, 0.5, True)
    add_dir("City Care Emergency Hospital", "hospital", "+91 80 0000 0002", -2.5, 1.5, True)
    add_dir("Neighbourhood Pharmacy", "pharmacy", "+91 80 0000 0003", 0.4, -0.3)
    add_dir("All Night Chemist", "pharmacy", "+91 80 0000 0004", -1.0, -1.2, True)
    add_dir("QuickFix Plumbing", "plumber", "+91 98000 10001", 1.0, 1.8)
    add_dir("BrightSpark Electricals", "electrician", "+91 98000 10002", -1.6, 0.3)
    add_dir("Learning Circle Tutors", "tutor", "+91 98000 10003", 0.9, 1.4)
    add_dir("Paws & Care Pet Clinic", "pet", "+91 98000 10004", 2.0, -0.2)
    add_dir("Bengaluru Volunteers Network", "volunteer", "+91 98000 10005", -0.6, 2.1)
    db.add(CommunityEvent(title="Neighbourhood First-Aid Workshop", description="Free hands-on basics for residents.", lat=offset(0.6, 0.4)[0],
                          lng=offset(0.6, 0.4)[1], starts_at=utcnow() + timedelta(days=3), organizer_id=users["aarav"].id))
    db.add(CommunityEvent(title="Weekend Clean-up Drive", description="Bring gloves; bags provided.", lat=offset(-0.8, 0.9)[0],
                          lng=offset(-0.8, 0.9)[1], starts_at=utcnow() + timedelta(days=6)))
    db.commit()
    print(f"Seeded {len(users)} users. Login: nishit@nexa-demo.app / {PASSWORD}  |  admin@nexa-demo.app / {PASSWORD}")
    for k in ("aarav", "rahul", "uncle", "meera", "dev"):
        print(f"  {users[k].name:16} trust {trust_svc.compute_trust(db, users[k]).score}")


if __name__ == "__main__":
    bootstrap.init_schema()
    with SessionLocal() as s:
        seed(s, reset="--reset" in sys.argv)
