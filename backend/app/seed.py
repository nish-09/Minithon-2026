"""Demo data. `python -m app.seed [--reset]`

Everything here goes through the real tables and the real Trust Engine: there are no hard-coded trust
scores. Histories are generated as completed requests + reviews + behaviour events, and the engine
computes the scores from them. Replace with real data/services in production.
Demo password for every seeded account: nexa1234
Location: Centered around Thadomal Shahani Engineering College (TSEC), Bandra West, Mumbai
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
    Assignment, Certification, CommunityEvent, CreditTransaction, DirectoryEntry, HelpCredit,
    HelpRequest, Incident, IncidentStep, Match, Message, Notification, Profile, Protocol,
    ProtocolStep, Relationship, RelationshipPreference, RelationshipType, RelStatus, Report,
    RequestCategory, RequestRecipient, RequestStatusHistory, Review, RevokedToken, Role, Skill,
    TrustEvent, TrustScore, User, UserCertification, UserSkill, Verification, utcnow,
)
from .security import hash_password
from .services import credits as credits_svc
from .services import trust as trust_svc

PASSWORD = "nexa1234"
# Thadomal Shahani Engineering College (TSEC), 37th Road, Off Linking Road, Bandra West, Mumbai
HOME = (19.0645, 72.8358)


def offset(dx_km: float, dy_km: float) -> tuple[float, float]:
    lat = HOME[0] + dy_km / 111.0
    lng = HOME[1] + dx_km / (111.0 * math.cos(math.radians(HOME[0])))
    return round(lat, 5), round(lng, 5)


# key, name, email, phone, (dx, dy) km from home, available, skills[(slug, years)], certs[slug], bio, verified(identity, phone, email), account age days
PEOPLE = [
    ("nishit", "Nishit Sharma", "nishit@nexa-demo.app", "+91 98000 00001", (0.0, 0.0), False, [("physical_assistance", 1)], [], "Student at TSEC, living near campus in Bandra West.", (True, True, True), 200),
    ("mom", "Anita Sharma", "anita@nexa-demo.app", "+91 98000 00002", (0.5, 0.5), True, [("elder_care", 3)], [], "Nishit's mother living near Pali Hill, Bandra West.", (True, True, True), 400),
    ("uncle", "Suresh Sharma", "suresh@nexa-demo.app", "+91 98000 00003", (0.6, -0.6), True, [("physical_assistance", 10), ("driving", 20)], [], "Retired, living near Khar West / Linking Road.", (True, True, True), 380),
    ("cousin", "Rohan Verma", "rohan@nexa-demo.app", "+91 98000 00004", (-0.7, 0.6), True, [("physical_assistance", 4), ("tech_support", 6)], [], "Software engineer living near Bandstand, Bandra.", (True, True, True), 300),
    ("kabir", "Kabir Malhotra", "kabir@nexa-demo.app", "+91 98000 00005", (-0.8, -0.7), False, [("carpentry", 5)], [], "Close friend living near Hill Road, Bandra.", (True, True, True), 500),
    ("aarav", "Aarav Mehta", "aarav@nexa-demo.app", "+91 98000 00006", (0.0, 0.2), True, [("first_aid", 6), ("cpr", 4)], ["first_aid_cert", "cpr_cert"], "Paramedic student opposite TSEC on 37th Road.", (True, True, True), 700),
    ("rahul", "Rahul Shah", "rahul@nexa-demo.app", "+91 98000 00007", (0.4, 0.0), True, [("physical_assistance", 5), ("carpentry", 3)], [], "Friendly Bandra neighbour near National College.", (True, True, True), 500),
    ("dev", "Dev Patel", "dev@nexa-demo.app", "+91 98000 00008", (0.0, -0.3), True, [("physical_assistance", 1)], [], "TSEC first-year student, new to NEXA.", (False, True, True), 3),
    ("meera", "Meera Kulkarni", "meera@nexa-demo.app", "+91 98000 00009", (-0.5, 0.0), True, [("physical_assistance", 2)], [], "Resident near Linking Road, Bandra West.", (False, True, True), 120),
    ("priya", "Priya Nair", "priya@nexa-demo.app", "+91 98000 00010", (0.6, 0.5), True, [("teaching", 8)], ["teaching_cert"], "Maths and physics tutor near Turner Road, Bandra.", (True, True, True), 600),
    ("vikram", "Vikram Rao", "vikram@nexa-demo.app", "+91 98000 00011", (0.8, -0.5), True, [("electrical", 12)], ["electrician_license"], "Licensed electrician in Bandra West.", (True, True, True), 650),
    ("sneha", "Sneha Iyer", "sneha@nexa-demo.app", "+91 98000 00012", (-0.9, 0.4), True, [("pet_care", 5)], ["vet_assistant_cert"], "Vet assistant near Carter Road, Bandra. Dog lover.", (True, True, True), 450),
    ("arjun", "Arjun Singh", "arjun@nexa-demo.app", "+91 98000 00013", (1.0, 0.8), True, [("physical_assistance", 6)], [], "Gym trainer at Bandra West.", (True, True, True), 250),
    ("admin", "NEXA Admin", "admin@nexa-demo.app", "+91 98000 00099", (0.1, 0.1), False, [], [], "Community administrator for TSEC Bandra.", (True, True, True), 900),
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
    ("nishit", "mom", "mother", 1, True),
    ("nishit", "uncle", "uncle", 2, True),
    ("nishit", "cousin", "cousin", 3, True),
    ("nishit", "kabir", "friend", 4, True),
]

RATING_COMMENTS = {
    5: "Excellent, arrived quickly and was very kind.",
    4: "Helpful and on time.",
    3: "Got it done but was late.",
    2: "Not great.",
    1: "Did not show up properly.",
}


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
    if not reset and db.scalar(select(User.id).where(User.email == "nishit@nexa-demo.app")):
        print("Seed data already present (use --reset to rebuild).")
        return

    skills = {s.slug: s for s in db.scalars(select(Skill))}
    certs = {c.slug: c for c in db.scalars(select(Certification))}
    users: dict[str, User] = {}
    for key, name, email, phone, (dx, dy), avail, sk, cs, bio, (ident, ph, em), age in PEOPLE:
        lat, lng = offset(dx, dy)
        u = User(
            name=name, email=email, phone=phone, password_hash=hash_password(PASSWORD),
            role=Role.ADMIN if key == "admin" else Role.USER,
            identity_verified=ident, phone_verified=ph, email_verified=em,
            lat=lat, lng=lng, is_available=avail,
            created_at=utcnow() - timedelta(days=age), location_updated_at=utcnow()
        )
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
    inverse = {r.slug: r.inverse_slug for r in db.scalars(select(RelationshipType))}
    for owner, other, label, prio, can in CIRCLE:
        a, b = users[owner], users[other]
        db.add(Relationship(
            user_id=a.id, related_user_id=b.id, relationship_type=label, status=RelStatus.ACCEPTED,
            initiated_by_id=a.id, priority=prio, can_receive_requests=can, is_trusted=True
        ))
        db.add(Relationship(
            user_id=b.id, related_user_id=a.id, relationship_type=inverse.get(label) or "other",
            status=RelStatus.ACCEPTED, initiated_by_id=a.id, priority=2, can_receive_requests=True, is_trusted=True
        ))

    # Realistic historical requests -> real events -> engine-computed trust
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
            r = HelpRequest(
                requester_id=client.id, raw_text=f"Past {cat} request in Bandra West",
                title=f"Past {cat.replace('_', ' ')} help", description="",
                category=cat, urgency="normal", skills_required=[], lat=client.lat, lng=client.lng,
                status="RATED", routing_mode="community", created_at=when, completed_at=when + timedelta(hours=1),
                filled_slots=1, expires_at=when + timedelta(hours=2), search_radius_km=10
            )
            db.add(r)
            db.flush()
            db.add(Assignment(request_id=r.id, helper_id=h.id, status="DONE", accepted_at=when, completed_at=r.completed_at, eta_minutes=6))
            db.add(Review(
                request_id=r.id, reviewer_id=client.id, reviewee_id=h.id, rating=ratings[i],
                comment=RATING_COMMENTS[ratings[i]], category=cat, created_at=r.completed_at
            ))
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

    # =========================================================================
    # ACTIVE REQUEST at TSEC Bandra (populates requests, assignments, matches, recipients, messages)
    # =========================================================================
    active_req = HelpRequest(
        requester_id=users["nishit"].id,
        raw_text="Twisted my ankle on the stairs near TSEC Old Building 3rd floor lab. Need first aid bandage.",
        title="Ankle sprain first-aid assistance at TSEC",
        description="Twisted my ankle descending the stairs outside the computer lab at TSEC. Need help with ice pack and bandage.",
        category="medical_assistance",
        urgency="urgent",
        skills_required=["first_aid"],
        lat=users["nishit"].lat,
        lng=users["nishit"].lng,
        location_shared=True,
        search_radius_km=5.0,
        status="ACCEPTED",
        routing_mode="community",
        created_at=now - timedelta(minutes=15),
        filled_slots=1,
        num_helpers=1,
        expires_at=now + timedelta(hours=2)
    )
    db.add(active_req)
    db.flush()

    # Active helper assignment
    active_asgn = Assignment(
        request_id=active_req.id,
        helper_id=users["aarav"].id,
        channel="community",
        status="ACTIVE",
        eta_minutes=3.0,
        distance_km=0.2,
        accepted_at=now - timedelta(minutes=10)
    )
    db.add(active_asgn)

    # RequestStatusHistory
    db.add(RequestStatusHistory(
        request_id=active_req.id,
        from_status="CREATED",
        to_status="HELPERS_NOTIFIED",
        actor_id=users["nishit"].id,
        note="Dispatched to nearby community first-aiders",
        created_at=now - timedelta(minutes=14)
    ))
    db.add(RequestStatusHistory(
        request_id=active_req.id,
        from_status="HELPERS_NOTIFIED",
        to_status="ACCEPTED",
        actor_id=users["aarav"].id,
        note="Aarav Mehta accepted request with ETA 3 mins",
        created_at=now - timedelta(minutes=10)
    ))

    # Matches table (SmartMatch snapshot)
    m1 = Match(
        request_id=active_req.id,
        helper_id=users["aarav"].id,
        match_score=95.5,
        trust_score=96.0,
        distance_km=0.2,
        eta_minutes=3.0,
        in_circle=False,
        breakdown={"trust": 0.40, "proximity": 0.35, "skills": 0.25, "verified_first_aid": True},
        created_at=now - timedelta(minutes=14)
    )
    m2 = Match(
        request_id=active_req.id,
        helper_id=users["rahul"].id,
        match_score=81.0,
        trust_score=88.5,
        distance_km=0.4,
        eta_minutes=5.0,
        in_circle=False,
        breakdown={"trust": 0.35, "proximity": 0.30, "skills": 0.16, "verified_first_aid": False},
        created_at=now - timedelta(minutes=14)
    )
    m3 = Match(
        request_id=active_req.id,
        helper_id=users["dev"].id,
        match_score=62.0,
        trust_score=60.0,
        distance_km=0.3,
        eta_minutes=4.0,
        in_circle=False,
        breakdown={"trust": 0.20, "proximity": 0.30, "skills": 0.12, "verified_first_aid": False},
        created_at=now - timedelta(minutes=14)
    )
    db.add_all([m1, m2, m3])

    # RequestRecipients
    rr1 = RequestRecipient(
        request_id=active_req.id,
        user_id=users["aarav"].id,
        channel="community",
        state="ACCEPTED",
        match_score=95.5,
        notified_at=now - timedelta(minutes=14),
        responded_at=now - timedelta(minutes=10)
    )
    rr2 = RequestRecipient(
        request_id=active_req.id,
        user_id=users["rahul"].id,
        channel="community",
        state="CANCELLED",
        match_score=81.0,
        notified_at=now - timedelta(minutes=14),
        responded_at=None
    )
    rr3 = RequestRecipient(
        request_id=active_req.id,
        user_id=users["dev"].id,
        channel="community",
        state="DECLINED",
        match_score=62.0,
        notified_at=now - timedelta(minutes=14),
        responded_at=now - timedelta(minutes=12)
    )
    db.add_all([rr1, rr2, rr3])

    # Messages table (Live chat on active request)
    chat_messages = [
        (users["nishit"].id, "Hi Aarav, I twisted my ankle on the stairs near TSEC Old Building 3rd floor.", 9),
        (users["aarav"].id, "On my way! I'm right outside on 37th Road with first aid kit and an ice pack. ETA 3 mins.", 8),
        (users["nishit"].id, "Thank you so much! Sitting right outside room 302 next to the elevator.", 6),
        (users["aarav"].id, "Just entered the campus gates, taking the elevator up now.", 3),
        (users["nishit"].id, "See you in a minute!", 1),
    ]
    for sender_id, text, mins_ago in chat_messages:
        db.add(Message(
            request_id=active_req.id,
            sender_id=sender_id,
            body=text,
            created_at=now - timedelta(minutes=mins_ago)
        ))

    # =========================================================================
    # NEXA CARE: Incidents & IncidentSteps
    # =========================================================================
    burn_proto = db.scalar(select(Protocol).where(Protocol.slug == "BURN_CARE"))
    dizzy_proto = db.scalar(select(Protocol).where(Protocol.slug == "DIZZY_FAINTNESS"))

    inc1 = Incident(
        user_id=users["nishit"].id,
        status="RESOLVED",
        urgency="critical",
        situation="burn_care",
        description="Minor hot water burn on forearm in TSEC cafeteria pantry",
        location_shared=True,
        lat=users["nishit"].lat,
        lng=users["nishit"].lng,
        user_responsive=True,
        protocol_id=burn_proto.id if burn_proto else None,
        current_step=3,
        completed_steps=[1, 2, 3],
        emergency_services_advised=False,
        emergency_services_contacted=False,
        escalation_level=0,
        care_active=False,
        started_at=now - timedelta(days=2, hours=3),
        closed_at=now - timedelta(days=2, hours=2)
    )
    db.add(inc1)
    db.flush()

    db.add_all([
        IncidentStep(incident_id=inc1.id, kind="protocol_selected", step_position=1, actor="system",
                     content="Protocol BURN_CARE initiated for scald burn.", created_at=inc1.started_at),
        IncidentStep(incident_id=inc1.id, kind="step_presented", step_position=1, actor="nexa",
                     content="Cool the burn under gentle running tap water for 10-20 minutes.", created_at=inc1.started_at + timedelta(seconds=15)),
        IncidentStep(incident_id=inc1.id, kind="user_said", step_position=1, actor="user",
                     content="I have my arm under running cold water now.", created_at=inc1.started_at + timedelta(seconds=45)),
        IncidentStep(incident_id=inc1.id, kind="step_completed", step_position=1, actor="user",
                     content="Completed 15 minutes of cool water rinse.", created_at=inc1.started_at + timedelta(minutes=15)),
        IncidentStep(incident_id=inc1.id, kind="step_presented", step_position=2, actor="nexa",
                     content="Do not apply ice, butter, or toothpastes. Keep clean.", created_at=inc1.started_at + timedelta(minutes=15, seconds=10)),
        IncidentStep(incident_id=inc1.id, kind="step_completed", step_position=2, actor="user",
                     content="Step understood and followed.", created_at=inc1.started_at + timedelta(minutes=16)),
        IncidentStep(incident_id=inc1.id, kind="step_presented", step_position=3, actor="nexa",
                     content="Cover loosely with sterile non-adherent dressing.", created_at=inc1.started_at + timedelta(minutes=16, seconds=10)),
        IncidentStep(incident_id=inc1.id, kind="closed", step_position=3, actor="user",
                     content="Incident resolved. First aid bandage applied.", created_at=inc1.closed_at),
    ])

    inc2 = Incident(
        user_id=users["dev"].id,
        status="ACTIVE",
        urgency="urgent",
        situation="dizzy_faintness",
        description="Feeling very dizzy and lightheaded near TSEC sports turf",
        location_shared=True,
        lat=users["dev"].lat,
        lng=users["dev"].lng,
        user_responsive=True,
        protocol_id=dizzy_proto.id if dizzy_proto else None,
        current_step=1,
        completed_steps=[1],
        emergency_services_advised=True,
        emergency_services_contacted=False,
        escalation_level=1,
        care_active=True,
        started_at=now - timedelta(minutes=12)
    )
    db.add(inc2)
    db.flush()

    db.add_all([
        IncidentStep(incident_id=inc2.id, kind="protocol_selected", step_position=1, actor="system",
                     content="Protocol DIZZY_FAINTNESS selected based on user symptoms.", created_at=inc2.started_at),
        IncidentStep(incident_id=inc2.id, kind="step_presented", step_position=1, actor="nexa",
                     content="Sit or lie down immediately in a shaded spot. Elevate legs slightly.", created_at=inc2.started_at + timedelta(seconds=20)),
        IncidentStep(incident_id=inc2.id, kind="user_said", step_position=1, actor="user",
                     content="Lying down on a bench under the trees right now.", created_at=inc2.started_at + timedelta(seconds=60)),
        IncidentStep(incident_id=inc2.id, kind="step_completed", step_position=1, actor="user",
                     content="Sitting in shade with feet elevated.", created_at=inc2.started_at + timedelta(minutes=3)),
    ])

    # =========================================================================
    # REPORTS (Moderation / Safety)
    # =========================================================================
    rep1 = Report(
        reporter_id=users["meera"].id,
        target_user_id=users["dev"].id,
        reason="no_show",
        details="Helper agreed to help carry library books at Bandra station book stall but did not show up or answer calls.",
        status="UPHELD",
        resolved_by=users["admin"].id,
        created_at=now - timedelta(days=5)
    )
    rep2 = Report(
        reporter_id=users["nishit"].id,
        target_user_id=users["kabir"].id,
        reason="unresponsive_delay",
        details="Was late by 30 mins to help assemble bookshelf, but finished the job well afterwards.",
        status="DISMISSED",
        resolved_by=users["admin"].id,
        created_at=now - timedelta(days=12)
    )
    db.add_all([rep1, rep2])

    # =========================================================================
    # VERIFICATIONS (KYC / Certifications verification)
    # =========================================================================
    v1 = Verification(
        user_id=users["dev"].id,
        kind="identity",
        status="PENDING",
        evidence="tsec_student_id_dev_patel.pdf",
        reviewed_by=None,
        created_at=now - timedelta(days=1)
    )
    v2 = Verification(
        user_id=users["aarav"].id,
        kind="certification",
        status="APPROVED",
        evidence="mumbai_paramedic_first_aid_cert.pdf",
        reviewed_by=users["admin"].id,
        created_at=now - timedelta(days=60)
    )
    v3 = Verification(
        user_id=users["vikram"].id,
        kind="certification",
        status="APPROVED",
        evidence="maharashtra_electrical_contractor_license.pdf",
        reviewed_by=users["admin"].id,
        created_at=now - timedelta(days=90)
    )
    v4 = Verification(
        user_id=users["sneha"].id,
        kind="identity",
        status="APPROVED",
        evidence="aadhaar_verified_bandra.pdf",
        reviewed_by=users["admin"].id,
        created_at=now - timedelta(days=45)
    )
    db.add_all([v1, v2, v3, v4])

    # =========================================================================
    # REVOKED TOKENS (JWT blacklist sample)
    # =========================================================================
    db.add(RevokedToken(
        jti="jti_seed_revoked_session_tsec_demo_01",
        expires_at=now + timedelta(days=1)
    ))

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================
    db.add_all([
        Notification(
            user_id=users["nishit"].id,
            kind="helper_assigned",
            title="Aarav Mehta accepted your request",
            body="Aarav is on the way (ETA 3 mins) with first-aid supplies to TSEC Old Building.",
            data={"request_id": active_req.id, "helper_id": users["aarav"].id},
            read=False,
            created_at=now - timedelta(minutes=10)
        ),
        Notification(
            user_id=users["aarav"].id,
            kind="request_matched",
            title="Urgent help request near TSEC",
            body="Nishit Sharma requested first aid assistance at TSEC Old Building.",
            data={"request_id": active_req.id},
            read=True,
            created_at=now - timedelta(minutes=12)
        ),
        Notification(
            user_id=users["nishit"].id,
            kind="trust_score_updated",
            title="Trust Score increased to 72.5",
            body="Your community reliability score updated based on recent positive ratings.",
            data={},
            read=True,
            created_at=now - timedelta(days=1)
        ),
        Notification(
            user_id=users["dev"].id,
            kind="community_event",
            title="TSEC Campus First-Aid Workshop this Saturday",
            body="Free emergency response workshop at TSEC Auditorium. Tap to view details.",
            data={},
            read=False,
            created_at=now - timedelta(hours=5)
        ),
    ])

    # =========================================================================
    # DIRECTORY ENTRIES (Bandra West, Mumbai)
    # =========================================================================
    def add_dir(name, cat, phone, dx, dy, h24=False, notes="Verified local Bandra listing"):
        lat, lng = offset(dx, dy)
        db.add(DirectoryEntry(name=name, category=cat, phone=phone, lat=lat, lng=lng, is_24h=h24, notes=notes))

    for name, phone, note in [
        ("Unified Emergency Response (India)", "112", "All emergencies"),
        ("Mumbai Police (Bandra Station)", "100", "022-26422323"),
        ("Bandra Fire Brigade Station", "101", "022-26421111"),
        ("Emergency Ambulance (Mumbai)", "108", "24x7 Ambulance service"),
        ("Women Helpline (Mumbai)", "1091", "24x7 safety assistance"),
    ]:
        db.add(DirectoryEntry(name=name, category="emergency", phone=phone, is_24h=True, notes=note or None))

    add_dir("KB Bhabha Hospital Bandra", "hospital", "+91 22 2642 2775", -0.6, -0.8, True, "Municipal General Hospital, Bandra West")
    add_dir("Lilavati Hospital & Research Centre", "hospital", "+91 22 2675 1000", -0.5, -1.8, True, "Multi-speciality tertiary care hospital, Bandra Reclamation")
    add_dir("Holy Family Hospital Bandra", "hospital", "+91 22 6267 0555", -0.8, -0.5, True, "Hill Road, Bandra West")
    add_dir("Noble Plus 24/7 Chemist", "pharmacy", "+91 22 2600 4455", 0.2, 0.3, True, "Linking Road, Bandra West")
    add_dir("Wellness Forever Bandra", "pharmacy", "+91 22 2640 1234", -0.7, -0.4, True, "Hill Road, 24 Hours Pharmacy")
    add_dir("Bandra QuickFix Plumbing", "plumber", "+91 98200 11001", 0.4, -0.2, False, "Pali Naka & Linking Road plumbing")
    add_dir("Linking Road Electrical Works", "electrician", "+91 98200 11002", 0.3, 0.4, False, "Licensed electrical maintenance")
    add_dir("Bandra Learning Circle Tutors", "tutor", "+91 98200 11003", 0.1, 0.3, False, "Near TSEC campus, STEM tutoring")
    add_dir("Carter Road Paws & Care Pet Clinic", "pet", "+91 98200 11004", -1.1, 0.2, False, "Veterinary care & pet assistance")
    add_dir("Bandra West Citizen Volunteers", "volunteer", "+91 98200 11005", 0.0, 0.1, False, "Neighbourhood mutual aid network")

    # Community Events at TSEC Bandra
    db.add(CommunityEvent(
        title="TSEC Campus First-Aid & Emergency Workshop",
        description="Hands-on basics for students and Bandra residents at TSEC Auditorium.",
        lat=offset(0.0, 0.0)[0], lng=offset(0.0, 0.0)[1],
        starts_at=utcnow() + timedelta(days=3), organizer_id=users["aarav"].id
    ))
    db.add(CommunityEvent(
        title="Bandra Carter Road Coastal Safety Drive",
        description="Neighbourhood safety, cleanliness, and volunteer coordination at Carter Road amphitheater.",
        lat=offset(-1.0, 0.4)[0], lng=offset(-1.0, 0.4)[1],
        starts_at=utcnow() + timedelta(days=6)
    ))
    db.add(CommunityEvent(
        title="Senior Citizen Digital & Safety Clinic",
        description="Free tech assistance and emergency app setup for elders near Linking Road.",
        lat=offset(0.3, 0.5)[0], lng=offset(0.3, 0.5)[1],
        starts_at=utcnow() + timedelta(days=8), organizer_id=users["cousin"].id
    ))

    db.commit()
    print(f"Seeded {len(users)} users centered at TSEC Bandra West, Mumbai.")
    print(f"Login: nishit@nexa-demo.app / {PASSWORD}  |  admin@nexa-demo.app / {PASSWORD}")
    for k in ("aarav", "rahul", "uncle", "meera", "dev"):
        print(f"  {users[k].name:16} trust {trust_svc.compute_trust(db, users[k]).score}")


if __name__ == "__main__":
    bootstrap.init_schema()
    with SessionLocal() as s:
        seed(s, reset="--reset" in sys.argv)
