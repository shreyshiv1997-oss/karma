"""Request-scoped dependencies: who is calling, and what may they do."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.revocation import is_revoked, session_is_current
from app.core.security import TokenError, decode_claims
from app.models.user import User

_bearer = HTTPBearer(auto_error=False, description="Access token")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: SessionDep,
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_claims(credentials.credentials, "access")
        user_id = claims.subject
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.is_suspended:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

    # Signature + expiry alone cannot express "this session ended". Both checks below are what
    # make logout real: the epoch catches a sign-out-everywhere, the denylist catches one device.
    if not await session_is_current(claims, user.token_version):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session ended; sign in again",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if await is_revoked(claims):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_capability(capability: str):
    """Return a dependency that enforces an additive capability.

    This replaces Labour Link's ``user_type`` check: the same user can hold ``can_hire``
    and ``can_work`` simultaneously, and capabilities can be granted at any time.
    """

    async def _checker(user: CurrentUser) -> User:
        caps = set(user.capabilities or [])
        if capability not in caps:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing capability: {capability}",
            )
        return user

    return Depends(_checker)


def require_admin(user: CurrentUser) -> User:
    if "admin" not in set(user.capabilities or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
