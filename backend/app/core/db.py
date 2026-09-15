"""Async engine, declarative base and session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Single declarative base for the whole canonical schema."""


_connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ECHO_SQL,
    future=True,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def session_scope(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """The request lifecycle, defined once.

    Commit on success, roll back on failure, and publish any queued real-time events only
    *after* the commit has actually returned. Publishing from inside the handler would let a
    client be told a gig changed state and then watch the transaction roll back. A rollback
    drops the queue, which is right: nothing happened, so nothing is announced.

    Tests override the session *factory*, not this lifecycle, so the post-commit ordering
    that production depends on is the same ordering the tests exercise. Reimplementing it in
    `conftest` is how it silently stopped being tested.

    The realtime import is local to avoid a cycle (services.realtime -> core.ports ->
    core.config).
    """
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        from app.services.realtime import drain_events

        drain_events(session)  # discard; the state change they described was undone
        raise

    from app.services.realtime import flush

    await flush(session)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """The session factory, as a dependency.

    WebSocket routes cannot use the request-scoped :func:`get_session` for their whole
    lifetime -- that would hold a database session open for as long as the socket stays up.
    Instead they depend on the *factory* and open short-lived sessions only when they need
    to read. Tests override this to point at their in-memory database; the previous version
    imported ``SessionLocal`` directly, so the authorisation query silently ran against the
    real database and every socket test was refused with 4403.
    """
    return SessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request. Delegates the lifecycle to :func:`session_scope`."""
    async with SessionLocal() as session:
        async for value in session_scope(session):
            yield value


async def init_db() -> None:
    """Create tables. Production uses Alembic; this is the dev/test path."""
    from app import models  # noqa: F401  (register mappers)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
