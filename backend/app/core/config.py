# FIXED: All production settings fail closed — no wildcard TRUSTED_HOSTS default, no
# silent in-memory cache in production, and X-Forwarded-For trust is explicit.
"""KARMA application settings.

Design decisions carried from the source-repo analysis:
  * Secret defaults exist so development is frictionless, but ``_assert_production_safe``
    makes the process refuse to boot if a default survives into production (risk: secrets
    defaulted to a dev string rather than failing closed).
  * ``ENVIRONMENT`` is the single switch that decides whether developer affordances
    (returning an OTP in the response body, serving /docs) are permitted at all.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_SECRET = "karma-development-only-secret-change-me-32ch"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=True
    )

    APP_NAME: str = "KARMA"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    API_PREFIX: str = "/api/v1"

    # --- database -------------------------------------------------------
    # SQLite by default so the reference build needs zero external services.
    # Production sets postgresql+asyncpg://... and GeoPort switches to PostGIS.
    DATABASE_URL: str = "sqlite+aiosqlite:///./karma.db"
    ECHO_SQL: bool = False

    # --- cache / otp / rate-limit --------------------------------------
    REDIS_URL: str | None = None  # None => in-memory CachePort fallback
    # Redis Pub/Sub ignores logical database numbers, so this deployment namespace must be
    # configurable when multiple KARMA environments share one Redis server.
    REALTIME_REDIS_CHANNEL: str = Field(
        default="karma:realtime:events:v1", min_length=3, max_length=200
    )

    # --- auth -----------------------------------------------------------
    SECRET_KEY: SecretStr = SecretStr(DEFAULT_SECRET)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=5, le=1440)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=14, ge=1, le=90)
    OTP_TTL_SECONDS: int = Field(default=300, ge=30, le=3600)
    OTP_LENGTH: int = Field(default=6, ge=4, le=8)
    # The verification-attempt budget's window. Deliberately outlives the code's own TTL:
    # a window that expired while a code was still live would hand an attacker a fresh
    # set of guesses against a live code, and a window reset by `send` (as this used to
    # be) let a resend trade one exhausted budget for a new one forever. Only a
    # successful verification clears the counter.
    OTP_ATTEMPT_WINDOW_SECONDS: int = Field(default=1800, ge=60, le=86_400)
    # Per-IP budgets. These are deliberately generous: behind carrier-grade NAT a whole
    # apartment block shares one address, so a tight per-IP limit locks out legitimate
    # neighbours. Production should pair these with a challenge (captcha / proof-of-work)
    # rather than tighten the number.
    OTP_SEND_LIMIT: int = Field(default=10, ge=1)
    OTP_SEND_WINDOW: int = Field(default=60, ge=1)
    REGISTER_LIMIT: int = Field(default=25, ge=1)
    REGISTER_WINDOW: int = Field(default=300, ge=1)
    # Password guessing. `/auth/login` used to have no budget of its own at all -- register
    # and otp/send each got one, and login rode the shared global bucket, which allowed
    # hundreds of guesses a minute per address *and* burned the same bucket legitimate
    # neighbours need in order to register. Per-IP counts every attempt; the per-account
    # budget counts only failures, so a locked-out attacker can never lock out the real user.
    LOGIN_LIMIT: int = Field(default=10, ge=1)
    LOGIN_WINDOW: int = Field(default=60, ge=1)
    LOGIN_ACCOUNT_LIMIT: int = Field(default=20, ge=1)
    LOGIN_ACCOUNT_WINDOW: int = Field(default=300, ge=1)
    SOS_LIMIT: int = Field(default=3, ge=1)
    SOS_WINDOW: int = Field(default=60, ge=1)

    # --- karma engine ---------------------------------------------------
    KARMA_START: int = Field(default=50, ge=0, le=100)

    # --- marketplace ----------------------------------------------------
    PLATFORM_FEE_RATE: float = Field(default=0.15, ge=0.0, le=0.5)
    MATCH_RADIUS_KM: float = Field(default=5.0, gt=0.0, le=100.0)
    # The timezone the night-fare window (22:00-06:00) is judged in. Clients may serialise a
    # gig start in any offset they like, so the pricing clock has to be the marketplace's own
    # rather than whichever string arrived. Validated at boot: a typo here must fail startup,
    # not the first estimate of the day.
    FARE_TIMEZONE: str = "Asia/Kolkata"

    # --- payments -------------------------------------------------------
    # Local/test runs use a deterministic authorization/capture simulator. Production is
    # forced onto Stripe below: silently minting wallet money is never a valid degradation.
    PAYMENT_PROVIDER: Literal["simulated", "stripe"] = "simulated"
    PAYMENT_CURRENCY: Literal["INR"] = "INR"
    STRIPE_SECRET_KEY: SecretStr | None = None
    STRIPE_PUBLISHABLE_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: SecretStr | None = None

    # --- immutable media objects ---------------------------------------
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = Field(default=5, ge=1, le=50)
    MEDIA_UPLOAD_LIMIT: int = Field(default=30, ge=1, le=1000)
    MEDIA_UPLOAD_WINDOW: int = Field(default=3600, ge=60, le=86_400)
    OBJECT_STORAGE_BACKEND: Literal["local", "s3"] = "local"
    S3_ENDPOINT: str | None = None
    S3_ACCESS_KEY: SecretStr | None = None
    S3_SECRET_KEY: SecretStr | None = None
    S3_BUCKET: str = Field(default="karma-media", pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    S3_REGION: str = Field(default="us-east-1", min_length=2, max_length=64)

    # --- consented location lookup -------------------------------------
    GEOCODING_PROVIDER: Literal["disabled", "nominatim"] = "disabled"
    GEOCODING_BASE_URL: str = "https://nominatim.openstreetmap.org"
    GEOCODING_USER_AGENT: str = Field(
        default="KARMA-development/1.0", min_length=8, max_length=200
    )
    GEOCODING_COUNTRY_CODES: str = Field(default="in", pattern=r"^[a-z]{2}(,[a-z]{2})*$")
    GEOCODING_REQUESTS_PER_SECOND: int = Field(default=1, ge=1, le=10)
    GEOCODING_CACHE_SECONDS: int = Field(default=86_400, ge=300, le=2_592_000)

    # --- http hardening -------------------------------------------------
    # NoDecode is required for the CSV form to work at all. Without it pydantic-settings
    # JSON-decodes complex fields straight from the environment *before* any validator
    # runs, so `_split_csv` below was unreachable dead code and
    # `ALLOWED_ORIGINS=https://karma.app` did not fall back to CSV -- it raised
    # SettingsError and the process died on boot. NoDecode hands the raw string to the
    # validator, which accepts JSON and CSV alike.
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    # An explicit local-development allowlist rather than "*". A wildcard default means a
    # deployment that forgets to set this is open to Host-header poisoning, and the
    # production guard below only fires if ENVIRONMENT was also set correctly -- two
    # things that must both be right for the default to be safe. This list is safe on its
    # own and production must extend it.
    TRUSTED_HOSTS: Annotated[list[str], NoDecode] = [
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "[::1]",
        "test",
        "testserver",
    ]
    RATE_LIMIT_REQUESTS: int = Field(default=300, ge=1)
    RATE_LIMIT_WINDOW: int = Field(default=60, ge=1)

    # How many reverse proxies sit in front of this process. 0 = none, and
    # ``X-Forwarded-For`` is ignored entirely (it is attacker-controlled otherwise).
    # Set this to the real number of hops you operate so rate limiting keys on the true
    # client address. See app/core/net.py for the derivation.
    TRUSTED_PROXY_HOPS: int = Field(default=0, ge=0, le=8)

    @field_validator("ALLOWED_ORIGINS", "TRUSTED_HOSTS", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept `A,B` from the environment as well as a JSON array or a real list.

        Both forms must work. docker-compose.yml passes JSON; a human setting an env var
        by hand reaches for CSV, and the docstring on this class has always promised CSV
        would work. It did not: see the NoDecode note on ALLOWED_ORIGINS.
        """
        if not isinstance(value, str):
            return value

        text = value.strip()
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"not a valid JSON list: {text!r}") from exc
            if not isinstance(decoded, list):
                raise ValueError(f"expected a JSON list, got {type(decoded).__name__}")
            return [str(item).strip() for item in decoded if str(item).strip()]

        return [part.strip() for part in text.split(",") if part.strip()]

    @field_validator("FARE_TIMEZONE")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        """Boot-time check: a bad zone name must not surface as a 500 on the first estimate.

        ``zoneinfo`` resolves lazily, so without this a typo in ``FARE_TIMEZONE`` (or a slim
        image with no tzdata at all) would pass every config check and then fail inside
        :func:`app.services.fare.is_night_time` at request time.
        """
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as exc:  # noqa: BLE001 - ZoneInfoNotFoundError, KeyError, tzdata gaps
            raise ValueError(
                f"FARE_TIMEZONE must be an IANA timezone name (e.g. 'Asia/Kolkata'), got {value!r}"
            ) from exc
        return value

    @model_validator(mode="after")
    def _assert_production_safe(self) -> Settings:
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY.get_secret_value() == DEFAULT_SECRET:
                raise RuntimeError(
                    "SECRET_KEY is still the development default; refusing to start in production."
                )
            if "*" in self.ALLOWED_ORIGINS:
                raise RuntimeError("ALLOWED_ORIGINS may not be '*' in production.")
            if "*" in self.TRUSTED_HOSTS:
                raise RuntimeError("TRUSTED_HOSTS may not be '*' in production.")
            if not self.ALLOWED_ORIGINS:
                raise RuntimeError("ALLOWED_ORIGINS must be set explicitly in production.")
            if not self.TRUSTED_HOSTS:
                raise RuntimeError("TRUSTED_HOSTS must be set explicitly in production.")
            # MemoryCache is per-process. In production it silently makes rate limits,
            # OTP storage and single-use WebSocket tickets local to one worker, so an
            # attacker just retries until they land on a fresh process. Redis is not an
            # optimisation here, it is the correctness boundary.
            if not self.REDIS_URL:
                raise RuntimeError(
                    "REDIS_URL is required in production: the in-memory CachePort cannot "
                    "enforce rate limits, OTP expiry or single-use realtime tickets across "
                    "worker processes."
                )
            if self.OBJECT_STORAGE_BACKEND != "s3":
                raise RuntimeError(
                    "OBJECT_STORAGE_BACKEND must be 's3' in production; uploaded evidence "
                    "cannot live on an ephemeral API filesystem."
                )
            if self.S3_ACCESS_KEY is None or self.S3_SECRET_KEY is None:
                raise RuntimeError("S3_ACCESS_KEY and S3_SECRET_KEY are required in production.")
            if self.GEOCODING_PROVIDER == "disabled":
                raise RuntimeError("GEOCODING_PROVIDER must be configured in production.")
            if self.GEOCODING_USER_AGENT == "KARMA-development/1.0":
                raise RuntimeError(
                    "GEOCODING_USER_AGENT must identify the production deployment and contact."
                )
            if self.PAYMENT_PROVIDER != "stripe":
                raise RuntimeError(
                    "PAYMENT_PROVIDER must be 'stripe' in production; simulated payments "
                    "must never create real wallet credit."
                )
            stripe_secret = (
                self.STRIPE_SECRET_KEY.get_secret_value()
                if self.STRIPE_SECRET_KEY is not None
                else ""
            )
            webhook_secret = (
                self.STRIPE_WEBHOOK_SECRET.get_secret_value()
                if self.STRIPE_WEBHOOK_SECRET is not None
                else ""
            )
            if not stripe_secret.startswith("sk_"):
                raise RuntimeError("STRIPE_SECRET_KEY is required in production.")
            if not (self.STRIPE_PUBLISHABLE_KEY or "").startswith("pk_"):
                raise RuntimeError("STRIPE_PUBLISHABLE_KEY is required in production.")
            if not webhook_secret.startswith("whsec_"):
                raise RuntimeError("STRIPE_WEBHOOK_SECRET is required in production.")
        return self

    # --- derived --------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def expose_dev_otp(self) -> bool:
        """Labour Link returned the OTP in the response body unconditionally.

        That is catastrophic if the flag is ever misconfigured, so it is hard-gated
        here on ENVIRONMENT rather than on a separate boolean that could drift.
        """
        return self.ENVIRONMENT in {"development", "test"}

    @property
    def use_postgis(self) -> bool:
        return "postgresql" in self.DATABASE_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
