import {
  asGigStatus,
  isSecuredPayment,
  isTerminal,
  nextStatusLabel,
  WORKER_NEXT,
} from '../src/utils/gig'

describe('asGigStatus', () => {
  it('accepts every legal status and narrows them', () => {
    expect(asGigStatus('searching')).toBe('searching')
    expect(asGigStatus('completion_pending')).toBe('completion_pending')
  })

  it('rejects anything else — an unknown status is ignored, never cast', () => {
    expect(asGigStatus('exploded')).toBeNull()
    expect(asGigStatus(42)).toBeNull()
    expect(asGigStatus(null)).toBeNull()
    expect(asGigStatus(undefined)).toBeNull()
  })
})

describe('WORKER_NEXT', () => {
  it('drives the worker through the lifecycle exactly once, in order', () => {
    expect(WORKER_NEXT.assigned).toBe('en_route')
    expect(WORKER_NEXT.en_route).toBe('arrived')
    expect(WORKER_NEXT.arrived).toBe('in_progress')
    expect(WORKER_NEXT.in_progress).toBe('completion_pending')
    expect(WORKER_NEXT.completion_pending).toBeUndefined()
    expect(WORKER_NEXT.completed).toBeUndefined()
    expect(WORKER_NEXT.cancelled).toBeUndefined()
    expect(WORKER_NEXT.searching).toBeUndefined()
  })
})

describe('nextStatusLabel', () => {
  it('labels each worker step, and everything else awaits approval', () => {
    expect(nextStatusLabel('assigned')).toBe('Mark as on the way')
    expect(nextStatusLabel('en_route')).toBe('Mark as arrived')
    expect(nextStatusLabel('arrived')).toBe('Start work')
    expect(nextStatusLabel('in_progress')).toBe('Submit completion proof')
    expect(nextStatusLabel('completion_pending')).toBe('Awaiting customer approval')
  })
})

describe('isTerminal / isSecuredPayment', () => {
  it('treats completed and cancelled as terminal', () => {
    expect(isTerminal('completed')).toBe(true)
    expect(isTerminal('cancelled')).toBe(true)
    expect(isTerminal('in_progress')).toBe(false)
  })

  it('treats authorized, captured and paid as secured', () => {
    expect(isSecuredPayment('authorized')).toBe(true)
    expect(isSecuredPayment('captured')).toBe(true)
    expect(isSecuredPayment('paid')).toBe(true)
    expect(isSecuredPayment('requires_payment')).toBe(false)
    expect(isSecuredPayment('processing')).toBe(false)
  })
})
