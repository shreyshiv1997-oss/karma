"""Stripe PaymentIntents, signed webhooks and secured gig-payment release."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.models.marketplace import Gig
from app.models.payments import GigPayment, StripeWebhookEvent
from app.models.user import User
from app.schemas.payments import (
    PaymentOut,
    PaymentRefundIn,
    StripeWebhookAck,
)
from app.services.fare import split_payout
from app.services.payment_workflows import (
    apply_provider_intent,
    apply_succeeded_refund,
    lock_payment,
    minor_from_money,
    payment_out,
    settle_captured_payment,
)
from app.services.payments import (
    PaymentGateway,
    PaymentProviderError,
    ProviderRefund,
    get_payment_gateway,
    intent_from_webhook_object,
)
from app.services.realtime import Event, queue_event

router = APIRouter(prefix="/payments", tags=["Payments"])
PaymentGatewayDep = Annotated[PaymentGateway, Depends(get_payment_gateway)]
_MAX_WEBHOOK_BYTES = 262_144


def _provider_failure(exc: PaymentProviderError) -> HTTPException:
    code = status.HTTP_409_CONFLICT if exc.code in {"canceled", "card_declined"} else 502
    return HTTPException(status_code=code, detail=str(exc))


async def _locked_gig(session, gig_id: int) -> Gig:
    gig = await session.scalar(select(Gig).where(Gig.id == gig_id).with_for_update())
    if gig is None:
        raise HTTPException(status_code=404, detail="Gig not found")
    return gig


async def _lock_provider_payment(
    session, intent_id: str
) -> tuple[GigPayment | None, Gig | None]:
    """Lock gig then payment, matching every API workflow's lock order.

    Looking up the gig id is deliberately non-locking. Acquiring the payment first would invert
    the release path's order and let a webhook race deadlock with customer approval.
    """
    gig_id = await session.scalar(
        select(GigPayment.gig_id).where(
            GigPayment.provider_payment_intent_id == intent_id
        )
    )
    if gig_id is None:
        return None, None
    gig = await session.scalar(select(Gig).where(Gig.id == gig_id).with_for_update())
    if gig is None:
        return None, None
    payment = await session.scalar(
        select(GigPayment)
        .where(GigPayment.provider_payment_intent_id == intent_id)
        .with_for_update()
    )
    return payment, gig


def _require_party(gig: Gig, user: User) -> None:
    if user.id not in {gig.customer_id, gig.worker_id} and "admin" not in set(
        user.capabilities or []
    ):
        raise HTTPException(status_code=404, detail="Payment not found")


@router.post("/gigs/{gig_id}/intent", response_model=PaymentOut)
async def create_or_resume_intent(
    gig_id: int,
    user: CurrentUser,
    session: SessionDep,
    gateway: PaymentGatewayDep,
) -> PaymentOut:
    """Create one fixed-price, manual-capture PaymentIntent for the gig's customer."""
    gig = await _locked_gig(session, gig_id)
    if gig.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Only the customer can secure payment")
    # Escrow opens once a worker is chosen. `completion_pending` is admitted for one reason:
    # a long job can outlive its card authorization (uncaptured holds expire at the provider),
    # and refusing here would strand finished work unpaid -- the canceled-intent replacement
    # below is then the only way money can move forward again.
    if gig.worker_id is None or gig.status not in {"assigned", "completion_pending"}:
        raise HTTPException(
            status_code=409,
            detail="Payment is secured after assignment and before work begins",
        )

    payment = await lock_payment(session, gig.id)
    if payment is not None:
        try:
            intent = await gateway.retrieve_intent(payment.provider_payment_intent_id)
        except PaymentProviderError as exc:
            # Some providers answer a terminal cancellation with the object, some with an
            # error; both spell the same thing below.
            if exc.code != "canceled":
                raise _provider_failure(exc) from exc
            intent = None
        if intent is not None and intent.status != "canceled":
            apply_provider_intent(payment, gig, intent)
            await session.flush()
            return payment_out(
                payment,
                client_secret=intent.client_secret,
                publishable_key=gateway.publishable_key,
            )

        # A canceled intent is terminal. Returning its client_secret would hand the customer
        # an object they can never confirm, on a gig no other endpoint could move: /release
        # captures nothing canceled, and this route kept serving the same dead intent
        # forever. Mint a replacement and re-key the row. The idempotency key names the
        # corpse, so a request that crashed before the re-key committed recomputes this key
        # on retry and the provider returns the replacement it already made.
        try:
            intent = await gateway.create_intent(
                amount_minor=minor_from_money(payment.amount),
                currency=payment.currency,
                gig_id=gig.id,
                customer_id=user.id,
                worker_id=gig.worker_id,
                receipt_email=user.email,
                idempotency_key=f"karma:gig:{gig.id}:intent:replace:{payment.provider_payment_intent_id}",
            )
        except PaymentProviderError as exc:
            raise _provider_failure(exc) from exc
        payment.provider_payment_intent_id = intent.id
        payment.authorized_at = None  # the replacement holds no authorization yet
        apply_provider_intent(payment, gig, intent)
        await session.flush()
        queue_event(
            session,
            Event.of(
                "gig.payment_updated",
                gig.id,
                status=gig.status,
                payment_status=gig.payment_status,
            ),
        )
        return payment_out(
            payment,
            client_secret=intent.client_secret,
            publishable_key=gateway.publishable_key,
        )

    amount = Decimal(str(gig.total)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise HTTPException(status_code=409, detail="Gig amount must be positive")
    split = split_payout(float(amount), settings.PLATFORM_FEE_RATE)
    try:
        intent = await gateway.create_intent(
            amount_minor=minor_from_money(amount),
            currency=settings.PAYMENT_CURRENCY,
            gig_id=gig.id,
            customer_id=user.id,
            worker_id=gig.worker_id,
            receipt_email=user.email,
            idempotency_key=f"karma:gig:{gig.id}:intent:v1",
        )
    except PaymentProviderError as exc:
        raise _provider_failure(exc) from exc

    payment = GigPayment(
        gig_id=gig.id,
        customer_id=user.id,
        worker_id=gig.worker_id,
        provider=gateway.provider_name,
        provider_payment_intent_id=intent.id,
        provider_status=intent.status,
        status="requires_payment",
        amount=amount,
        platform_fee=Decimal(str(split["platform_fee"])),
        worker_payout=Decimal(str(split["worker_payout"])),
        currency=settings.PAYMENT_CURRENCY,
    )
    session.add(payment)
    apply_provider_intent(payment, gig, intent)
    await session.flush()
    queue_event(
        session,
        Event.of(
            "gig.payment_updated",
            gig.id,
            status=gig.status,
            payment_status=gig.payment_status,
        ),
    )
    return payment_out(
        payment,
        client_secret=intent.client_secret,
        publishable_key=gateway.publishable_key,
    )


@router.get("/gigs/{gig_id}", response_model=PaymentOut)
async def payment_status(
    gig_id: int,
    user: CurrentUser,
    session: SessionDep,
) -> PaymentOut:
    gig = await _locked_gig(session, gig_id)
    _require_party(gig, user)
    payment = await lock_payment(session, gig.id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment_out(payment)


@router.post("/gigs/{gig_id}/sync", response_model=PaymentOut)
async def sync_payment(
    gig_id: int,
    user: CurrentUser,
    session: SessionDep,
    gateway: PaymentGatewayDep,
) -> PaymentOut:
    """Retrieve Stripe server-side after PaymentSheet; never trust a client success flag."""
    gig = await _locked_gig(session, gig_id)
    _require_party(gig, user)
    payment = await lock_payment(session, gig.id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    try:
        intent = await gateway.retrieve_intent(payment.provider_payment_intent_id)
    except PaymentProviderError as exc:
        raise _provider_failure(exc) from exc
    apply_provider_intent(payment, gig, intent)
    if intent.status == "succeeded":
        await settle_captured_payment(session, payment, gig)
    await session.flush()
    return payment_out(payment)


@router.post("/gigs/{gig_id}/release", response_model=PaymentOut)
async def release_payment(
    gig_id: int,
    user: CurrentUser,
    session: SessionDep,
    gateway: PaymentGatewayDep,
) -> PaymentOut:
    """Customer approval captures the authorization and atomically releases the ledger payout."""
    gig = await _locked_gig(session, gig_id)
    if gig.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Only the customer can release payment")
    if gig.status not in {"completion_pending", "completed"}:
        raise HTTPException(status_code=409, detail="The worker has not submitted completion")
    payment = await lock_payment(session, gig.id)
    if payment is None:
        raise HTTPException(status_code=409, detail="No secured payment exists")
    if payment.released_at is not None:
        return payment_out(payment)

    try:
        intent = await gateway.retrieve_intent(payment.provider_payment_intent_id)
        if intent.status == "requires_capture":
            intent = await gateway.capture_intent(
                payment.provider_payment_intent_id,
                idempotency_key=f"karma:gig:{gig.id}:capture:v1",
            )
    except PaymentProviderError as exc:
        raise _provider_failure(exc) from exc
    apply_provider_intent(payment, gig, intent)
    if intent.status != "succeeded":
        await session.flush()
        raise HTTPException(
            status_code=409,
            detail=(
                # Expired holds are the common case on long jobs; the way forward is the
                # replacement intent POST /payments/gigs/{id}/intent now mints.
                "The authorization was cancelled; secure the payment again to reopen it."
                if intent.status == "canceled"
                else "Stripe capture is still processing; the signed webhook will reconcile it"
            ),
        )
    await settle_captured_payment(session, payment, gig)
    await session.flush()
    return payment_out(payment)


@router.post("/gigs/{gig_id}/refund", response_model=PaymentOut)
async def refund_payment(
    gig_id: int,
    payload: PaymentRefundIn,
    admin_user: AdminUser,
    session: SessionDep,
    gateway: PaymentGatewayDep,
) -> PaymentOut:
    """Trust administrators can issue a full provider refund after dispute review."""
    del admin_user
    gig = await _locked_gig(session, gig_id)
    payment = await lock_payment(session, gig.id)
    if payment is None or payment.released_at is None:
        raise HTTPException(status_code=409, detail="Only a released payment can be refunded")
    if payment.refunded_at is not None:
        return payment_out(payment)
    try:
        refund = await gateway.refund_intent(
            payment.provider_payment_intent_id,
            gig_id=gig.id,
            idempotency_key=f"karma:gig:{gig.id}:refund:v1",
        )
    except PaymentProviderError as exc:
        raise _provider_failure(exc) from exc
    await apply_succeeded_refund(session, payment, gig, refund)
    payment.failure_message = f"Admin refund: {payload.reason}"[:240]
    await session.flush()
    return payment_out(payment)


def _event_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


@router.post("/webhooks/stripe", response_model=StripeWebhookAck)
async def stripe_webhook(
    request: Request,
    session: SessionDep,
    gateway: PaymentGatewayDep,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> StripeWebhookAck:
    """Verify the raw body before parsing and process Stripe's at-least-once events once."""
    if stripe_signature is None:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature")
    body = await request.body()
    if len(body) > _MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Stripe webhook body is too large")
    try:
        event = gateway.construct_webhook_event(body, stripe_signature)
    except PaymentProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    event_id = str(_event_value(event, "id", ""))
    event_type = str(_event_value(event, "type", ""))
    event_created = int(_event_value(event, "created", 0) or 0)
    data = _event_value(event, "data", {})
    obj = _event_value(data, "object", {})
    object_id = str(_event_value(obj, "id", "")) or None
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Malformed Stripe event")

    if await session.get(StripeWebhookEvent, event_id) is not None:
        return StripeWebhookAck(duplicate=True)
    receipt = StripeWebhookEvent(
        id=event_id,
        event_type=event_type,
        provider_created=event_created,
        object_id=object_id,
        status="processing",
    )
    session.add(receipt)
    try:
        await session.flush()
    except IntegrityError:
        # A concurrent delivery won the primary-key race. This request has not done any
        # business work yet, so resetting its transaction is safe and leaves the winner's
        # receipt as the single source of truth.
        await session.rollback()
        return StripeWebhookAck(duplicate=True)

    if event_type.startswith("payment_intent.") and object_id is not None:
        payment, gig = await _lock_provider_payment(session, object_id)
        if payment is not None and gig is not None:
            intent = intent_from_webhook_object(obj)
            applied = apply_provider_intent(
                payment,
                gig,
                intent,
                event_created=event_created,
            )
            if applied and intent.status == "succeeded":
                await settle_captured_payment(session, payment, gig)
            if applied:
                queue_event(
                    session,
                    Event.of(
                        "gig.payment_updated",
                        gig.id,
                        status=gig.status,
                        payment_status=gig.payment_status,
                    ),
                )
    elif event_type in {"refund.created", "refund.updated"} and object_id is not None:
        intent_id = str(_event_value(obj, "payment_intent", ""))
        payment, gig = await _lock_provider_payment(session, intent_id)
        if payment is not None and gig is not None:
            refund = ProviderRefund(
                id=object_id,
                status=str(_event_value(obj, "status", "pending")),
                payment_intent_id=intent_id,
            )
            await apply_succeeded_refund(session, payment, gig, refund)

    receipt.status = "processed"
    receipt.processed_at = datetime.now(UTC)
    await session.flush()
    return StripeWebhookAck()
