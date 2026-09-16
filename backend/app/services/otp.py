"""Phone OTP verification, ported from Labour Link.

Security corrections over the original:
  * The OTP is never returned by ``send`` -- the router decides, and only in dev/test
    (see ``settings.expose_dev_otp``).
  * A verification attempt budget is enforced alongside the send budget, so an attacker
    cannot brute-force the code inside its TTL. The budget window outlives the code
    (``OTP_ATTEMPT_WINDOW_SECONDS``) and is *not* reset by requesting a new code: a
    resend used to clear the counter, which let an attacker trade one exhausted
    budget for a fresh one -- forever -- as long as the send budget let them keep
    resending a live code. Only a successful verification resets it.
"""

from __future__ import annotations

import secrets

from app.core.config import settings
from app.core.ports import CachePort


class OtpError(ValueError):
    pass


class RateLimited(OtpError):
    pass


class OtpService:
    KEY = "karma:otp:{phone}"
    VERIFIED_KEY = "karma:otp:verified:{phone}"
    ATTEMPTS_KEY = "karma:otp:attempts:{phone}"
    MAX_ATTEMPTS = 5

    def __init__(self, cache: CachePort) -> None:
        self.cache = cache

    async def send(self, phone: str) -> str:
        """Generate and 'deliver' an OTP. Returns the code so the caller can decide
        whether to surface it (dev) or hand it to an SMS adapter (production)."""
        code = "".join(secrets.choice("0123456789") for _ in range(settings.OTP_LENGTH))
        await self.cache.set(self.KEY.format(phone=phone), code, ttl=settings.OTP_TTL_SECONDS)
        # Deliberately NOT clearing the attempt counter here: a resend must not hand
        # the caller a fresh set of guesses against the new code. The counter keeps
        # its own, longer window (see OTP_ATTEMPT_WINDOW_SECONDS); a successful
        # verification is what resets it.
        return code

    async def verify(self, phone: str, code: str) -> bool:
        key = self.KEY.format(phone=phone)
        attempts_key = self.ATTEMPTS_KEY.format(phone=phone)

        attempts = await self.cache.incr_window(
            attempts_key, settings.OTP_ATTEMPT_WINDOW_SECONDS
        )
        if attempts > self.MAX_ATTEMPTS:
            await self.cache.delete(key)
            # The old message told a new code would fix it; it no longer does.
            raise RateLimited("Too many OTP attempts. Please wait before trying again.")

        expected = await self.cache.get(key)
        if expected is None or not secrets.compare_digest(expected, code):
            return False

        await self.cache.delete(key)
        await self.cache.delete(attempts_key)
        await self.cache.set(self.VERIFIED_KEY.format(phone=phone), "1", ttl=900)
        return True

    async def is_verified_recently(self, phone: str) -> bool:
        return await self.cache.get(self.VERIFIED_KEY.format(phone=phone)) == "1"

    async def consume_verification(self, phone: str) -> None:
        """Single-use: a verified phone cannot mint unlimited accounts."""
        await self.cache.delete(self.VERIFIED_KEY.format(phone=phone))
