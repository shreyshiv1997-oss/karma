# FIXED: can_hire requires verified contact details and cannot be self-granted without
# verification — and rate limits key on the proxy-resolved client IP.
"""Authentication.

One identity, two entry doors: email+password (Tatwamasi) and phone OTP (Labour Link).
There is no role-selection screen -- capabilities are granted progressively.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import or_, select

from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep
from app.core.net import client_ip
from app.core.ports import build_cache
from app.core.revocation import is_revoked, revoke, session_is_current
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_claims,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.models.trust import VerificationSubmission
from app.models.user import KarmaEvent, KarmaEventType, User
from app.schemas import (
    AuthResponse,
    LoginRequest,
    LogoutRequest,
    Message,
    OtpSendRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from app.services.karma import KarmaLedger
from app.services.otp import OtpService, RateLimited

router = APIRouter(prefix="/auth", tags=["Auth"])
_cache = build_cache()


async def _rate_limit(key: str, limit: int, window: int) -> None:
    hits = await _cache.incr_window(key, window)
    if hits > limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")


@router.post("/otp/send", response_model=OtpSendResponse)
async def send_otp(payload: OtpSendRequest, request: Request) -> OtpSendResponse:
    client = client_ip(request)
    await _rate_limit(
        f"karma:rl:otpsend:{client}:{payload.phone}",
        settings.OTP_SEND_LIMIT,
        settings.OTP_SEND_WINDOW,
    )
    code = await OtpService(_cache).send(payload.phone)
    return OtpSendResponse(
        message="OTP sent",
        dev_otp=code if settings.expose_dev_otp else None,
    )


@router.post("/otp/verify", response_model=Message)
async def verify_otp(payload: OtpVerifyRequest) -> Message:
    try:
        ok = await OtpService(_cache).verify(payload.phone, payload.otp)
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    return Message(detail="Phone verified")


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(payload: RegisterRequest, request: Request, session: SessionDep) -> AuthResponse:
    client = client_ip(request)
    await _rate_limit(f"karma:rl:register:{client}", settings.REGISTER_LIMIT, settings.REGISTER_WINDOW)

    # Build the uniqueness check conditionally: comparing a column to None compiles to
    # `IS NULL`, which would match every email-only user and 409 all later registrations.
    conditions = [User.handle == payload.handle]
    if payload.email:
        conditions.append(User.email == payload.email)
    if payload.phone:
        conditions.append(User.phone == payload.phone)

    exists = await session.scalar(select(User.id).where(or_(*conditions)))
    if exists is not None:
        raise HTTPException(status_code=409, detail="Handle, email or phone already registered")

    # A phone registration requires a completed OTP; an email registration does not.
    if payload.phone and not await OtpService(_cache).is_verified_recently(payload.phone):
        raise HTTPException(status_code=400, detail="Phone OTP verification required")

    user = User(
        handle=payload.handle,
        display_name=payload.display_name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        city=payload.city,
        capabilities=["can_post", "can_follow", "can_chat"],
        karma=settings.KARMA_START,
        karma_work=settings.KARMA_START,
        karma_social=settings.KARMA_START,
        reputation_score=float(settings.KARMA_START),
    )
    session.add(user)
    await session.flush()

    if payload.phone:
        await OtpService(_cache).consume_verification(payload.phone)
        # Record *which* number was proven, not merely that a phone was proven once. No
        # endpoint can change `users.phone` today, so the ledger row and the credential cannot
        # diverge yet; the day a change-number flow exists, `has_verified_contact` below must
        # compare this value against the account's current phone -- otherwise a verified number
        # becomes permanent proof of whatever replaces it, and `can_hire` (the ability to summon
        # a stranger to an address) inherits that hole.
        await KarmaLedger(session).record(
            user.id,
            KarmaEventType.PHONE_VERIFIED,
            reason="Phone number verified",
            meta={"phone": user.phone},
        )

    return AuthResponse(
        user=UserOut.model_validate(user),
        access_token=create_access_token(user.id, version=user.token_version),
        refresh_token=create_refresh_token(user.id, version=user.token_version),
    )


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest, request: Request, session: SessionDep) -> AuthResponse:
    identifier = payload.identifier.strip()

    # Two budgets, because they stop two different attacks.
    #
    # `/auth/login` used to have no budget of its own at all while /auth/register and
    # /auth/otp/send each had a tight one, so password guessing was capped only by the shared
    # global bucket -- hundreds of tries a minute per address, which also spent the same
    # allowance neighbours behind one NAT need in order to register. The per-address limit
    # stops a spray across many accounts. The per-account limit stops a siege of one account,
    # and it counts *failures only*, because throttling successes would hand an attacker who
    # knows a handle the ability to lock that person out of their own login.
    await _rate_limit(
        f"karma:rl:login:{client_ip(request)}", settings.LOGIN_LIMIT, settings.LOGIN_WINDOW
    )

    user = await session.scalar(
        select(User).where(
            or_(User.handle == identifier, User.email == identifier, User.phone == identifier)
        )
    )
    # Uniform message: do not reveal which identifier failed to match.
    if user is None or not verify_password(payload.password, user.password_hash):
        await _rate_limit(
            f"karma:rl:loginacct:{identifier.casefold()}",
            settings.LOGIN_ACCOUNT_LIMIT,
            settings.LOGIN_ACCOUNT_WINDOW,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if user.is_suspended:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

    # Transparent upgrade: a migrated bcrypt hash becomes Argon2id here, silently.
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    return AuthResponse(
        user=UserOut.model_validate(user),
        access_token=create_access_token(user.id, version=user.token_version),
        refresh_token=create_refresh_token(user.id, version=user.token_version),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, session: SessionDep) -> TokenPair:
    try:
        claims = decode_claims(payload.refresh_token, "refresh")
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = await session.get(User, claims.subject)
    if user is None or user.is_suspended:
        raise HTTPException(status_code=401, detail="Invalid session")
    # A refresh token minted before a sign-out-everywhere, or explicitly revoked by a logout on
    # that device, is no longer a credential -- and this is the endpoint that would otherwise
    # quietly hand it a fresh 60-minute access token.
    if not await session_is_current(claims, user.token_version) or await is_revoked(claims):
        raise HTTPException(status_code=401, detail="Invalid session")

    # Deliberate: the rotated-out refresh token is *not* revoked here. Revoking on use would
    # make refresh single-use, and the web client has no single-flight guard on its refresh path
    # (the Flutter one does), so two parallel 401s would leave the second one holding a dead
    # token and bounce a live user back to the sign-in screen. The epoch bump above is what
    # saves a user who is actually under attack; making rotation safe is a client-side
    # prerequisite, noted in the README rather than shipped half-done here.
    return TokenPair(
        access_token=create_access_token(user.id, version=user.token_version),
        refresh_token=create_refresh_token(user.id, version=user.token_version),
    )


def _bearer_or_none(request: Request) -> str | None:
    """The raw access token, without the ceremony of accepting it."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None


