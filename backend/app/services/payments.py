"""Payment-provider boundary: Stripe in production, deterministic simulator in dev/test.

Only this module imports Stripe. Business workflows consume the small typed results below, which
keeps provider payloads and card details out of the database and makes failure handling testable.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol
from uuid import uuid4

import stripe

from app.core.config import settings


class PaymentProviderError(RuntimeError):
    """A safe, non-secret provider failure suitable for an API response."""

    def __init__(self, message: str, *, code: str = "provider_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProviderIntent:
    id: str
    status: str
    amount_minor: int
    currency: str
    client_secret: str | None = None
    charge_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class ProviderRefund:
    id: str
    status: str
    payment_intent_id: str


class PaymentGateway(Protocol):
    provider_name: str
    publishable_key: str | None

    async def create_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        gig_id: int,
        customer_id: int,
        worker_id: int,
        receipt_email: str | None,
        idempotency_key: str,
    ) -> ProviderIntent: ...

    async def retrieve_intent(self, intent_id: str) -> ProviderIntent: ...
    async def capture_intent(
        self, intent_id: str, *, idempotency_key: str
    ) -> ProviderIntent: ...
    async def cancel_intent(
        self, intent_id: str, *, idempotency_key: str
    ) -> ProviderIntent: ...
    async def refund_intent(
        self, intent_id: str, *, gig_id: int, idempotency_key: str
    ) -> ProviderRefund: ...
    def construct_webhook_event(self, payload: bytes, signature: str) -> dict[str, Any]: ...


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _intent(value: Any) -> ProviderIntent:
    latest_charge = _value(value, "latest_charge")
    if latest_charge is not None and not isinstance(latest_charge, str):
        latest_charge = _value(latest_charge, "id")
    last_error = _value(value, "last_payment_error")
    return ProviderIntent(
        id=str(_value(value, "id")),
        status=str(_value(value, "status")),
        amount_minor=int(_value(value, "amount", 0)),
        currency=str(_value(value, "currency", "")).upper(),
        client_secret=_value(value, "client_secret"),
        charge_id=latest_charge,
        failure_code=_value(last_error, "code") if last_error else None,
        failure_message=(
            str(_value(last_error, "message"))[:240] if last_error else None
        ),
    )


def intent_from_webhook_object(value: Any) -> ProviderIntent:
    """Normalize a verified Stripe event object through the same contract as API responses."""
    return _intent(value)


class StripePaymentGateway:
    provider_name = "stripe"

    def __init__(
        self,
        secret_key: str,
        publishable_key: str,
        webhook_secret: str,
    ) -> None:
        self._secret_key = secret_key
        self.publishable_key = publishable_key
        self._webhook_secret = webhook_secret

    @staticmethod
    def _raise_provider(exc: stripe.StripeError) -> PaymentProviderError:
        code = getattr(exc, "code", None) or "stripe_error"
        user_message = getattr(exc, "user_message", None)
        message = user_message or "Stripe could not process the payment. Please try again."
        return PaymentProviderError(str(message)[:240], code=str(code)[:80])

    async def create_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        gig_id: int,
        customer_id: int,
        worker_id: int,
        receipt_email: str | None,
        idempotency_key: str,
    ) -> ProviderIntent:
        try:
            result = await stripe.PaymentIntent.create_async(
                api_key=self._secret_key,
                idempotency_key=idempotency_key,
                amount=amount_minor,
                currency=currency.lower(),
                capture_method="manual",
                payment_method_types=["card"],
                description=f"KARMA gig #{gig_id}",
                metadata={
                    "karma_gig_id": str(gig_id),
                    "karma_customer_id": str(customer_id),
                    "karma_worker_id": str(worker_id),
                },
                receipt_email=receipt_email,
            )
        except stripe.StripeError as exc:
            raise self._raise_provider(exc) from exc
        return _intent(result)

    async def retrieve_intent(self, intent_id: str) -> ProviderIntent:
        try:
            result = await stripe.PaymentIntent.retrieve_async(
                intent_id,
                api_key=self._secret_key,
            )
        except stripe.StripeError as exc:
            raise self._raise_provider(exc) from exc
        return _intent(result)

    async def capture_intent(
        self, intent_id: str, *, idempotency_key: str
    ) -> ProviderIntent:
        try:
            intent = await stripe.PaymentIntent.retrieve_async(
                intent_id,
                api_key=self._secret_key,
            )
            result = await intent.capture_async(
                api_key=self._secret_key,
                idempotency_key=idempotency_key,
            )
        except stripe.StripeError as exc:
            raise self._raise_provider(exc) from exc
        return _intent(result)

    async def cancel_intent(
        self, intent_id: str, *, idempotency_key: str
    ) -> ProviderIntent:
        try:
            intent = await stripe.PaymentIntent.retrieve_async(
                intent_id,
                api_key=self._secret_key,
            )
            result = await intent.cancel_async(
                api_key=self._secret_key,
                idempotency_key=idempotency_key,
                cancellation_reason="requested_by_customer",
            )
        except stripe.StripeError as exc:
            raise self._raise_provider(exc) from exc
        return _intent(result)

    async def refund_intent(
        self, intent_id: str, *, gig_id: int, idempotency_key: str
    ) -> ProviderRefund:
        try:
            result = await stripe.Refund.create_async(
                api_key=self._secret_key,
                idempotency_key=idempotency_key,
                payment_intent=intent_id,
                reason="requested_by_customer",
                metadata={"karma_gig_id": str(gig_id)},
            )
        except stripe.StripeError as exc:
            raise self._raise_provider(exc) from exc
        return ProviderRefund(
            id=str(_value(result, "id")),
            status=str(_value(result, "status")),
            payment_intent_id=str(_value(result, "payment_intent", intent_id)),
        )

    def construct_webhook_event(self, payload: bytes, signature: str) -> dict[str, Any]:
        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                self._webhook_secret,
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise PaymentProviderError(
                "Invalid Stripe webhook signature", code="invalid_signature"
            ) from exc
        return event.to_dict()


class SimulatedPaymentGateway:
    """No-network development provider with the same authorization/capture state machine.

    The webhook secret has no default on purpose: see :func:`get_payment_gateway`. An
    un-configured simulator signs nothing, so its webhook route answers 400 to every event
    including one crafted from this source file.
    """

    provider_name = "simulated"
    publishable_key = None

    def __init__(self, webhook_secret: str) -> None:
        self._intents: dict[str, ProviderIntent] = {}
        self._by_gig: dict[int, str] = {}
        self._webhook_secret = webhook_secret

    async def create_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        gig_id: int,
        customer_id: int,
        worker_id: int,
        receipt_email: str | None,
        idempotency_key: str,
    ) -> ProviderIntent:
        del customer_id, worker_id, receipt_email, idempotency_key
        existing_id = self._by_gig.get(gig_id)
        if existing_id is not None:
            return self._intents[existing_id]
        intent_id = f"pi_sim_{gig_id}_{uuid4().hex}"
        result = ProviderIntent(
            id=intent_id,
            status="requires_capture",
            amount_minor=amount_minor,
            currency=currency.upper(),
        )
        self._intents[intent_id] = result
        self._by_gig[gig_id] = intent_id
        return result

    async def retrieve_intent(self, intent_id: str) -> ProviderIntent:
        try:
            return self._intents[intent_id]
        except KeyError as exc:
            raise PaymentProviderError("Simulated payment not found", code="not_found") from exc

    async def capture_intent(
        self, intent_id: str, *, idempotency_key: str
    ) -> ProviderIntent:
        del idempotency_key
        current = await self.retrieve_intent(intent_id)
        if current.status == "canceled":
            raise PaymentProviderError("The payment authorization was cancelled", code="canceled")
        result = ProviderIntent(
            id=current.id,
            status="succeeded",
            amount_minor=current.amount_minor,
            currency=current.currency,
            charge_id=current.charge_id or f"ch_sim_{uuid4().hex}",
        )
        self._intents[intent_id] = result
        return result

    async def cancel_intent(
        self, intent_id: str, *, idempotency_key: str
    ) -> ProviderIntent:
        del idempotency_key
        current = await self.retrieve_intent(intent_id)
        if current.status == "succeeded":
            return current
        result = ProviderIntent(
            id=current.id,
            status="canceled",
            amount_minor=current.amount_minor,
            currency=current.currency,
        )
        self._intents[intent_id] = result
        return result

    async def refund_intent(
        self, intent_id: str, *, gig_id: int, idempotency_key: str
    ) -> ProviderRefund:
        del gig_id, idempotency_key
        current = await self.retrieve_intent(intent_id)
        if current.status != "succeeded":
            raise PaymentProviderError("Only a captured payment can be refunded")
        return ProviderRefund(
            id=f"re_sim_{uuid4().hex}",
            status="succeeded",
            payment_intent_id=intent_id,
        )

    def construct_webhook_event(self, payload: bytes, signature: str) -> dict[str, Any]:
        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                self._webhook_secret,
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise PaymentProviderError(
                "Invalid Stripe webhook signature", code="invalid_signature"
            ) from exc
        return event.to_dict()

    def reset(self) -> None:
        self._intents.clear()
        self._by_gig.clear()


@lru_cache
def get_payment_gateway() -> PaymentGateway:
    if settings.PAYMENT_PROVIDER == "stripe":
        if (
            settings.STRIPE_SECRET_KEY is None
            or settings.STRIPE_PUBLISHABLE_KEY is None
            or settings.STRIPE_WEBHOOK_SECRET is None
        ):
            raise RuntimeError("Stripe payment settings are incomplete")
        return StripePaymentGateway(
            settings.STRIPE_SECRET_KEY.get_secret_value(),
            settings.STRIPE_PUBLISHABLE_KEY,
            settings.STRIPE_WEBHOOK_SECRET.get_secret_value(),
        )
    # A webhook secret is a *shared* secret, so the simulator must not ship one that is
    # written in this file. The signature-verification path is the same code in both
    # providers, and `payment_intent.succeeded` settles a payout -- so with a published
    # default, anything able to reach POST /payments/webhooks/stripe could mint a valid
    # signature and credit a wallet. `ENVIRONMENT` was never a safe gate for it: the setting
    # that silences this (PAYMENT_PROVIDER=simulated) is exactly the one a half-configured
    # staging box keeps, and that box then runs the open secret in production traffic.
    #
    # With no secret configured, the process generates an unguessable one at startup. Local
    # tooling that genuinely needs to inject an event reads it from its own environment; a
    # passer-by cannot derive it from the source tree.
    if settings.STRIPE_WEBHOOK_SECRET is not None:
        return SimulatedPaymentGateway(settings.STRIPE_WEBHOOK_SECRET.get_secret_value())
    return SimulatedPaymentGateway(secrets.token_urlsafe(32))
