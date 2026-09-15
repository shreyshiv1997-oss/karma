"""Lifecycle utilities for Bitchat's ephemeral relay."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, update

from app.models.messaging import BitchatEnvelope, BitchatPreKey

log = logging.getLogger(__name__)
_SWEEP_INTERVAL_SECONDS = 30


async def purge_expired(session) -> int:
    """Physically remove expired ciphertext.

    Claimed one-time prekeys are intentionally not recycled. An offline sender may still hold
    the claimed public half; making that key available again after a timeout would allow two
    different messages to use one "one-time" key and quietly destroy its security property.
    """
    now = datetime.now(UTC)
    expired = await session.execute(
        delete(BitchatEnvelope).where(BitchatEnvelope.expires_at <= now)
    )
    # A mesh-only sender may never submit an envelope to the relay. Once even the
    # longest legal message TTL has elapsed, remove who/which-gig claimed the key,
    # while retaining the claimed_at tombstone so that key is never recycled.
    await session.execute(
        update(BitchatPreKey)
        .where(
            BitchatPreKey.claimed_at <= now - timedelta(days=7),
            BitchatPreKey.claimed_by_device_id.is_not(None),
        )
        .values(claimed_by_device_id=None, claimed_gig_id=None)
    )
    return int(expired.rowcount or 0)


async def cleanup_forever(factory) -> None:
    """Continuously enforce expiry even when nobody opens a conversation.

    More than one worker may run this idempotent sweep. The database predicate is the
    authority, so duplicate sweepers cannot resurrect or double-deliver anything.
    """
    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
            async with factory() as session:
                removed = await purge_expired(session)
                await session.commit()
            if removed:
                log.debug("Bitchat expiry sweep removed %s envelope(s)", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Bitchat expiry sweep failed", exc_info=True)
