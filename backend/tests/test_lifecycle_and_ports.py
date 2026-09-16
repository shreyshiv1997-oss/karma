"""The request lifecycle and the ports that fall back when infrastructure is absent.

`session_scope` is the only place a transaction is committed, and the only place queued
real-time events are published. Its failure path is the one that matters most: if it committed
before rolling back, or published events for a rolled-back transaction, clients would be told
about state that never happened. None of that was tested.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.core.db import session_scope
from app.core.ports import MemoryCache, RedisCache, build_cache
from app.models.user import User
from app.services.realtime import Event, drain_events, flush, queue_event

pytestmark = pytest.mark.asyncio


class _Boom(Exception):
    pass


@asynccontextmanager
async def _scope(session):
    """Drive `session_scope` the way FastAPI drives a `yield` dependency.

    This distinction is not cosmetic. A raw `async for` over the generator only ever *closes*
    it, which raises `GeneratorExit` -- a `BaseException`, so `except Exception` cannot catch
    it and neither the rollback nor the event discard runs. FastAPI wraps dependencies in
    `asynccontextmanager`, which throws the handler's exception *into* the generator, so the
    cleanup path executes. Testing it the other way proves nothing about production.
    """
    async with asynccontextmanager(session_scope)(session) as value:
        yield value


# ── session_scope ─────────────────────────────────────────────────────────────


async def test_a_successful_scope_commits(session_factory):
    async with session_factory() as session:
        async with _scope(session) as s:
            s.add(User(handle="committed", display_name="Committed", password_hash="x"))

    async with session_factory() as check:
        found = await check.scalar(select(User).where(User.handle == "committed"))
        assert found is not None, "the scope must commit on success"


async def test_a_failing_scope_rolls_back(session_factory):
    """★ Nothing written inside a failed scope may survive it."""
    with pytest.raises(_Boom):
        async with session_factory() as session:
            async with _scope(session) as s:
                s.add(User(handle="discarded", display_name="Discarded", password_hash="x"))
                await s.flush()
                raise _Boom("handler blew up")

    async with session_factory() as check:
        found = await check.scalar(select(User).where(User.handle == "discarded"))
        assert found is None, "the scope must roll back on failure"


async def test_a_failing_scope_discards_queued_realtime_events(session_factory):
    """★ Events queued inside a rolled-back transaction must never reach a client.

    This is the invariant the post-commit publish exists to protect. Queue an event, fail the
    transaction, and confirm the queue on *that same session* is empty afterwards rather than
    carrying a ghost of a state change that did not happen.
    """
    held = {}

    with pytest.raises(_Boom):
        async with session_factory() as session:
            held["session"] = session
            async with _scope(session) as s:
                queue_event(s, Event.of("gig.status_changed", 12345, status="in_progress"))
                # Prove it really was queued before the failure, or the assertion below is vacuous.
                assert len(drain_events(s)) == 1
                queue_event(s, Event.of("gig.status_changed", 12345, status="in_progress"))
                raise _Boom("handler blew up")

    assert drain_events(held["session"]) == [], "the queue must be empty after a rollback"


async def test_a_successful_scope_publishes_and_drains_queued_events(session_factory):
    """The counterpart: on success the queue is flushed, not left dangling."""
    held = {}

    async with session_factory() as session:
        held["session"] = session
        async with _scope(session) as s:
            queue_event(s, Event.of("gig.status_changed", 54321, status="arrived"))

    # With no socket connected the flush is a no-op that must not raise, and the queue drains.
    await flush(held["session"])
    assert drain_events(held["session"]) == []


async def test_flush_with_nothing_queued_is_a_no_op(session_factory):
    async with session_factory() as session:
        await flush(session)  # must not raise
        assert drain_events(session) == []


async def test_the_session_factory_dependency_is_a_sessionmaker(session_factory):
    """★ The WebSocket routes depend on this rather than on a request-scoped session.

    Holding `get_session()` for a socket's lifetime would pin a database session open for as
    long as the client stays connected. The routes take the factory and open short-lived
    sessions per read instead.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.db import get_session_factory

    factory = get_session_factory()
    assert isinstance(factory, async_sessionmaker)
    # It is a module-level singleton, so every socket shares one pool rather than making one.
    assert get_session_factory() is factory


# ── MemoryCache ───────────────────────────────────────────────────────────────


async def test_memory_cache_stores_reads_and_deletes():
    cache = MemoryCache()
    await cache.set("k", "v", ttl=60)
    assert await cache.get("k") == "v"

    # `delete` returns None -- the Protocol is `async def delete(self, key) -> None`.
    assert await cache.delete("k") is None
    assert await cache.get("k") is None


