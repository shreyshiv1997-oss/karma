"""Transactional payment state and Stripe-to-ledger reconciliation.

Stripe and the SQL database cannot share a transaction. These functions make every operation
retryable instead: provider calls use deterministic idempotency keys, webhook events are stored,
payment rows are locked, and ledger movements carry unique external references.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, update

from app.models.marketplace import Gig
from app.models.payments import GigPayment
from app.models.trust import Dispute, LedgerEntry, OPEN_DISPUTE_STATUSES, Wallet
from app.schemas.payments import PaymentOut
from app.services.payments import PaymentGateway, ProviderIntent, ProviderRefund
from app.services.realtime import Event, queue_event

_PROVIDER_TO_PUBLIC = {
    "requires_payment_method": "requires_payment",
    "requires_confirmation": "requires_payment",
    "requires_action": "requires_action",
    "processing": "processing",
    "requires_capture": "authorized",
    "canceled": "cancelled",
    "succeeded": "captured",
}


def money_from_minor(value: int) -> Decimal:
    return (Decimal(value) / Decimal(100)).quantize(Decimal("0.01"))


def minor_from_money(value: Decimal) -> int:
    quantized = Decimal(str(value)).quantize(Decimal("0.01"))
    return int(quantized * 100)


def payment_out(
    payment: GigPayment,
    *,
    client_secret: str | None = None,
    publishable_key: str | None = None,
) -> PaymentOut:
    return PaymentOut(
        gig_id=payment.gig_id,
        provider=payment.provider,
        status=payment.status,
        amount=float(payment.amount),
        platform_fee=float(payment.platform_fee),
        worker_payout=float(payment.worker_payout),
        currency=payment.currency,
        payment_intent_id=payment.provider_payment_intent_id,
        client_secret=client_secret,
        publishable_key=publishable_key,
        authorized_at=payment.authorized_at,
        captured_at=payment.captured_at,
        released_at=payment.released_at,
        refunded_at=payment.refunded_at,
        failure_message=payment.failure_message,
    )


def apply_provider_intent(
    payment: GigPayment,
    gig: Gig,
    intent: ProviderIntent,
    *,
    event_created: int | None = None,
) -> bool:
    """Apply a current provider snapshot; return False for an old webhook event."""
    if intent.id != payment.provider_payment_intent_id:
        raise HTTPException(status_code=409, detail="Payment identity mismatch")
    if intent.amount_minor != minor_from_money(payment.amount):
        raise HTTPException(status_code=409, detail="Stripe payment amount mismatch")
    if intent.currency.upper() != payment.currency.upper():
        raise HTTPException(status_code=409, detail="Stripe payment currency mismatch")
    if event_created is not None and event_created < payment.last_event_created:
        return False
    # A PaymentIntent remains `succeeded` after Stripe refunds it. Likewise, an impossible
    # delayed failure/cancellation event must never rewrite a locally released payment. Keep
    # these terminal business states while still accepting the authoritative intent snapshot.
    if (
        payment.released_at is not None
        and payment.refunded_at is None
        and intent.status != "succeeded"
    ):
        return False
    if event_created is not None:
        payment.last_event_created = event_created

    now = datetime.now(UTC)
    payment.provider_status = intent.status
    payment.provider_charge_id = intent.charge_id or payment.provider_charge_id
    payment.failure_code = intent.failure_code
    payment.failure_message = intent.failure_message
    if payment.refunded_at is not None:
        payment.status = "refunded"
        gig.payment_status = "refunded"
        return True
    if payment.released_at is not None:
        payment.status = "paid"
        gig.payment_status = "paid"
        return True

    public = _PROVIDER_TO_PUBLIC.get(intent.status, "failed")
    payment.status = public

    if public == "authorized":
        payment.authorized_at = payment.authorized_at or now
        gig.payment_status = "authorized"
    elif public in {"requires_payment", "requires_action", "processing"}:
        gig.payment_status = public
    elif public == "captured":
        payment.captured_at = payment.captured_at or now
        gig.payment_status = "captured"
    elif public == "cancelled":
        payment.cancelled_at = payment.cancelled_at or now
        gig.payment_status = "cancelled"
    else:
        gig.payment_status = "failed"
    return True


async def lock_payment(session, gig_id: int) -> GigPayment | None:
    return await session.scalar(
        select(GigPayment).where(GigPayment.gig_id == gig_id).with_for_update()
    )


async def settle_captured_payment(session, payment: GigPayment, gig: Gig) -> bool:
    """Release a captured authorization into proof, wallet and ledgers exactly once."""
    if payment.released_at is not None:
        return False
    if payment.provider_status != "succeeded":
        raise HTTPException(status_code=409, detail="Stripe has not captured this payment")
    if gig.status != "completion_pending":
        # A manual dashboard capture before work approval is money held by the platform, not
        # permission to mint proof or pay the worker. A later legitimate release retries this.
        return False

    # Either party's open case freezes the payout -- see OPEN_DISPUTE_STATUSES for why this list
    # and the filing limit in trust.raise_dispute are the same object.
    open_dispute = await session.scalar(
        select(Dispute.id).where(
            Dispute.gig_id == gig.id,
            Dispute.status.in_(OPEN_DISPUTE_STATUSES),
        )
    )
    if open_dispute is not None:
        raise HTTPException(status_code=409, detail="Payment is frozen while the dispute is open")

    # Local import avoids a router/service cycle. This is the existing audited fusion seam;
    # it now runs only after a provider-confirmed capture.
    from app.routers.gigs import _complete_gig

    await _complete_gig(
        gig,
        list(gig.proof_photos or []),
        session,
        payment_reference=payment.provider_payment_intent_id,
    )
    now = datetime.now(UTC)
    payment.status = "paid"
    payment.released_at = now
    gig.payment_status = "paid"
    queue_event(
        session,
        Event.of(
            "gig.payment_released",
            gig.id,
            status=gig.status,
            payment_status="paid",
            amount=float(payment.amount),
        ),
    )
    return True


async def cancel_gig_authorization(
    session,
    gig: Gig,
    gateway: PaymentGateway,
) -> None:
    payment = await lock_payment(session, gig.id)
    if payment is None or payment.status in {"cancelled", "refunded"}:
        gig.payment_status = "cancelled"
        return
    if payment.released_at is not None or payment.provider_status == "succeeded":
        raise HTTPException(
            status_code=409,
            detail="Captured payments must be resolved through the refund workflow",
        )
    intent = await gateway.cancel_intent(
        payment.provider_payment_intent_id,
        idempotency_key=f"karma:gig:{gig.id}:cancel:v1",
    )
    apply_provider_intent(payment, gig, intent)


async def apply_succeeded_refund(
    session,
    payment: GigPayment,
    gig: Gig,
    refund: ProviderRefund,
) -> bool:
    if payment.refunded_at is not None:
        return False
    if refund.payment_intent_id != payment.provider_payment_intent_id:
        raise HTTPException(status_code=409, detail="Refund payment identity mismatch")
    if refund.status != "succeeded":
        payment.status = "refund_pending"
        gig.payment_status = "refund_pending"
        payment.provider_refund_id = refund.id
        return False

    now = datetime.now(UTC)
    # The worker wallet is a cached projection of released payout rows. Refunds reverse the
    # available balance atomically; there is currently no cash-out path that can make it short.
    result = await session.execute(
        update(Wallet)
        .where(
            Wallet.user_id == payment.worker_id,
            Wallet.balance >= payment.worker_payout,
        )
        .values(balance=Wallet.balance - payment.worker_payout)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Worker wallet cannot cover this refund")

    session.add(
        LedgerEntry(
            user_id=payment.worker_id,
            entry_type="refund_debit",
            amount=-payment.worker_payout,
            gig_id=gig.id,
            external_reference=f"stripe:{payment.provider_payment_intent_id}:refund:worker",
            note=f"Refund reversal for gig #{gig.id}",
        )
    )
    session.add(
        LedgerEntry(
            user_id=payment.customer_id,
            entry_type="refund",
            amount=payment.amount,
            gig_id=gig.id,
            external_reference=f"stripe:{payment.provider_payment_intent_id}:refund:customer",
            note=f"Stripe refund for gig #{gig.id}",
        )
    )
    payment.provider_refund_id = refund.id
    payment.status = "refunded"
    payment.refunded_at = now
    gig.payment_status = "refunded"
    queue_event(
        session,
        Event.of(
            "gig.payment_refunded",
            gig.id,
            status=gig.status,
            payment_status="refunded",
            amount=float(payment.amount),
        ),
    )
    return True
