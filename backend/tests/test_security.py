"""Security: password hashing across both legacy and current schemes, and JWT hardening."""

from __future__ import annotations

import pytest
from passlib.context import CryptContext

from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)


def test_argon2id_roundtrip():
    hashed = hash_password("CorrectHorse!9")
    assert hashed.startswith("$argon2id$"), "expected Argon2id, the OWASP-preferred scheme"
    assert verify_password("CorrectHorse!9", hashed)
    assert not verify_password("wrong", hashed)


def test_legacy_bcrypt_still_verifies_then_upgrades():
    """A migrated Labour Link user must not be locked out."""
    legacy = CryptContext(schemes=["bcrypt"]).hash("LegacyPass!1")
    assert legacy.startswith("$2b$")
    assert verify_password("LegacyPass!1", legacy), "legacy bcrypt hash must verify"
    assert password_needs_rehash(legacy), "bcrypt must be flagged for upgrade to Argon2id"


def test_current_argon2_does_not_need_rehash():
    assert not password_needs_rehash(hash_password("Anything!123"))


@pytest.mark.parametrize("bad", [None, "", "not-a-hash", "$2b$12$garbage"])
def test_malformed_hashes_fail_closed(bad):
    assert verify_password("anything", bad) is False


def test_token_roundtrip_and_type_enforcement():
    access = create_access_token(42)
    assert decode_token(access, "access") == 42

    refresh = create_refresh_token(42)
    assert decode_token(refresh, "refresh") == 42

    # A refresh token presented as an access token must be rejected.
    with pytest.raises(TokenError):
        decode_token(refresh, "access")
    with pytest.raises(TokenError):
        decode_token(access, "refresh")


def test_tampered_token_rejected():
    token = create_access_token(42)
    with pytest.raises(TokenError):
        decode_token(token[:-3] + "abc", "access")