@router.post("/logout", response_model=Message)
async def logout(request: Request, payload: LogoutRequest | None = None) -> Message:
    """End *this* session: the access token in hand, plus the refresh token if one is handed over.

    Only the presented tokens are revoked, so signing out on a phone leaves a laptop working.
    Without this the endpoint would be a client-side `localStorage.clear()` wearing a uniform:
    the pair would stay valid for another 60 minutes and 14 days respectively, and a token stolen
    before the "logout" would keep working afterwards. A caller who suspects their account,
    rather than their device, wants /auth/logout-all.

    It deliberately does *not* depend on a live access token. Requiring one -- which this endpoint
    did until now, by taking `CurrentUser` -- means the client that most needs to sign out is the
    one it refuses: an hour after the last request, `GET /auth/me` is a 401, and so is
    `POST /auth/logout`, leaving the refresh token good for its remaining thirteen days. A refresh
    token is self-authenticating, which is why /auth/refresh needs no session either; holding it
    *is* the proof that this request is entitled to kill it.

    Nor does the route borrow the shared "401 -> refresh -> retry" path the API clients use. That
    retry mints a new pair, so the logout would then revoke the token it was handed while the
    freshly rotated one stayed alive -- a sign-out that quietly replaces the session it ends. The
    clients' sign-out calls skip the retry for exactly this reason (`signOut` in `src/api/client.ts`).
    """
    access_error: str | None = None
    revoked_access = False
    raw_access = _bearer_or_none(request)
    if raw_access is not None:
        try:
            await revoke(decode_claims(raw_access, "access"))
            revoked_access = True
        except TokenError as exc:
            access_error = str(exc)

    if payload is not None and payload.refresh_token:
        try:
            refresh_claims = decode_claims(payload.refresh_token, "refresh")
        except TokenError as exc:
            # Which half of the request failed decides the status: a caller that got *something*
            # revoked made a partial success and deserves a 400 naming what did not happen, while a
            # caller whose credentials were all unreadable has simply not signed out -- a 400
            # claiming an access token died would be invented.
            if revoked_access:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "This device's access token was revoked; the refresh token was not: "
                        f"{exc}"
                    ),
                ) from exc
            raise HTTPException(
                status_code=401,
                detail=(
                    "Nothing to revoke: the refresh token could not be read"
                    + (f", and neither could the access token ({access_error})" if access_error else "")
                ),
            ) from exc
        await revoke(refresh_claims)
        return Message(
            detail="Signed out on this device"
            if revoked_access
            else "Signed out on this device; its access token was already invalid"
        )

    if access_error is not None or raw_access is None:
        # Nothing was revoked. Answering 200 here would be the same lie this endpoint was added
        # to stop: a client that reads 200 as "signed out" wipes its storage and moves on.
        raise HTTPException(
            status_code=401,
            detail="Nothing to revoke: present a live access token, or the refresh token in the body",
        )
    # No refresh token in the body. Say so, rather than letting the caller believe the session is
    # over: the access token dies now, and its holder can still re-mint one all afternoon.
    return Message(
        detail="Signed out on this device; no refresh token was presented, so it stays valid"
    )


