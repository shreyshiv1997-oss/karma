"""Public payment contracts. Card and PaymentMethod data deliberately do not appear here."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PaymentOut(BaseModel):
    gig_id: int
    provider: str
    status: str
    amount: float
    platform_fee: float
    worker_payout: float
    currency: str
    payment_intent_id: str
    client_secret: str | None = None
    publishable_key: str | None = None
    authorized_at: datetime | None = None
    captured_at: datetime | None = None
    released_at: datetime | None = None
    refunded_at: datetime | None = None
    failure_message: str | None = None


class PaymentRefundIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


class StripeWebhookAck(BaseModel):
    received: Literal[True] = True
    duplicate: bool = False
