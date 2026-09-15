"""Redis Pub/Sub fanout across independent API-worker hubs."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from uuid import uuid4

import pytest

from app.services.realtime import Event, RedisRealtime

pytestmark = pytest.mark.asyncio
_CHANNEL = "karma:test:realtime:v1"
_STOP = object()


class _Broker:
    def __init__(self) -> None:
        self.subscribers: set[_PubSub] = set()

    async def publish(self, channel: str, data: str) -> int:
        recipients = [item for item in self.subscribers if channel in item.channels]
        for item in recipients:
            await item.messages.put(
                {"type": "message", "channel": channel, "data": data}
            )
        return len(recipients)


class _PubSub:
    def __init__(self, broker: _Broker) -> None:
        self.broker = broker
        self.channels: set[str] = set()
        self.messages: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.channels.add(channel)
        self.broker.subscribers.add(self)

    async def listen(self):
        while not self.closed:
            message = await self.messages.get()
            if message is _STOP:
                return
            yield message

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.broker.subscribers.discard(self)
        await self.messages.put(_STOP)


class _Redis:
    def __init__(
        self,
        broker: _Broker,
        *,
        ping_error: Exception | None = None,
        publish_error: Exception | None = None,
    ) -> None:
        self.broker = broker
        self.ping_error = ping_error
        self.publish_error = publish_error
        self.closed = False
        self.pubsubs: list[_PubSub] = []

    async def ping(self) -> bool:
        if self.ping_error is not None:
            raise self.ping_error
        return True

    def pubsub(self) -> _PubSub:
        pubsub = _PubSub(self.broker)
        self.pubsubs.append(pubsub)
        return pubsub

    async def publish(self, channel: str, data: str) -> int:
        if self.publish_error is not None:
            raise self.publish_error
        return await self.broker.publish(channel, data)

    async def aclose(self) -> None:
        self.closed = True


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.received = asyncio.Event()

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)
        self.received.set()


async def _hubs(broker: _Broker) -> tuple[RedisRealtime, RedisRealtime]:
    first = RedisRealtime(
        "redis://unused",
        channel=_CHANNEL,
        redis_client=_Redis(broker),
    )
    second = RedisRealtime(
        "redis://unused",
        channel=_CHANNEL,
        redis_client=_Redis(broker),
    )
    await first.start()
    await second.start()
    return first, second


async def _close(*hubs: RedisRealtime) -> None:
    for hub in hubs:
        with suppress(Exception):
            await hub.close()


async def test_event_from_wire_rejects_untrusted_bus_shapes():
    valid = Event.of("gig.status_changed", 7, status="arrived")
    assert Event.from_wire(valid.to_wire()) == valid

    for malformed in (
        None,
        [],
        {"type": "", "gig_id": 7, "data": {}, "at": "now"},
        {"type": "gig.changed", "gig_id": True, "data": {}, "at": "now"},
        {"type": "gig.changed", "gig_id": 0, "data": {}, "at": "now"},
        {"type": "gig.changed", "gig_id": 7, "data": [], "at": "now"},
        {"type": "gig.changed", "gig_id": 7, "data": {}, "at": None},
    ):
        with pytest.raises((TypeError, ValueError)):
            Event.from_wire(malformed)


async def test_one_worker_publishes_to_sockets_on_another_worker():
    broker = _Broker()
    first, second = await _hubs(broker)
    local = _Socket()
    remote = _Socket()
    wrong_gig = _Socket()
    try:
        await first.connect(9, 100, local)
        await second.connect(9, 101, remote)
        await second.connect(10, 102, wrong_gig)

        event = Event.of("gig.status_changed", 9, status="in_progress")
        assert await first.publish(event) == 1
        await asyncio.wait_for(remote.received.wait(), timeout=1)
        await asyncio.sleep(0)

        assert local.sent == [event.to_wire()]
        assert remote.sent == [event.to_wire()]
        assert wrong_gig.sent == []
        # The origin envelope is ignored by worker A's subscriber because worker A already
        # delivered locally. An own-process socket must never receive the same event twice.
        assert first.published == [event]
        assert second.published == [event]
    finally:
        await _close(first, second)


async def test_malformed_bus_message_is_ignored_without_killing_subscription():
    broker = _Broker()
    first, second = await _hubs(broker)
    remote = _Socket()
    try:
        await second.connect(3, 20, remote)
        await broker.publish(_CHANNEL, "not-json")
        await asyncio.sleep(0)
        assert remote.sent == []
        assert second.is_ready is True

        valid = Event.of("gig.assigned", 3, worker_id=20)
        await first.publish(valid)
        await asyncio.wait_for(remote.received.wait(), timeout=1)
        assert remote.sent == [valid.to_wire()]
    finally:
        await _close(first, second)


async def test_startup_fails_if_redis_cannot_be_reached():
    redis = _Redis(_Broker(), ping_error=ConnectionError("redis refused"))
    hub = RedisRealtime("redis://unused", channel=_CHANNEL, redis_client=redis)
    with pytest.raises(ConnectionError, match="redis refused"):
        await hub.start()
    assert hub.is_ready is False
    await hub.close()
    assert redis.closed is True


async def test_lost_subscription_reconnects_and_resumes_remote_fanout():
    broker = _Broker()
    sender_redis = _Redis(broker)
    receiver_redis = _Redis(broker)
    sender = RedisRealtime("redis://unused", channel=_CHANNEL, redis_client=sender_redis)
    receiver = RedisRealtime("redis://unused", channel=_CHANNEL, redis_client=receiver_redis)
    remote = _Socket()

    async def wait_for_resubscribe() -> None:
        while len(receiver_redis.pubsubs) < 2 or not receiver.is_ready:
            await asyncio.sleep(0.01)

    try:
        await sender.start()
        await receiver.start()
        await receiver.connect(12, 8, remote)
        await receiver_redis.pubsubs[0].aclose()
        await asyncio.wait_for(wait_for_resubscribe(), timeout=1)

        event = Event.of("gig.status_changed", 12, status="in_progress")
        await sender.publish(event)
        await asyncio.wait_for(remote.received.wait(), timeout=1)
        assert remote.sent == [event.to_wire()]
    finally:
        await _close(sender, receiver)


async def test_publish_outage_still_delivers_locally_after_commit():
    redis = _Redis(_Broker(), publish_error=ConnectionError("redis dropped"))
    hub = RedisRealtime("redis://unused", channel=_CHANNEL, redis_client=redis)
    socket = _Socket()
    try:
        await hub.start()
        await hub.connect(5, 30, socket)
        event = Event.of("gig.status_changed", 5, status="arrived")

        # Redis loss is logged, but a mutation that has already committed is not reported as
        # an HTTP failure and sockets on this worker still get the authoritative state.
        assert await hub.publish(event) == 1
        assert socket.sent == [event.to_wire()]
    finally:
        await hub.close()


async def test_oversized_event_is_refused_before_publish():
    redis = _Redis(_Broker())
    hub = RedisRealtime("redis://unused", channel=_CHANNEL, redis_client=redis)
    try:
        await hub.start()
        event = Event.of("gig.status_changed", 1, value="x" * 70_000)
        with pytest.raises(ValueError, match="message limit"):
            await hub.publish(event)
        assert hub.published == []
    finally:
        await hub.close()


@pytest.mark.skipif(
    not os.getenv("TEST_REDIS_URL"),
    reason="set TEST_REDIS_URL to exercise a live Redis server",
)
async def test_two_real_redis_clients_bridge_independent_worker_hubs():
    url = os.environ["TEST_REDIS_URL"]
    channel = f"karma:test:realtime:{uuid4().hex}"
    first = RedisRealtime(url, channel=channel)
    second = RedisRealtime(url, channel=channel)
    remote = _Socket()
    try:
        await first.start()
        await second.start()
        await second.connect(77, 2, remote)
        event = Event.of("gig.status_changed", 77, status="arrived")
        await first.publish(event)
        await asyncio.wait_for(remote.received.wait(), timeout=2)
        assert remote.sent == [event.to_wire()]
    finally:
        await _close(first, second)