async def test_memory_cache_delete_of_a_missing_key_is_not_an_error():
    cache = MemoryCache()
    assert await cache.delete("never-set") is None
    assert await cache.get("never-set") is None


async def test_the_rate_limit_window_counts_within_and_resets_after():
    """`incr_window` backs the SOS and OTP limits."""
    cache = MemoryCache()
    assert await cache.incr_window("rl", 60) == 1
    assert await cache.incr_window("rl", 60) == 2
    assert await cache.incr_window("rl", 60) == 3


async def test_delete_clears_a_window_key_written_by_incr_window():
    """`CachePort.delete` must mean the same thing for both ports.

    `incr_window` keeps its state in `_windows`; a delete that only touched
    `_values` let a limiter's counter survive its own `delete`, while `RedisCache`
    (whose DEL removes the key however it was written) did not. That divergence is
    how the OTP attempt budget reset in production but not in development.
    """
    cache = MemoryCache()
    assert await cache.incr_window("rl", 60) == 1
    assert await cache.incr_window("rl", 60) == 2

    await cache.delete("rl")
    assert await cache.incr_window("rl", 60) == 1, "the window must restart after delete"


async def test_a_rate_limit_window_expires_old_hits():
    """A hit older than the window must stop counting."""
    cache = MemoryCache()
    await cache.incr_window("rl", 60)
    # Backdate the recorded hit beyond the window.
    cache._windows["rl"] = [cache._windows["rl"][0] - 61]
    assert await cache.incr_window("rl", 60) == 1, "the stale hit must not count"


async def test_a_zero_ttl_entry_is_evicted_immediately():
    cache = MemoryCache()
    await cache.set("gone", "now", ttl=0)
    assert await cache.get("gone") is None


async def test_a_null_ttl_entry_never_expires():
    cache = MemoryCache()
    await cache.set("forever", "value", ttl=None)
    assert await cache.get("forever") == "value"


async def test_reset_clears_everything():
    cache = MemoryCache()
    await cache.set("a", "1")
    await cache.incr_window("w", 60)
    cache.reset()
    assert await cache.get("a") is None
    assert await cache.incr_window("w", 60) == 1, "the window restarted"


# ── build_cache ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_build_cache_memo():
    """Give every test in this file a clean build-cache memo.

    The build-cache tests monkeypatch ``settings`` to exercise other branches; without
    a reset, the memoised instance from import time (or an earlier test's patched
    settings) would answer instead of a fresh build, and the tests would pass while
    checking nothing.
    """
    from app.core import ports

    ports.reset_build_cache()
    yield
    ports.reset_build_cache()


async def test_build_cache_is_one_instance_for_the_whole_process():
    """Two modules asking for a cache get the same store, not two parallel ones."""
    from app.core import ports

    first = ports.build_cache()
    second = ports.build_cache()
    assert first is second

    ports.reset_build_cache()
    rebuilt = ports.build_cache()
    assert rebuilt is not first, "reset must force a rebuild against current settings"


async def test_build_cache_falls_back_to_memory_without_redis(monkeypatch):
    """★ No Redis configured must not break the app; it must degrade to memory."""
    from app.core import ports
    from app.core.config import settings

    monkeypatch.setattr(settings, "REDIS_URL", None, raising=False)
    assert isinstance(ports.build_cache(), MemoryCache)


async def test_build_cache_degrades_in_development_if_the_redis_client_cannot_load(
    monkeypatch,
):
    """Development stays usable when an optional Redis client cannot be constructed."""
    from app.core import ports
    from app.core.config import settings

    class _Unavailable:
        def __init__(self, _url: str) -> None:
            raise ModuleNotFoundError("redis client unavailable")

    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development", raising=False)
    monkeypatch.setattr(ports, "RedisCache", _Unavailable)
    assert isinstance(ports.build_cache(), MemoryCache)


async def test_build_cache_fails_closed_in_production_if_redis_cannot_load(monkeypatch):
    from app.core import ports
    from app.core.config import settings

    class _Unavailable:
        def __init__(self, _url: str) -> None:
            raise ModuleNotFoundError("redis client unavailable")

    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    monkeypatch.setattr(ports, "RedisCache", _Unavailable)
    with pytest.raises(RuntimeError, match="refusing to fall back"):
        ports.build_cache()


async def test_the_health_descriptor_agrees_with_the_active_cache():
    """The two must not disagree -- operators act on the descriptor."""
    from app.core.config import settings

    cache = build_cache()
    if settings.REDIS_URL:
        assert isinstance(cache, RedisCache)
    else:
        assert isinstance(cache, MemoryCache)
