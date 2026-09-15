/**
 * The gig lifecycle, as a state machine.
 *
 * `assigned` is not an editable status from the outside — only
 * `/gigs/{id}/assign` enters it — which is why it is not in `WORKER_NEXT`'s
 * domain keys until the worker picks the gig up.
 */

export const GIG_STATUSES = [
  'searching',
  'assigned',
  'en_route',
  'arrived',
  'in_progress',
  'completion_pending',
  'completed',
  'cancelled',
] as const

export type GigStatus = (typeof GIG_STATUSES)[number]

/**
 * Narrow an untrusted status string coming off the wire. A cast would satisfy
 * the compiler and then put a nonsense value into state; ignoring an unknown
 * status is strictly safer — the rail falls back to the last state it trusts.
 */
export function asGigStatus(value: unknown): GigStatus | null {
  return typeof value === 'string' && (GIG_STATUSES as readonly string[]).includes(value)
    ? (value as GigStatus)
    : null
}

/** The lifecycle rail, in order. */
export const RAIL = [
  'assigned',
  'en_route',
  'arrived',
  'in_progress',
  'completion_pending',
  'completed',
] as const

/** The worker's legal next step, if any. */
export const WORKER_NEXT: Partial<Record<GigStatus, GigStatus>> = {
  assigned: 'en_route',
  en_route: 'arrived',
  arrived: 'in_progress',
  in_progress: 'completion_pending',
}

export const STATUS_LABELS: Record<string, string> = {
  searching: 'Searching',
  assigned: 'Assigned',
  en_route: 'On the way',
  arrived: 'Arrived',
  in_progress: 'Working',
  completion_pending: 'Awaiting approval',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

export function nextStatusLabel(status: string): string {
  const map: Record<string, string> = {
    assigned: 'Mark as on the way',
    en_route: 'Mark as arrived',
    arrived: 'Start work',
    in_progress: 'Submit completion proof',
  }
  return map[status] ?? 'Awaiting customer approval'
}

export function isTerminal(status: string): boolean {
  return status === 'completed' || status === 'cancelled'
}

export function isSecuredPayment(status: string): boolean {
  return status === 'authorized' || status === 'captured' || status === 'paid'
}

export function paymentLabel(status: string): string {
  const label: Record<string, string> = {
    requires_payment: 'payment required',
    requires_action: 'action required',
    processing: 'processing payment',
    authorized: 'payment secured',
    captured: 'payment captured',
    paid: 'paid',
    cancelled: 'payment cancelled',
    refunded: 'refunded',
  }
  return label[status] ?? status
}
