"""Password hashing and signed-token utilities.

Merge decision: Tatwamasi's Argon2id parameters and its strict JWT claims win, because
Argon2id is OWASP's first recommendation and Labour Link used plain bcrypt with no
issuer/audience validation. Labour Link's bcrypt hashes are still *verifiable* so that a
migrated user never has to re-enter a password; they are rehashed to Argon2id on the next
successful login (see ``password_needs_rehash``).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_log = logging.getLogger(__name__)

# Tatwamasi's exact parameters: t=3, m=64 MiB, p=4.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
_legacy_bcrypt = CryptContext(schemes=["bcrypt"], deprecated="auto")

TOKEN_ISSUER = "karma-api"
TOKEN_AUDIENCE = "karma-client"
TokenType = Literal["access", "refresh"]


# --------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """Verify against Argon2id, falling back to legacy bcrypt.

    Never raises: a malformed stored hash is simply a failed login, not a 500.
    """
    if not plain or not hashed:
        return False
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError):
        # Not an Argon2 hash -- it may be a migrated bcrypt hash.
        #
        # A failure here must not become a 500 (the login surface should not reveal that a
        # stored hash is malformed), but swallowing it silently is its own trap: a missing
        # bcrypt backend and a genuinely wrong password looked identical to every operator
        # who ever debugged a "users can't log in" ticket. So: fail closed, and log the reason.
        try:
            return _legacy_bcrypt.verify(plain, hashed)
        except Exception:  # noqa: BLE001 - passlib raises whatever its backend raises
            _log.debug("legacy bcrypt verification failed for a stored hash", exc_info=True)
            return False


def password_needs_rehash(hashed: str | None) -> bool:
    """True when the stored hash is bcrypt or an out-of-date Argon2 parameter set."""
    if not hashed:
        return True
    try:
        return _hasher.check_needs_rehash(hashed)
    except (InvalidHashError, VerificationError):
        return True


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------
def _create_token(
    subject: str | int,
    token_type: TokenType,
    expires_delta: timedelta,
    *,
    version: int = 0,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "nbf": now,
        "exp": now + expires_delta,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "jti": str(uuid.uuid4()),
        # The session epoch. Bumping `users.token_version` invalidates every token minted
        # before it, which is how "sign out everywhere" is enforced without keeping a row per
        # token. Absent from tokens issued before this claim existed, and read as 0, so a
        # live session is never dropped by the upgrade itself.
        "ver": version,
    }
    return jwt.encode(payload, settings.SECRET_KEY.get_secret_value(), algorithm=settings.ALGORITHM)


def create_access_token(subject: str | int, *, version: int = 0) -> str:
    return _create_token(
        subject, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), version=version
    )


def create_refresh_token(subject: str | int, *, version: int = 0) -> str:
    return _create_token(
        subject, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), version=version
    )


class TokenError(ValueError):
    """Raised for any invalid, expired, wrong-type or wrongly-scoped token."""


@dataclass(frozen=True)
class TokenClaims:
    """What a verified token asserts, in the shape the revocation checks need.

    ``jti`` and ``version`` are the two handles a logout can act on: one identifies a single
    token, the other identifies the whole session epoch it was minted inside.
    """

    subject: int
    token_type: TokenType
    jti: str | None
    version: int
    expires_at: datetime | None

    def seconds_left(self, *, now: datetime | None = None) -> int:
        """Remaining life, used to give a revocation marker the token's own TTL -- so the
        denylist can never outlive the thing it revokes."""
        if self.expires_at is None:
            return 0
        reference = now or datetime.now(UTC)
        expiry = self.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return max(0, int((expiry - reference).total_seconds()))


def decode_claims(token: str, expected_type: TokenType) -> TokenClaims:
    """Decode and validate a token, returning every claim the auth layer enforces.

    Validates signature, expiry, issuer, audience and the ``type`` claim, so a refresh
    token can never be presented as an access token.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=[settings.ALGORITHM],
            audience=TOKEN_AUDIENCE,
            issuer=TOKEN_ISSUER,
            options={"require_exp": True, "require_sub": True},
        )
    except JWTError as exc:
        raise TokenError("invalid token") from exc

    if payload.get("type") != expected_type:
        raise TokenError("wrong token type")
    try:
        subject = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("token subject is not a user id") from exc

    # python-jose hands back `exp` as a datetime when it can convert it and as an int when it
    # cannot; accept both rather than guessing at the library's version.
    raw_expiry = payload.get("exp")
    if isinstance(raw_expiry, (int, float)):
        expires_at: datetime | None = datetime.fromtimestamp(raw_expiry, UTC)
    elif isinstance(raw_expiry, datetime):
        expires_at = raw_expiry
    else:
        expires_at = None

    raw_version = payload.get("ver", 0)
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        raise TokenError("token session version is malformed") from None

    jti = payload.get("jti")
    return TokenClaims(
        subject=subject,
        token_type=expected_type,
        jti=jti if isinstance(jti, str) and jti else None,
        version=version,
        expires_at=expires_at,
    )


def decode_token(token: str, expected_type: TokenType) -> int:
    """Decode a token and return the subject user id. See :func:`decode_claims`."""
    return decode_claims(token, expected_type).subject
