"""SQLAlchemy models. String enums keep the schema portable between SQLite and PostgreSQL."""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Always timezone-aware UTC. SQLite drops tzinfo on read, which made API timestamps ambiguous to browsers."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        # SQLite gives naive values; PostgreSQL gives the session timezone. Normalise both to UTC.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# ---- constants ----------------------------------------------------------------------------
class Role:
    USER = "user"
    ADMIN = "admin"


class RelStatus:
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    BLOCKED = "BLOCKED"


class ReqStatus:
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    MATCHING = "MATCHING"
    TRUSTED_CIRCLE = "TRUSTED_CIRCLE"
    HELPERS_NOTIFIED = "HELPERS_NOTIFIED"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    ON_THE_WAY = "ON_THE_WAY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RATED = "RATED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    ESCALATED = "ESCALATED"

    OPEN = (CREATED, ANALYZING, MATCHING, TRUSTED_CIRCLE, HELPERS_NOTIFIED, ESCALATED)
    ACTIVE = OPEN + (ASSIGNED, ACCEPTED, ON_THE_WAY, IN_PROGRESS)
    TERMINAL = (COMPLETED, RATED, CANCELLED, EXPIRED)


class RecipientState:
    NOTIFIED = "NOTIFIED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"  # notification withdrawn (someone else accepted / request closed)
    EXPIRED = "EXPIRED"


# ---- users --------------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=Role.USER)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    location_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    is_available: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    skills: Mapped[list["UserSkill"]] = relationship(cascade="all, delete-orphan")
    certifications: Mapped[list["UserCertification"]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (Index("ix_users_geo", "lat", "lng"),)


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    bio: Mapped[str] = mapped_column(Text, default="")
    # {"mon": ["09:00-17:00"], ...}; empty => no schedule restriction beyond is_available
    availability_schedule: Mapped[dict] = mapped_column(JSON, default=dict)
    # privacy
    relationship_visibility: Mapped[str] = mapped_column(String(16), default="circle")  # me|circle|nobody
    location_sharing: Mapped[str] = mapped_column(String(16), default="requests")  # off|requests|always
    prefer_trusted_circle: Mapped[bool] = mapped_column(Boolean, default=True)
    trusted_circle_default_mode: Mapped[str] = mapped_column(String(16), default="ask")  # ask|circle|community
    user: Mapped[User] = relationship(back_populates="profile")


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    trust_category: Mapped[str | None] = mapped_column(String(64))  # category this skill builds trust in


class UserSkill(Base):
    __tablename__ = "user_skills"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True)
    years_experience: Mapped[float] = mapped_column(Float, default=0)
    skill: Mapped[Skill] = relationship(lazy="joined")


class Certification(Base):
    __tablename__ = "certifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(160))
    grants_skill: Mapped[str | None] = mapped_column(String(64))  # skill slug implied


class UserCertification(Base):
    __tablename__ = "user_certifications"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    certification_id: Mapped[int] = mapped_column(ForeignKey("certifications.id"), primary_key=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # admin-verified only
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    certification: Mapped[Certification] = relationship(lazy="joined")


# ---- relationships (trusted circle graph) -------------------------------------------------
class RelationshipType(Base):
    __tablename__ = "relationship_types"

    slug: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(64))
    group: Mapped[str] = mapped_column(String(16))  # family | friends | other
    inverse_slug: Mapped[str | None] = mapped_column(String(32))


class Relationship(Base):
    """Directed edge owner -> related. A verified relationship exists when status == ACCEPTED;
    each side keeps their own edge (own label, visibility, contactability, priority)."""

    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    related_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    relationship_type: Mapped[str] = mapped_column(ForeignKey("relationship_types.slug"))
    status: Mapped[str] = mapped_column(String(16), default=RelStatus.PENDING)
    initiated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=True)
    can_receive_requests: Mapped[bool] = mapped_column(Boolean, default=True)
    visibility: Mapped[str] = mapped_column(String(16), default="circle")  # me|circle|nobody
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1 (highest) .. 10
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    related_user: Mapped[User] = relationship(foreign_keys=[related_user_id], lazy="joined")

    __table_args__ = (
        UniqueConstraint("user_id", "related_user_id", name="uq_relationship_pair"),
        CheckConstraint("user_id != related_user_id", name="ck_no_self_relationship"),
        CheckConstraint("priority BETWEEN 1 AND 10", name="ck_priority_range"),
    )


class RelationshipPreference(Base):
    """Per-user circle preferences, kept apart from the graph edges."""

    __tablename__ = "relationship_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    prefer_circle_for_critical: Mapped[bool] = mapped_column(Boolean, default=True)
    circle_window_override_s: Mapped[int | None] = mapped_column(Integer)
    reveal_relationship_to_helpers: Mapped[bool] = mapped_column(Boolean, default=False)


# ---- requests -----------------------------------------------------------------------------
class RequestCategory(Base):
    __tablename__ = "request_categories"

    slug: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(96))
    default_skills: Mapped[list] = mapped_column(JSON, default=list)
    icon: Mapped[str] = mapped_column(String(16), default="🤝")


