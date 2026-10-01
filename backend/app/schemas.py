from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

PHONE_RE = r"^\+?[0-9][0-9 \-]{6,18}$"
Urgency = Literal["normal", "urgent", "critical"]
Visibility = Literal["me", "circle", "nobody"]


class Strict(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}


class RegisterIn(Strict):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, pattern=PHONE_RE)


class LoginIn(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class LocationIn(Strict):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class SkillIn(Strict):
    slug: str = Field(max_length=64)
    years_experience: float = Field(default=0, ge=0, le=70)


class ProfileUpdate(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, pattern=PHONE_RE)
    avatar_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")
    bio: str | None = Field(default=None, max_length=1000)
    skills: list[SkillIn] | None = Field(default=None, max_length=30)
    certifications: list[str] | None = Field(default=None, max_length=20)
    availability_schedule: dict[str, list[str]] | None = None
    is_available: bool | None = None
    relationship_visibility: Visibility | None = None
    location_sharing: Literal["off", "requests", "always"] | None = None
    prefer_trusted_circle: bool | None = None
    trusted_circle_default_mode: Literal["ask", "circle", "community"] | None = None
    prefer_circle_for_critical: bool | None = None
    circle_window_override_s: int | None = Field(default=None, ge=30, le=3600)
    reveal_relationship_to_helpers: bool | None = None

    @field_validator("availability_schedule")
    @classmethod
    def _sched(cls, v):
        if v is None:
            return v
        days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        import re
        for d, windows in v.items():
            if d not in days:
                raise ValueError(f"invalid day {d}")
            for w in windows:
                if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d", w):
                    raise ValueError("windows must look like 09:00-17:00")
        return v


class AIUnderstandIn(Strict):
    text: str = Field(min_length=2, max_length=1000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class VoiceContext(Strict):
    stage: Literal["awaiting_circle_choice", "awaiting_cancel_confirm"] | None = None
    draft_text: str | None = Field(default=None, max_length=1000)
    request_id: int | None = None


class VoiceCommandIn(Strict):
    text: str = Field(min_length=1, max_length=1000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    share_location: bool = False
    context: VoiceContext = Field(default_factory=VoiceContext)


class TranscriptIn(Strict):
    transcript: str = Field(min_length=1, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)


class RequestOverrides(Strict):
    category: str | None = None
    urgency: Urgency | None = None
    title: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    num_helpers: int | None = Field(default=None, ge=1, le=20)
    time_requirement: str | None = Field(default=None, max_length=64)
    skills_required: list[str] | None = Field(default=None, max_length=10)


class RequestCreate(Strict):
    text: str = Field(min_length=3, max_length=1000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    share_location: bool = False
    routing_mode: Literal["circle_first", "community", "custom"] | None = None
    custom_recipient_ids: list[int] | None = Field(default=None, max_length=30)
    reveal_relationship: bool = False
    overrides: RequestOverrides | None = None


class RequestPatch(Strict):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    num_helpers: int | None = Field(default=None, ge=1, le=20)
    time_requirement: str | None = Field(default=None, max_length=64)


class RelationshipCreate(Strict):
    email: EmailStr | None = None
    user_id: int | None = None
    relationship_type: str = Field(max_length=32)


class RelationshipPatch(Strict):
    relationship_type: str | None = Field(default=None, max_length=32)
    is_trusted: bool | None = None
    can_receive_requests: bool | None = None
    visibility: Visibility | None = None
    priority: int | None = Field(default=None, ge=1, le=10)


class ProgressIn(Strict):
    status: Literal["ON_THE_WAY", "IN_PROGRESS"]


class ReviewIn(Strict):
    helper_id: int
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class NoShowIn(Strict):
    helper_id: int


class MessageIn(Strict):
    body: str = Field(min_length=1, max_length=2000)


class ReportIn(Strict):
    target_user_id: int | None = None
    request_id: int | None = None
    reason: Literal["harassment", "no_show", "unsafe", "fraud", "spam", "other"]
    details: str = Field(default="", max_length=2000)


class DonateIn(Strict):
    to_user_id: int
    amount: int = Field(ge=1, le=10_000)


class MatchFindIn(Strict):
    request_id: int
    limit: int = Field(default=10, ge=1, le=25)


class TrustedCircleAskIn(Strict):
    recipient_ids: list[int] | None = Field(default=None, max_length=30)


class IncidentCreate(Strict):
    text: str = Field(min_length=3, max_length=1000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    share_location: bool = False


class UtteranceIn(Strict):
    text: str = Field(min_length=1, max_length=500)


class StepCompleteIn(Strict):
    step: int | None = Field(default=None, ge=1, le=50)
    unable: bool = False


class EscalateIn(Strict):
    emergency_contacted: bool = False
    note: str = Field(default="", max_length=500)


class CloseIn(Strict):
    resolution: Literal["RESOLVED", "CANCELLED"] = "RESOLVED"
    reason: str = Field(default="", max_length=500)


# ---- admin ----
class ProtocolStepIn(Strict):
    instruction: str = Field(min_length=3, max_length=1000)
    fallback_instruction: str | None = Field(default=None, max_length=1000)
    is_critical: bool = False


class ProtocolIn(Strict):
    slug: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")
    title: str = Field(min_length=3, max_length=160)
    situation_keywords: list[str] = Field(default_factory=list, max_length=50)
    requires_emergency_services: bool = False
    source: str = Field(default="", max_length=200)
    steps: list[ProtocolStepIn] = Field(min_length=1, max_length=30)


class DirectoryIn(Strict):
    name: str = Field(min_length=2, max_length=160)
    category: Literal["emergency", "hospital", "pharmacy", "plumber", "electrician", "tutor", "pet", "volunteer", "other"]
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=255)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    is_24h: bool = False
    notes: str | None = Field(default=None, max_length=255)


class VerifyIn(Strict):
    kind: Literal["identity", "phone", "email"]
    approved: bool = True


class CertVerifyIn(Strict):
    certification: str
    verified: bool = True


class ReportResolveIn(Strict):
    status: Literal["UPHELD", "DISMISSED"]


class ModerateIn(Strict):
    is_active: bool


ListingKindT = Literal["sell", "gift", "service"]


class ListingIn(Strict):
    kind: ListingKindT
    category: str = Field(min_length=2, max_length=32, pattern=r"^[a-z_]+$")
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=2000)
    price: float | None = Field(default=None, ge=0, le=10_000_000)
    condition: Literal["new", "like_new", "good", "fair"] | None = None
    contact_phone: str | None = Field(default=None, pattern=PHONE_RE)


class ListingUpdate(Strict):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    price: float | None = Field(default=None, ge=0, le=10_000_000)
    status: Literal["available", "closed"] | None = None


class ClaimIn(Strict):
    message: str = Field(default="", max_length=500)