@router.post("/logout-all", response_model=Message)
async def logout_everywhere(user: CurrentUser, session: SessionDep) -> Message:
    """End every session on the account by advancing its epoch.

    One integer write invalidates every token minted before it -- access and refresh alike, on
    every device -- without a revocation table that grows with the number of logins. The token
    used to call this endpoint dies with the rest, which is why the caller must re-authenticate:
    a "sign out everywhere" that leaves the current session working would be a lie.
    """
    user.token_version = int(user.token_version or 0) + 1
    await session.flush()
    return Message(detail="Signed out everywhere; other sessions are now invalid")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


# Capabilities a user may add to themselves with no further proof. These are the
# defaults every account already receives; listing them keeps the endpoint total.
SELF_SERVICE_CAPABILITIES = {"can_post", "can_follow", "can_chat"}

# Capabilities that are self-*requested* but only granted once the stated precondition
# actually holds. `can_work` is absent deliberately: it is granted solely by
# POST /workers/register, behind an approved KYC submission.
VERIFIED_CAPABILITIES = {"can_hire"}


async def has_verified_contact(session, user: User) -> bool:
    """True when this account has a contact detail somebody actually proved they own.

    Two ways to satisfy it, both evidenced by durable state rather than by the caller
    saying so:

      * a phone number that completed the OTP flow -- registration appends a
        ``PHONE_VERIFIED`` ledger row when, and only when, the OTP was consumed; or
      * an approved KYC submission, which is strictly stronger.
    """
    if user.phone:
        verified_phone = await session.scalar(
            select(KarmaEvent.id).where(
                KarmaEvent.user_id == user.id,
                KarmaEvent.event_type == KarmaEventType.PHONE_VERIFIED.value,
            )
        )
        if verified_phone is not None:
            return True

    approved_kyc = await session.scalar(
        select(VerificationSubmission.id).where(
            VerificationSubmission.user_id == user.id,
            VerificationSubmission.status == "approved",
        )
    )
    return approved_kyc is not None


@router.post("/capability/{capability}", response_model=UserOut)
async def grant_capability(capability: str, user: CurrentUser, session: SessionDep) -> UserOut:
    """Opt into a capability.

    ``can_hire`` is self-*service* but not self-*asserted*: hiring means summoning a
    stranger to a physical address, so the account must have a contact detail that was
    actually verified. The previous implementation granted it to any authenticated
    caller, including an account registered seconds earlier with an unverified email --
    and, worse, set ``is_verified = True`` while doing so, letting any account award
    itself the trust badge the feed and the match cards render.

    ``can_work`` is never grantable here at all; it requires an approved KYC via the
    trust router, because a stranger is entering someone's home.
    """
    if capability in SELF_SERVICE_CAPABILITIES:
        pass
    elif capability in VERIFIED_CAPABILITIES:
        if not await has_verified_contact(session, user):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Verify a contact detail before hiring: confirm your phone number "
                    "by OTP, or complete identity verification."
                ),
            )
    else:
        raise HTTPException(
            status_code=400, detail="That capability cannot be self-granted; complete verification."
        )

    caps = set(user.capabilities or [])
    caps.add(capability)
    user.capabilities = sorted(caps)
    # `is_verified` is a trust assertion owned by the KYC reviewer (see
    # trust.review_verification). Opting into a capability must never set it.
    await session.flush()
    return UserOut.model_validate(user)
