import { clampKarma, karmaBand, karmaHue } from '../src/utils/karma'
import { colors } from '../src/theme/tokens'

describe('karmaBand', () => {
  it('maps the full range to its four bands', () => {
    expect(karmaBand(0)).toBe('dormant')
    expect(karmaBand(39.9)).toBe('dormant')
    expect(karmaBand(40)).toBe('building')
    expect(karmaBand(69.9)).toBe('building')
    expect(karmaBand(70)).toBe('trusted')
    expect(karmaBand(84.9)).toBe('trusted')
    expect(karmaBand(85)).toBe('proven')
    expect(karmaBand(100)).toBe('proven')
  })
})

describe('karmaHue', () => {
  it('walks the gradient rose → amber → lime → gold', () => {
    expect(karmaHue(0)).toBe(colors.karmaDormant)
    expect(karmaHue(40)).toBe(colors.karmaBuilding)
    expect(karmaHue(70)).toBe(colors.karmaTrusted)
    expect(karmaHue(85)).toBe(colors.karmaProven)
  })
})

describe('clampKarma', () => {
  it('never renders outside 0..100', () => {
    expect(clampKarma(-12)).toBe(0)
    expect(clampKarma(55.5)).toBe(55.5)
    expect(clampKarma(999)).toBe(100)
  })
})
