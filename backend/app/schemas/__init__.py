"""Pydantic v2 request/response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

# --------------------------------------------------------------------------
# shared
# --------------------------------------------------------------------------


def normalize_phone(raw: str) -> str:
    """Canonical E.164-ish form: strip spaces/dashes, force a leading '+'.

    Both the OTP flow and registration must key on the *same* string, otherwise a
    verified phone looks unverified at registration time.
    """
    cleaned = "".join(ch for ch in raw.strip() if ch.isdigit())
    if not cleaned:
        raise ValueError("phone must contain digits")
    return f"+{cleaned}"


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    detail: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
HANDLE_RE = r"^[a-z0-9_\.]{3,30}$"


class RegisterRequest(BaseModel):
    handle: str = Field(min_length=3, max_length=30, pattern=HANDLE_RE)
    display_name: str = Field(min_length=1, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=8, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    city: str | None = Field(default=None, max_length=100)

    @field_validator("phone")
    @classmethod
    def _digits(cls, v: str | None) -> str | None:
        return None if v is None else normalize_phone(v)

    @model_validator(mode="after")
    def _need_one_identifier(self) -> RegisterRequest:
        if not self.email and not self.phone:
            raise ValueError("either email or phone is required")
        return self


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class OtpSendRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=32)

    @field_validator("phone")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalize_phone(v)


class OtpSendResponse(BaseModel):
    message: str
    # Only ever populated when settings.expose_dev_otp is true.
    dev_otp: str | None = None


class OtpVerifyRequest(BaseModel):
    phone: str
    otp: str = Field(min_length=4, max_length=8)

    @field_validator("phone")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalize_phone(v)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    """Optional, because the access token alone is already enough to log this device out.

    Passing the refresh token is what makes the logout stick past the access token's remaining
    minutes; without it the pair could simply be re-minted by whoever stole it.
    """

    refresh_token: str | None = None


class UserOut(ORMModel):
    id: int
    uuid: str
    handle: str
    display_name: str
    email: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    bio: str = ""
    city: str | None = None
    capabilities: list[str] = []
    is_verified: bool = False
    verification_tier: str = "none"
    karma: int = 50
    karma_work: int = 50
    karma_social: int = 50
    streak: int = 0
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    status_text: str | None = None


class AuthResponse(BaseModel):
    user: UserOut
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# --------------------------------------------------------------------------
# karma
# --------------------------------------------------------------------------
class KarmaEventOut(ORMModel):
    id: int
    event_type: str
    domain: str
    delta: int
    reason: str
    created_at: datetime


class KarmaLedgerOut(BaseModel):
    blended: int
    work: int
    social: int
    band: str
    events: list[KarmaEventOut]
    # `events` is a bounded page; this is the true row count. Without it the UI would
    # label a ledger of 28 events as "20 events" because that is the page size.
    total_events: int
    # True when there are older rows behind `before_id`. Decided by reading one row past the
    # page, not by whether the page happened to be full.
    truncated: bool = False


# --------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------
class CategoryOut(ORMModel):
    id: int
    name: str
    slug: str
    emoji: str
    description: str = ""
    base_fare: float
    per_km_rate: float
    per_hour_rate: float
    urgency_multiplier: float
    night_multiplier: float


# --------------------------------------------------------------------------
# gigs
# --------------------------------------------------------------------------
class EstimateRequest(BaseModel):
    category_id: int
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    estimated_hours: float = Field(default=2.0, gt=0, le=24)
    urgency: str = Field(default="standard", pattern="^(standard|urgent)$")
    skill_tier: str = Field(default="bronze", pattern="^(bronze|silver|gold)$")
    starts_at: datetime | None = None


class GigCreate(BaseModel):
    category_id: int
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(default="", max_length=2000)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    address_label: str = Field(default="", max_length=200)
    location_source: Literal["device", "geocoded", "provided"] = "provided"
    location_accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    geocoder: str | None = Field(default=None, max_length=64)
    location_consent: bool = False
    estimated_hours: float = Field(default=2.0, gt=0, le=24)
    urgency: str = Field(default="standard", pattern="^(standard|urgent)$")
    photos: list[str] = Field(default_factory=list, max_length=8)
    preferred_start_at: datetime | None = None

    @model_validator(mode="after")
    def _location_has_provenance_and_consent(self) -> GigCreate:
        if self.location_source in {"device", "geocoded"} and not self.location_consent:
            raise ValueError("location_consent must be true for device or geocoded locations")
        if self.location_source == "geocoded" and not self.geocoder:
            raise ValueError("geocoder is required for a geocoded location")
        if self.location_source != "geocoded" and self.geocoder is not None:
            raise ValueError("geocoder is only valid for geocoded locations")
        return self


class GigStatusUpdate(BaseModel):
    status: str = Field(
        pattern="^(assigned|en_route|arrived|in_progress|completion_pending|completed|cancelled)$"
    )
    proof_photos: list[str] = Field(default_factory=list, max_length=8)


class GigOut(ORMModel):
    id: int
    customer_id: int
    worker_id: int | None = None
    category_id: int
    title: str
    description: str
    status: str
    urgency: str
    lat: float
    lng: float
    address_label: str
    location_source: str = "provided"
    location_accuracy_m: float | None = None
    geocoder: str | None = None
    total: float
    fare_breakdown: dict = Field(default_factory=dict)
    photos: list[str] = Field(default_factory=list)
    proof_photos: list[str] = Field(default_factory=list)
    payment_status: str
    created_at: datetime
    completed_at: datetime | None = None


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------
class CandidateOut(BaseModel):
    user_id: int
    display_name: str
    handle: str
    avatar_url: str | None = None
    rating: float
    hourly_rate: float
    distance_km: float
    eta_minutes: int
    score: float
    karma: int
    total_jobs: int
    verification_tier: str
    reasons: list[str]
    proof_count: int = 0


class MatchRequest(BaseModel):
    gig_id: int


# --------------------------------------------------------------------------
# social
# --------------------------------------------------------------------------
class PostCreate(BaseModel):
    kind: str = Field(default="post", pattern="^(post|reel|pulse)$")
    body: str = Field(default="", max_length=4000)
    media_urls: list[str] = Field(default_factory=list, max_length=10)
    hashtags: list[str] = Field(default_factory=list, max_length=20)


class PostOut(ORMModel):
    id: int
    author_id: int
    kind: str
    body: str
    media_urls: list = []
    hashtags: list = []
    gig_id: int | None = None
    before_url: str | None = None
    after_url: str | None = None
    category_name: str | None = None
    amount_earned: float | None = None
    rating: int | None = None
    likes_count: int = 0
    comments_count: int = 0
    created_at: datetime
    # Denormalised for the feed so one query renders a card.
    author_name: str | None = None
    author_handle: str | None = None
    author_avatar: str | None = None
    author_karma: int | None = None
    author_tier: str | None = None


# --------------------------------------------------------------------------
# reviews & trust
# --------------------------------------------------------------------------
class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    punctuality: int | None = Field(default=None, ge=1, le=5)
    quality: int | None = Field(default=None, ge=1, le=5)
    communication: int | None = Field(default=None, ge=1, le=5)
    comment: str = Field(default="", max_length=2000)


class ReviewOut(ORMModel):
    id: int
    gig_id: int
    reviewer_id: int
    reviewee_id: int
    rating: int
    comment: str
    created_at: datetime


class VerificationCreate(BaseModel):
    document_type: str = Field(pattern="^(aadhaar|pan|govt_id)$")
    document_ref: str = Field(min_length=4, max_length=64)


class VerificationOut(ORMModel):
    id: int
    document_type: str
    status: str
    created_at: datetime


class TrustedContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=32)
    relationship: str = Field(default="", max_length=40)


class TrustedContactOut(ORMModel):
    id: int
    name: str
    phone: str
    relationship: str


class EmergencyRequest(BaseModel):
    gig_id: int | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    note: str = Field(default="", max_length=500)