class HelpRequest(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(ForeignKey("request_categories.slug"), index=True)
    urgency: Mapped[str] = mapped_column(String(16), default="normal")  # normal|urgent|critical
    skills_required: Mapped[list] = mapped_column(JSON, default=list)
    num_helpers: Mapped[int] = mapped_column(Integer, default=1)
    filled_slots: Mapped[int] = mapped_column(Integer, default=0)
    time_requirement: Mapped[str | None] = mapped_column(String(64))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    location_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    search_radius_km: Mapped[float | None] = mapped_column(Float)
    unmatched_alerted: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(24), default=ReqStatus.CREATED, index=True)
    routing_mode: Mapped[str] = mapped_column(String(16), default="community")  # circle_first|community|custom
    circle_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime)
    escalated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reveal_relationship: Mapped[bool] = mapped_column(Boolean, default=False)
    nlu_source: Mapped[str] = mapped_column(String(16), default="rules")  # rules|llm
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    __table_args__ = (
        Index("ix_requests_geo", "lat", "lng"),
        CheckConstraint("num_helpers BETWEEN 1 AND 20", name="ck_num_helpers"),
    )


class RequestStatusHistory(Base):
    __tablename__ = "request_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RequestRecipient(Base):
    """Who was asked (circle member or community helper), through which channel, and their answer."""

    __tablename__ = "request_recipients"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))  # circle|community|emergency
    state: Mapped[str] = mapped_column(String(16), default=RecipientState.NOTIFIED)
    match_score: Mapped[float | None] = mapped_column(Float)
    notified_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("request_id", "user_id", name="uq_recipient"),)


class Match(Base):
    """Stored SmartMatch result snapshot so ranking is explainable after the fact."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    helper_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    match_score: Mapped[float] = mapped_column(Float)
    trust_score: Mapped[float] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    eta_minutes: Mapped[float | None] = mapped_column(Float)
    in_circle: Mapped[bool] = mapped_column(Boolean, default=False)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    helper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="community")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE|ARRIVED|DONE|CANCELLED|NO_SHOW
    eta_minutes: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    accepted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    arrived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    helper: Mapped[User] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("request_id", "helper_id", name="uq_assignment"),)


# ---- messaging / notifications ------------------------------------------------------------
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


# ---- reviews / trust ----------------------------------------------------------------------
class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"))
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reviewee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str | None] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    reviewer: Mapped[User] = relationship(foreign_keys=[reviewer_id])
    __table_args__ = (
        UniqueConstraint("request_id", "reviewer_id", "reviewee_id", name="uq_review"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_rating"),
    )


class TrustScore(Base):
    """category == '' holds the overall score; other rows are contextual trust."""

    __tablename__ = "trust_scores"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    category: Mapped[str] = mapped_column(String(48), primary_key=True, default="")
    score: Mapped[float] = mapped_column(Float)
    components: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(32), default="heuristic-v1")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TrustEvent(Base):
    """Behavioural evidence used as trust-model inputs."""

    __tablename__ = "trust_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    # notified|responded|accepted|declined|completed|cancelled|no_show|report_upheld
    category: Mapped[str | None] = mapped_column(String(48))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"))
    value: Mapped[float | None] = mapped_column(Float)  # e.g. response seconds
    counterparty_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---- credits ------------------------------------------------------------------------------
class HelpCredit(Base):
    __tablename__ = "help_credits"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_credit_nonneg"),)


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))  # earned|spent|donated|received|grant
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"))
    counterparty_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---- NEXA CARE ----------------------------------------------------------------------------
class Protocol(Base):
    """Admin-managed, versioned, pre-approved guidance. The LLM may only choose among these."""

    __tablename__ = "protocols"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(160))
    situation_keywords: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_emergency_services: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(200), default="")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    steps: Mapped[list["ProtocolStep"]] = relationship(order_by="ProtocolStep.position", cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (UniqueConstraint("slug", "version", name="uq_protocol_version"),)


class ProtocolStep(Base):
    __tablename__ = "protocol_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    instruction: Mapped[str] = mapped_column(Text)
    fallback_instruction: Mapped[str | None] = mapped_column(Text)  # used when user "can't do that"
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)  # ACTIVE|RESOLVED|CANCELLED
    urgency: Mapped[str] = mapped_column(String(16), default="critical")
    situation: Mapped[str] = mapped_column(String(64), default="unknown")
    description: Mapped[str] = mapped_column(Text, default="")
    location_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    user_responsive: Mapped[bool] = mapped_column(Boolean, default=True)
    protocol_id: Mapped[int | None] = mapped_column(ForeignKey("protocols.id"))
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    completed_steps: Mapped[list] = mapped_column(JSON, default=list)
    emergency_services_advised: Mapped[bool] = mapped_column(Boolean, default=False)
    emergency_services_contacted: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    care_active: Mapped[bool] = mapped_column(Boolean, default=False)
    request_id: Mapped[int | None] = mapped_column(Integer)  # linked help request (no FK: circular)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    protocol: Mapped[Protocol | None] = relationship(lazy="joined")


class IncidentStep(Base):
    """Audit trail of everything that happened in a care session."""

    __tablename__ = "incident_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    # protocol_selected|step_presented|step_completed|step_skipped|user_said|nexa_said|escalated|state_change|closed
    step_position: Mapped[int | None] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(16), default="system")  # user|nexa|system|admin
    content: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---- community ----------------------------------------------------------------------------
class CommunityEvent(Base):
    __tablename__ = "community_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    organizer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class DirectoryEntry(Base):
    __tablename__ = "directory_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(32), index=True)
    # emergency|hospital|pharmacy|plumber|electrician|tutor|pet|volunteer|other
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(String(255))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    is_24h: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(String(255))


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"))
    reason: Mapped[str] = mapped_column(String(48))
    details: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN|UPHELD|DISMISSED
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # email|phone|identity|certification
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING|APPROVED|REJECTED
    evidence: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RevokedToken(Base):
    """Logout denylist (JWT ids). Rows can be purged once expires_at has passed."""

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
