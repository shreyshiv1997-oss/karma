import { inr, ledgerDate, relative } from '../src/utils/format'

describe('inr', () => {
  it('formats with en-IN grouping', () => {
    expect(inr(1234.5)).toBe('₹1,235')
    expect(inr(1234.5, 2)).toBe('₹1,234.50')
    expect(inr(100000)).toBe('₹1,00,000')
  })
})

describe('relative', () => {
  const now = new Date('2026-09-14T12:00:00Z')

  it('counts up from "just now" through days', () => {
    expect(relative('2026-09-14T11:59:30Z', now)).toBe('just now')
    expect(relative('2026-09-14T11:30:00Z', now)).toBe('30m')
    expect(relative('2026-09-14T05:00:00Z', now)).toBe('7h')
    expect(relative('2026-09-01T12:00:00Z', now)).toBe('13d')
  })

  it('switches to a date, adding the year only when it differs', () => {
    const sameYear = relative('2026-05-01T00:00:00Z', now)
    expect(sameYear).not.toMatch(/2026/)
    const otherYear = relative('2024-05-01T00:00:00Z', now)
    expect(otherYear).toMatch(/2024/)
  })

  it('renders empty for garbage', () => {
    expect(relative('not-a-date', now)).toBe('')
  })
})

describe('ledgerDate', () => {
  it('always carries the year — it is the audit trail', () => {
    const out = ledgerDate('2026-09-14T12:00:00Z')
    expect(out).toMatch(/2026/)
  })
})
