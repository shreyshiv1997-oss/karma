"""Session revocation: making a logout actually mean something.

Before this module existed, a token was only ever checked for its signature and its expiry.
`jti` was minted into every token and consulted by nobody, and there was no logout endpoint at
all -- "signing out" meant clearing client storage, which is a UX gesture, not a security one.
A captured refresh token stayed valid for the whole `REFRESH_TOKEN_EXPIRE_DAYS`, and a captured
access token for the whole `ACCESS_TOKEN_EXPIRE_MINUTES`, against a server that could not be
told to stop trusting either.

Two mechanisms, because they cost different things:

* **`users.token_version`** -- the session epoch. One integer per user; bumping it invalidates
  every token minted before the bump in a single write, with no storage that grows with usage.
  This is what "sign out everywhere" and "we revoked this account" ride on.
* **a `jti` denylist** -- precise but per-token, so it must be bounded: entries are written with
  the revoked token's own remaining lifetime and expire on their own. Revoking one session must
  not leak a row into Redis forever.

The denylist lives behind `CachePort` for the same reason rate limits do: an in-process dict
cannot revoke a token for the other workers, which is why production refuses to boot without
Redis.
"""

from __future__ import annotations

from app.core.ports import CachePort, build_cache
from app.core.security import TokenClaims

REVOKED_KEY = "karma:revoked:{jti}"

_cache: CachePort = build_cache()


async def revoke(claims: TokenClaims) -> None:
    """Refuse this token from now until it would have expired on its own.

    A token with no `jti` (issued before the claim existed) has nothing to name, so it falls to
    the session epoch instead -- which is why logout also bumps `token_version` when the caller
    wants everything gone rather than one device.
    """
    if not claims.jti:
        return
    ttl = claims.seconds_left()
    if ttl <= 0:
        # Already expired: nothing left to protect, and a 0-TTL marker would be stored forever.
        return
    await _cache.set(REVOKED_KEY.format(jti=claims.jti), "1", ttl=ttl)


async def is_revoked(claims: TokenClaims) -> bool:
    if not claims.jti:
        return False
    return await _cache.get(REVOKED_KEY.format(jti=claims.jti)) is not None


async def session_is_current(claims: TokenClaims, token_version: int | None) -> bool:
    """False when the token predates the account's current session epoch.

    Tokens issued before `ver` existed carry no claim and read as version 0, matching a fresh
    account's default -- the upgrade cannot log anybody out.
    """
    return claims.version == int(token_version or 0)
