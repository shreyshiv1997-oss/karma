# FIXED: Real-time tickets are atomically consumed and production fanout crosses workers.
"""Post-commit WebSocket fanout for the gig lifecycle.

Routes never publish inside their database transaction. They buffer :class:`Event` objects on
the SQLAlchemy session; ``session_scope`` publishes them only after commit. Development uses an
in-process hub. Production uses the same local socket hub plus Redis Pub/Sub, so an event
created by worker A reaches sockets attached to workers B, C, and D.

The WebSocket handshake exchanges the JWT for a short-lived, single-use ticket. Browsers cannot
attach an Authorization header to a WebSocket request, while putting the JWT itself in a query
string would leak it into proxy logs and browser history.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from inspect import isawaitable
from typing import Any, Protocol
from uuid import uuid4

from fastapi import WebSocket

from app.core.config import settings
from app.core.ports import build_cache

log = logging.getLogger(__name__)

_SEND_TIMEOUT_S = 5.0
TICKET_TTL_S = 30
MAX_CONNECTIONS_PER_USER = 8
_MAX_BUS_MESSAGE_BYTES = 65_536
_BUS_VERSION = 1


@dataclass(frozen=True)
class Event:
    """One namespaced lifecycle change in the client wire format."""

    type: str
    gig_id: int
    data: dict
    at: str

    @classmethod
    def of(cls, type_: str, gig_id: int, **data: object) -> Event:
        return cls(type=type_, gig_id=gig_id, data=data, at=_now())

    @classmethod
    def from_wire(cls, value: object) -> Event:
        """Validate an event received from the internal Redis bus.

        Redis is infrastructure, not a deserialization trust boundary. Refusing malformed or
        oversized shapes prevents one bad publisher from crashing every API worker.
        """
        if not isinstance(value, dict):
            raise TypeError("event must be an object")
        type_ = value.get("type")
        gig_id = value.get("gig_id")
        data = value.get("data")
        at = value.get("at")
        if not isinstance(type_, str) or not type_ or len(type_) > 100:
            raise ValueError("event type is invalid")
        if type(gig_id) is not int or gig_id <= 0:  # bool is intentionally not an id
            raise ValueError("event gig_id is invalid")
        if not isinstance(data, dict) or any(not isinstance(key, str) for key in data):
            raise ValueError("event data is invalid")
        if not isinstance(at, str) or not at or len(at) > 64:
            raise ValueError("event timestamp is invalid")
        return cls(type=type_, gig_id=gig_id, data=data, at=at)

    def to_wire(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RealtimePort(Protocol):
    """The process-local socket API shared by memory and Redis implementations."""

    published: list[Event]

    @property
    def is_ready(self) -> bool: ...
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def connect(self, gig_id: int, user_id: int, websocket: WebSocket) -> bool: ...
    async def disconnect(self, gig_id: int, user_id: int, websocket: WebSocket) -> None: ...
    async def publish(self, event: Event) -> int: ...
    async def publish_many(self, events: Iterable[Event]) -> None: ...
    def channel_size(self, gig_id: int) -> int: ...
    def total_connections(self) -> int: ...
    def reset(self) -> None: ...


class MemoryRealtime:
    """In-process fanout. One gig id maps to the sockets watching it."""

    def __init__(self) -> None:
        self._channels: dict[int, set[WebSocket]] = defaultdict(set)
        self._socket_users: dict[WebSocket, int] = {}
        self._per_user: dict[int, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        # Test/diagnostic history for this process. Redis hubs include local and remote events.
        self.published: list[Event] = []

    @property
    def is_ready(self) -> bool:
        return True

    async def start(self) -> None:
        """Memory has no external lifecycle."""

    async def close(self) -> None:
        """Memory has no external lifecycle."""

    async def connect(self, gig_id: int, user_id: int, websocket: WebSocket) -> bool:
        """Register a socket, enforcing the per-process per-user connection cap."""
        async with self._lock:
            if websocket in self._socket_users:
                return True
            if self._per_user[user_id] >= MAX_CONNECTIONS_PER_USER:
                return False
            self._channels[gig_id].add(websocket)
            self._socket_users[websocket] = user_id
            self._per_user[user_id] += 1
        return True

    async def disconnect(self, gig_id: int, user_id: int, websocket: WebSocket) -> None:
        del gig_id, user_id  # the registered mapping is authoritative and makes this idempotent
        async with self._lock:
            self._remove_socket(websocket)

    def _remove_socket(self, websocket: WebSocket) -> None:
        registered_user = self._socket_users.pop(websocket, None)
        for channel_id, sockets in list(self._channels.items()):
            sockets.discard(websocket)
            if not sockets:
                del self._channels[channel_id]
        if registered_user is not None:
            remaining = self._per_user[registered_user] - 1
            if remaining > 0:
                self._per_user[registered_user] = remaining
            else:
                self._per_user.pop(registered_user, None)

    def channel_size(self, gig_id: int) -> int:
        return len(self._channels.get(gig_id, ()))

    def total_connections(self) -> int:
        return len(self._socket_users)

    async def publish(self, event: Event) -> int:
        """Fan out concurrently and prune dead sockets without failing healthy recipients."""
        self.published.append(event)
        payload = event.to_wire()
        async with self._lock:
            recipients = list(self._channels.get(event.gig_id, ()))

        async def send(websocket: WebSocket) -> bool:
            try:
                await asyncio.wait_for(
                    websocket.send_json(payload), timeout=_SEND_TIMEOUT_S
                )
                return True
            except Exception:  # noqa: BLE001 - disconnects are expected during fanout
                return False

        accepted = await asyncio.gather(*(send(ws) for ws in recipients))
        dead = [ws for ws, delivered in zip(recipients, accepted, strict=True) if not delivered]
        if dead:
            async with self._lock:
                for websocket in dead:
                    self._remove_socket(websocket)
        return sum(accepted)

    async def publish_many(self, events: Iterable[Event]) -> None:
        for event in events:
            await self.publish(event)

    def reset(self) -> None:
        """Test hook: drop every socket and the process-local publication log."""
        self._channels.clear()
        self._socket_users.clear()
        self._per_user.clear()
        self.published.clear()


class RedisRealtime(MemoryRealtime):
    """Redis Pub/Sub transport plus the same process-local socket hub.

    Every process subscribes to one deployment-namespaced channel. A publisher first sends an
    envelope to Redis and then fans out locally. Envelopes carry a random process id, so the
    publisher's own subscriber ignores the echo and each local socket receives the event once.

    Redis Pub/Sub is intentionally ephemeral: a disconnected client gets a fresh database
    snapshot when it reconnects. Durable replay would require a stream and per-client offsets,
    which is a different product contract.
    """

    def __init__(
        self,
        url: str,
        *,
        channel: str,
        redis_client: Any | None = None,
    ) -> None:
        super().__init__()
        if redis_client is None:
            import redis.asyncio as aioredis

            redis_client = aioredis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=5,
                health_check_interval=30,
            )
        self._redis = redis_client
        self._channel = channel
        self._origin = uuid4().hex
        self._listener: asyncio.Task[None] | None = None
        self._start_lock = asyncio.Lock()
        self._ready = False
        self._closing = False
        self._closed = False

    @property
    def is_ready(self) -> bool:
        return self._ready and self._listener is not None and not self._listener.done()

    async def start(self) -> None:
        """Ping and subscribe before the application is declared started."""
        async with self._start_lock:
            if self._closed:
                raise RuntimeError("Redis realtime hub is closed")
            if self._listener is not None and not self._listener.done():
                return
            self._closing = False
            await self._redis.ping()
            pubsub = await self._subscribe()
            self._ready = True
            self._listener = asyncio.create_task(
                self._listen(pubsub), name=f"redis-realtime-{self._origin[:8]}"
            )

    async def _subscribe(self):
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(self._channel)
        except Exception:
            await _close_async(pubsub)
            raise
        return pubsub

    async def _listen(self, pubsub) -> None:
        backoff = 0.25
        try:
            while not self._closing:
                try:
                    async for message in pubsub.listen():
                        if self._closing:
                            break
                        if message.get("type") != "message":
                            continue
                        decoded = self._decode(message.get("data"))
                        if decoded is None:
                            continue
                        origin, event = decoded
                        if origin != self._origin:
                            await super().publish(event)
                    if not self._closing:
                        raise ConnectionError("Redis Pub/Sub listener ended")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._ready = False
                    log.exception("Redis realtime subscription lost; reconnecting")
                finally:
                    await _close_async(pubsub)

                while not self._closing:
                    await asyncio.sleep(backoff)
                    try:
                        pubsub = await self._subscribe()
                        self._ready = True
                        backoff = 0.25
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        log.warning("Redis realtime resubscribe failed", exc_info=True)
                        backoff = min(backoff * 2, 5.0)
        finally:
            self._ready = False
            await _close_async(pubsub)

    def _decode(self, raw: object) -> tuple[str, Event] | None:
        try:
            if isinstance(raw, bytes):
                if len(raw) > _MAX_BUS_MESSAGE_BYTES:
                    raise ValueError("message is too large")
                raw = raw.decode("utf-8")
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_BUS_MESSAGE_BYTES:
                raise ValueError("message is invalid or too large")
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or envelope.get("v") != _BUS_VERSION:
                raise ValueError("envelope version is invalid")
            origin = envelope.get("origin")
            if not isinstance(origin, str) or not origin or len(origin) > 64:
                raise ValueError("envelope origin is invalid")
            return origin, Event.from_wire(envelope.get("event"))
        except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
            log.warning("Ignored malformed Redis realtime event")
            return None

    async def publish(self, event: Event) -> int:
        if self._listener is None or self._listener.done():
            await self.start()
        envelope = json.dumps(
            {"v": _BUS_VERSION, "origin": self._origin, "event": event.to_wire()},
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if len(envelope.encode("utf-8")) > _MAX_BUS_MESSAGE_BYTES:
            raise ValueError("Realtime event exceeds the Redis message limit")
        try:
            await self._redis.publish(self._channel, envelope)
        except Exception:
            # Local sockets still receive the committed state. Other workers' clients will
            # refresh from the database on reconnect; do not turn a successful mutation into
            # a misleading HTTP 500 after its transaction has committed.
            log.exception("Redis realtime publish failed after database commit")
        return await super().publish(event)

    async def close(self) -> None:
        async with self._start_lock:
            if self._closed:
                return
            self._closing = True
            self._ready = False
            task = self._listener
            self._listener = None
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await _close_async(self._redis)
            self._closed = True


async def _close_async(value: object) -> None:
    close = getattr(value, "aclose", None) or getattr(value, "close", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result


def build_realtime() -> RealtimePort:
    if settings.REDIS_URL:
        return RedisRealtime(
            settings.REDIS_URL,
            channel=settings.REALTIME_REDIS_CHANNEL,
        )
    if settings.is_production:  # pragma: no cover - configuration rejects this first
        raise RuntimeError("REDIS_URL is required for production realtime fanout")
    return MemoryRealtime()


# Imported by the router and by the post-commit session lifecycle.
realtime: RealtimePort = build_realtime()
_cache = build_cache()


# ── tickets ───────────────────────────────────────────────────────────────────
async def issue_ticket(user_id: int) -> str:
    """Mint a single-use handshake token bound to one user."""
    ticket = secrets.token_urlsafe(24)
    await _cache.set(_ticket_key(ticket), str(user_id), ttl=TICKET_TTL_S)
    return ticket


async def redeem_ticket(ticket: str) -> int | None:
    """Consume a ticket exactly once, including across worker processes.

    ``MemoryCache`` performs the read/remove without an intervening await; ``RedisCache`` uses
    GETDEL. A leaked query-string ticket therefore loses every replay race after its first use.
    """
    if not ticket:
        return None
    raw = await _cache.get_and_delete(_ticket_key(ticket))
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _ticket_key(ticket: str) -> str:
    return f"karma:rt:ticket:{ticket}"


# ── buffering on the SQLAlchemy session ──────────────────────────────────────
_BUFFER_KEY = "realtime_events"


def queue_event(session, event: Event) -> None:
    """Attach an event to the session for post-commit publication."""
    session.info.setdefault(_BUFFER_KEY, []).append(event)


def drain_events(session) -> list[Event]:
    """Take and clear whatever is queued on this session."""
    return session.info.pop(_BUFFER_KEY, [])


async def flush(session) -> None:
    """Publish queued events. The session lifecycle calls this only after a successful commit."""
    events = drain_events(session)
    if events:
        await realtime.publish_many(events)
