"""Phone OTP verification, ported from Labour Link.

Two security corrections over the original:
  * The OTP is never returned by ``send`` -- the router decides, and only in dev/test
    (see ``settings.expose_dev_otp``).
  * A verification attempt budget is enforced alongside the send budget, so an attacker
    cannot brute-force the code inside its TTL.
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
        await self.cache.delete(self.ATTEMPTS_KEY.format(phone=phone))
        return code

    async def verify(self, phone: str, code: str) -> bool:
        key = self.KEY.format(phone=phone)
        attempts_key = self.ATTEMPTS_KEY.format(phone=phone)

        attempts = await self.cache.incr_window(attempts_key, settings.OTP_TTL_SECONDS)
        if attempts > self.MAX_ATTEMPTS:
            await self.cache.delete(key)
            raise RateLimited("Too many OTP attempts. Request a new code.")

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
