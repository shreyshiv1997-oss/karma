"""Secured-payment invariants: authorization, capture, webhooks and refunds.

The simulator exercises the same durable workflow as Stripe without accepting card data. Signed
webhook tests use Stripe's real signature format and always sign the exact bytes sent over HTTP.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.marketplace import Gig
from app.models.payments import GigPayment, StripeWebhookEvent
from app.models.social import Post
from app.models.trust import LedgerEntry, Wallet
from app.models.user import User
from app.services.payments import StripePaymentGateway, get_payment_gateway
from tests.conftest import add_category, auth, make_worker, register_user

pytestmark = pytest.mark.asyncio
_WEBHOOK_SECRET = "whsec_karma_test"


async def _assigned_gig(client, session_factory, *, suffix: str = ""):
    category_id = await add_category(session_factory)
    customer = await register_user(client, handle=f"priya{suffix}")
    granted = await client.post(
        "/api/v1/auth/capability/can_hire", headers=auth(customer["token"])
    )
    assert granted.status_code == 200, granted.text
    worker = await make_worker(
        client,
        session_factory,
        handle=f"ramesh{suffix}",
        category_id=category_id,
    )
    posted = await client.post(
        "/api/v1/gigs",
        headers=auth(customer["token"]),
        json={
            "category_id": category_id,
            "title": "Repair the service panel",
            "description": "Breaker trips under load.",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 2,
        },
    )
    assert posted.status_code == 201, posted.text
    gig_id = posted.json()["id"]
    assigned = await client.post(
        f"/api/v1/gigs/{gig_id}/assign",
        params={"worker_id": worker["user_id"]},
        headers=auth(customer["token"]),
    )
    assert assigned.status_code == 200, assigned.text
    return customer, worker, gig_id, assigned.json()


async def _authorize(client, customer, gig_id: int) -> dict:
    response = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/intent",
        headers=auth(customer["token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "authorized"
    return response.json()


async def _submit_completion(client, worker, gig_id: int) -> None:
    for state in ("en_route", "arrived", "in_progress", "completion_pending"):
        response = await client.post(
            f"/api/v1/gigs/{gig_id}/status",
            headers=auth(worker["token"]),
            json={
                "status": state,
                "proof_photos": [],
            },
        )
        assert response.status_code == 200, f"{state}: {response.text}"


def _signed_event(
    *,
    event_id: str,
    event_type: str,
    created: int,
    object_data: dict,
) -> tuple[bytes, str]:
    payload = json.dumps(
        {
            "id": event_id,
            "object": "event",
            "created": created,
            "type": event_type,
            "data": {"object": object_data},
        },
        separators=(",", ":"),
    ).encode()
    timestamp = int(time.time())
    digest = hmac.new(
        _WEBHOOK_SECRET.encode(),
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    return payload, f"t={timestamp},v1={digest}"


async def _post_event(client, payload: bytes, signature: str):
    return await client.post(
        "/api/v1/payments/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )


def _intent_object(payment: dict, *, status: str, charge: str | None = None) -> dict:
    value = {
        "id": payment["payment_intent_id"],
        "object": "payment_intent",
        "amount": int((Decimal(str(payment["amount"])) * 100).to_integral_exact()),
        "currency": payment["currency"].lower(),
        "status": status,
    }
    if charge is not None:
        value["latest_charge"] = charge
    return value


async def test_stripe_gateway_creates_manual_capture_intent_with_idempotency(monkeypatch):
    seen: dict = {}

    async def fake_create_async(**kwargs):
        seen.update(kwargs)
        return {
            "id": "pi_real_contract",
            "status": "requires_payment_method",
            "amount": 12345,
            "currency": "inr",
            "client_secret": "pi_real_contract_secret_test",
        }

    monkeypatch.setattr(
        "app.services.payments.stripe.PaymentIntent.create_async",
        fake_create_async,
    )
    gateway = StripePaymentGateway("sk_test_contract", "pk_test_contract", "whsec_contract")
    intent = await gateway.create_intent(
        amount_minor=12345,
        currency="INR",
        gig_id=42,
        customer_id=7,
        worker_id=9,
        receipt_email="priya@example.com",
        idempotency_key="karma:gig:42:intent:v1",
    )

    assert intent.id == "pi_real_contract"
    assert seen["api_key"] == "sk_test_contract"
    assert seen["idempotency_key"] == "karma:gig:42:intent:v1"
    assert seen["capture_method"] == "manual"
    assert seen["payment_method_types"] == ["card"]
    assert seen["amount"] == 12345
    assert seen["currency"] == "inr"
    assert seen["metadata"] == {
        "karma_gig_id": "42",
        "karma_customer_id": "7",
        "karma_worker_id": "9",
    }


async def test_authorization_is_required_and_one_intent_is_resumed(
    client, session_factory
):
    customer, worker, gig_id, gig = await _assigned_gig(client, session_factory)

    premature = await client.post(
        f"/api/v1/gigs/{gig_id}/status",
        headers=auth(worker["token"]),
        json={"status": "en_route"},
    )
    assert premature.status_code == 409
    assert "authorize" in premature.json()["detail"].lower()

    worker_attempt = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/intent",
        headers=auth(worker["token"]),
    )
    assert worker_attempt.status_code == 403

    first = await _authorize(client, customer, gig_id)
    second = await _authorize(client, customer, gig_id)
    assert second["payment_intent_id"] == first["payment_intent_id"]
    assert first["amount"] == gig["total"]
    assert first["currency"] == "INR"
    assert first["client_secret"] is None  # simulator never invents card-facing secrets

    outsider = await register_user(client, handle="outsider")
    hidden = await client.get(
        f"/api/v1/payments/gigs/{gig_id}", headers=auth(outsider["token"])
    )
    assert hidden.status_code == 404

    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(GigPayment))
        ) == 1

    permitted = await client.post(
        f"/api/v1/gigs/{gig_id}/status",
        headers=auth(worker["token"]),
        json={"status": "en_route"},
    )
    assert permitted.status_code == 200, permitted.text


async def test_worker_proof_cannot_move_money_and_duplicate_release_is_exactly_once(
    client, session_factory
):
    customer, worker, gig_id, _ = await _assigned_gig(client, session_factory)
    payment = await _authorize(client, customer, gig_id)
    await _submit_completion(client, worker, gig_id)

    async with session_factory() as session:
        assert await session.get(Wallet, worker["user_id"]) is None
        assert await session.scalar(
            select(func.count()).select_from(LedgerEntry).where(LedgerEntry.gig_id == gig_id)
        ) == 0
        assert await session.scalar(
            select(func.count()).select_from(Post).where(Post.gig_id == gig_id)
        ) == 0

    first = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/release",
        headers=auth(customer["token"]),
    )
    second = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/release",
        headers=auth(customer["token"]),
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "paid"
    assert datetime.fromisoformat(first.json()["released_at"]).replace(
        tzinfo=None
    ) == datetime.fromisoformat(second.json()["released_at"]).replace(tzinfo=None)

    async with session_factory() as session:
        stored = await session.scalar(select(GigPayment).where(GigPayment.gig_id == gig_id))
        wallet = await session.get(Wallet, worker["user_id"])
        entries = (
            await session.execute(
                select(LedgerEntry).where(LedgerEntry.gig_id == gig_id)
            )
        ).scalars().all()
        assert stored.provider_status == "succeeded"
        assert Decimal(wallet.balance) == Decimal(str(payment["worker_payout"]))
        assert [entry.entry_type for entry in entries] == ["payout", "fee"]
        assert len({entry.external_reference for entry in entries}) == 2
        assert all(payment["payment_intent_id"] in entry.external_reference for entry in entries)
        assert await session.scalar(
            select(func.count()).select_from(Post).where(Post.gig_id == gig_id)
        ) == 1


async def test_webhook_requires_a_valid_exact_body_signature_and_deduplicates(
    client, session_factory
):
    customer, worker, gig_id, _ = await _assigned_gig(client, session_factory)
    payment = await _authorize(client, customer, gig_id)
    await _submit_completion(client, worker, gig_id)
    created = int(time.time())
    payload, signature = _signed_event(
        event_id="evt_payment_succeeded",
        event_type="payment_intent.succeeded",
        created=created,
        object_data=_intent_object(payment, status="succeeded", charge="ch_webhook"),
    )

    missing = await client.post(
        "/api/v1/payments/webhooks/stripe",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert missing.status_code == 400
    invalid = await _post_event(client, payload + b" ", signature)
    assert invalid.status_code == 400

    accepted = await _post_event(client, payload, signature)
    duplicate = await _post_event(client, payload, signature)
    assert accepted.status_code == duplicate.status_code == 200
    assert accepted.json() == {"received": True, "duplicate": False}
    assert duplicate.json() == {"received": True, "duplicate": True}

    async with session_factory() as session:
        stored = await session.scalar(select(GigPayment).where(GigPayment.gig_id == gig_id))
        receipt = await session.get(StripeWebhookEvent, "evt_payment_succeeded")
        gig = await session.get(Gig, gig_id)
        assert stored.status == "paid"
        assert gig.status == "completed"
        assert receipt.status == "processed"
        assert receipt.processed_at is not None
        assert await session.scalar(
            select(func.count()).select_from(StripeWebhookEvent)
        ) == 1
        assert await session.scalar(
            select(func.count()).select_from(LedgerEntry).where(LedgerEntry.gig_id == gig_id)
        ) == 2


async def test_stale_webhook_cannot_regress_a_released_payment(client, session_factory):
    customer, worker, gig_id, _ = await _assigned_gig(client, session_factory)
    payment = await _authorize(client, customer, gig_id)
    await _submit_completion(client, worker, gig_id)
    current_created = int(time.time())
    current_body, current_signature = _signed_event(
        event_id="evt_current",
        event_type="payment_intent.succeeded",
        created=current_created,
        object_data=_intent_object(payment, status="succeeded", charge="ch_current"),
    )
    assert (await _post_event(client, current_body, current_signature)).status_code == 200

    stale_body, stale_signature = _signed_event(
        event_id="evt_stale",
        event_type="payment_intent.payment_failed",
        created=current_created - 60,
        object_data=_intent_object(payment, status="requires_payment_method"),
    )
    stale = await _post_event(client, stale_body, stale_signature)
    assert stale.status_code == 200, stale.text
    impossible_body, impossible_signature = _signed_event(
        event_id="evt_impossible_terminal_regression",
        event_type="payment_intent.payment_failed",
        created=current_created + 60,
        object_data=_intent_object(payment, status="requires_payment_method"),
    )
    impossible = await _post_event(client, impossible_body, impossible_signature)
    assert impossible.status_code == 200, impossible.text

    async with session_factory() as session:
        stored = await session.scalar(select(GigPayment).where(GigPayment.gig_id == gig_id))
        gig = await session.get(Gig, gig_id)
        assert stored.status == "paid"
        assert stored.provider_status == "succeeded"
        assert stored.last_event_created == current_created
        assert gig.status == "completed"
        assert gig.payment_status == "paid"
        assert await session.get(StripeWebhookEvent, "evt_stale") is not None


async def test_webhook_rejects_amount_mismatch_without_poisoning_the_event_id(
    client, session_factory
):
    customer, _worker, gig_id, _ = await _assigned_gig(client, session_factory)
    payment = await _authorize(client, customer, gig_id)
    obj = _intent_object(payment, status="requires_capture")
    obj["amount"] += 1
    payload, signature = _signed_event(
        event_id="evt_wrong_amount",
        event_type="payment_intent.amount_capturable_updated",
        created=int(time.time()),
        object_data=obj,
    )
    rejected = await _post_event(client, payload, signature)
    assert rejected.status_code == 409
    assert "amount" in rejected.json()["detail"].lower()

    async with session_factory() as session:
        assert await session.get(StripeWebhookEvent, "evt_wrong_amount") is None
        stored = await session.scalar(select(GigPayment).where(GigPayment.gig_id == gig_id))
        assert stored.status == "authorized"


async def test_capture_webhook_before_completion_reconciles_on_later_release(
    client, session_factory
):
    customer, worker, gig_id, _ = await _assigned_gig(client, session_factory)
    payment = await _authorize(client, customer, gig_id)

    # Model a Stripe/dashboard capture. Keeping the simulator authoritative state in sync makes
    # the later API request exercise the retrieve-succeeded path instead of capturing again.
    gateway = get_payment_gateway()
    captured = await gateway.capture_intent(
        payment["payment_intent_id"], idempotency_key="external:test:capture"
    )
    body, signature = _signed_event(
        event_id="evt_early_capture",
        event_type="payment_intent.succeeded",
        created=int(time.time()),
        object_data=_intent_object(payment, status=captured.status, charge=captured.charge_id),
    )
    early = await _post_event(client, body, signature)
    assert early.status_code == 200, early.text

    async with session_factory() as session:
        stored = await session.scalar(select(GigPayment).where(GigPayment.gig_id == gig_id))
        gig = await session.get(Gig, gig_id)
        assert stored.status == "captured"
        assert stored.released_at is None
        assert gig.status == "assigned"
        assert await session.scalar(
            select(func.count()).select_from(LedgerEntry).where(LedgerEntry.gig_id == gig_id)
        ) == 0

    await _submit_completion(client, worker, gig_id)
    released = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/release",
        headers=auth(customer["token"]),
    )
    assert released.status_code == 200, released.text
    assert released.json()["status"] == "paid"


async def test_cancelling_a_gig_cancels_the_uncaptured_authorization(
    client, session_factory
):
    customer, _worker, gig_id, _ = await _assigned_gig(client, session_factory)
    payment = await _authorize(client, customer, gig_id)
    cancelled = await client.post(
        f"/api/v1/gigs/{gig_id}/status",
        headers=auth(customer["token"]),
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["payment_status"] == "cancelled"

    provider = await get_payment_gateway().retrieve_intent(payment["payment_intent_id"])
    assert provider.status == "canceled"
    stored = await client.get(
        f"/api/v1/payments/gigs/{gig_id}", headers=auth(customer["token"])
    )
    assert stored.status_code == 200
    assert stored.json()["status"] == "cancelled"


async def test_admin_full_refund_reverses_the_wallet_and_is_idempotent(
    client, session_factory
):
    customer, worker, gig_id, _ = await _assigned_gig(client, session_factory)
    await _authorize(client, customer, gig_id)
    await _submit_completion(client, worker, gig_id)
    released = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/release",
        headers=auth(customer["token"]),
    )
    assert released.status_code == 200, released.text

    admin = await register_user(client, handle="trustadmin")
    async with session_factory() as session:
        user = await session.get(User, admin["user"]["id"])
        user.capabilities = [*list(user.capabilities or []), "admin"]
        await session.commit()

    first = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/refund",
        headers=auth(admin["token"]),
        json={"reason": "Dispute reviewed in the customer's favour"},
    )
    second = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/refund",
        headers=auth(admin["token"]),
        json={"reason": "Safe retry after a lost response"},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "refunded"
    assert datetime.fromisoformat(first.json()["refunded_at"]).replace(
        tzinfo=None
    ) == datetime.fromisoformat(second.json()["refunded_at"]).replace(tzinfo=None)
    reconciled = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/sync",
        headers=auth(customer["token"]),
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "refunded"

    async with session_factory() as session:
        wallet = await session.get(Wallet, worker["user_id"])
        entries = (
            await session.execute(
                select(LedgerEntry)
                .where(LedgerEntry.gig_id == gig_id)
                .order_by(LedgerEntry.id)
            )
        ).scalars().all()
        assert Decimal(wallet.balance) == Decimal(0)
        assert [entry.entry_type for entry in entries] == [
            "payout",
            "fee",
            "refund_debit",
            "refund",
        ]
        assert len({entry.external_reference for entry in entries}) == 4
        assert sum(1 for entry in entries if entry.entry_type == "refund_debit") == 1
        assert sum(1 for entry in entries if entry.entry_type == "refund") == 1


async def test_non_admin_cannot_refund(client, session_factory):
    customer, worker, gig_id, _ = await _assigned_gig(client, session_factory)
    await _authorize(client, customer, gig_id)
    await _submit_completion(client, worker, gig_id)
    await client.post(
        f"/api/v1/payments/gigs/{gig_id}/release",
        headers=auth(customer["token"]),
    )
    forbidden = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/refund",
        headers=auth(customer["token"]),
        json={"reason": "Trying to bypass dispute review"},
    )
    assert forbidden.status_code == 403
