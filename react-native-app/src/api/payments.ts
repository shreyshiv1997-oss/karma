/**
 * The secured-payment flow, exactly as the backend defines it:
 *
 *   1. `POST /payments/gigs/{id}/intent` — one fixed-price PaymentIntent,
 *      `capture_method=manual`. Development's deterministic simulator returns
 *      an already-authorized payment and the loop continues with no card.
 *   2. Stripe mode: PaymentSheet confirms the card (card data never leaves
 *      Stripe's UI). Only then does the app call `POST .../sync`.
 *   3. `sync` is permitted to travel only when the intent is actually
 *      `requires_capture` (or already captured) — the backend verifies
 *      server-side.
 *   4. `POST .../release` captures after the customer approves the work.
 *
 * Release, refund and the release confirmation all live here so the Gigs
 * screen holds no payment knowledge beyond "it is secured or it is not".
 */

import Stripe from '@stripe/stripe-react-native'
import { post } from './client'
import type { GigPayment } from './types'
import { isSecuredPayment } from '../utils/gig'

export class PaymentFlowError extends Error {
  constructor(message: string) {
    super(message)
  }
}

let stripeReadyFor: string | null = null

async function ensureStripe(publishableKey: string): Promise<void> {
  if (stripeReadyFor !== publishableKey) {
    // The url scheme must match the `scheme` in app.json; a missing scheme
    // simply means redirect-based flows fall back to the sheet result, which
    // is all the manual-capture flow needs.
    await Stripe.initStripe({ publishableKey, urlScheme: 'karma' })
    stripeReadyFor = publishableKey
  }
}

/**
 * Secure the fixed price for an assigned gig. Resolves with the payment the
 * backend now reports. Throws `PaymentFlowError` with a human message when
 * the customer's card was declined or the flow was cancelled.
 *
 * Card data never leaves Stripe's UI: the sheet is set up with the intent's
 * client secret and presented; only the sheet's outcome crosses the wire, as
 * `POST .../sync`.
 */
export async function secureGigPayment(gigId: number): Promise<GigPayment> {
  const payment = await post<GigPayment>(`/payments/gigs/${gigId}/intent`)

  // The simulator (and any already-settled gig) needs no card at all.
  if (isSecuredPayment(payment.status)) return payment

  if (!payment.client_secret || !payment.publishable_key) {
    throw new PaymentFlowError(
      payment.failure_message ?? 'Payment setup is incomplete. Please try again.',
    )
  }

  await ensureStripe(payment.publishable_key)
  try {
    await Stripe.initPaymentSheet({
      paymentIntentClientSecret: payment.client_secret,
      merchantDisplayName: 'KARMA',
    })
    await Stripe.presentPaymentSheet()
  } catch (err) {
    const message =
      (err as { localizedMessage?: string; message?: string } | null)?.localizedMessage ??
      (err as { message?: string } | null)?.message ??
      'The payment was not authorised.'
    throw new PaymentFlowError(message)
  }

  const synced = await post<GigPayment>(`/payments/gigs/${gigId}/sync`)
  if (!isSecuredPayment(synced.status)) {
    throw new PaymentFlowError(synced.failure_message ?? 'Stripe is still processing. Please retry shortly.')
  }
  return synced
}

/** The customer approves the completed work; the capture happens here. */
export function releaseGigPayment(gigId: number): Promise<GigPayment> {
  return post<GigPayment>(`/payments/gigs/${gigId}/release`)
}
