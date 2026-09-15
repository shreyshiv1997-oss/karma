import { colors } from '../theme/tokens'

export type KarmaBand = 'dormant' | 'building' | 'trusted' | 'proven'

/**
 * The karma gradient, as data:
 *
 *   0 ─────── 40 ─────── 70 ─────── 100
 *  rose ──── amber ──── lime ──── karma-gold
 *  dormant   building    trusted    proven
 */
export function karmaBand(value: number): KarmaBand {
  if (value >= 85) return 'proven'
  if (value >= 70) return 'trusted'
  if (value >= 40) return 'building'
  return 'dormant'
}

export function karmaHue(value: number): string {
  switch (karmaBand(value)) {
    case 'proven':
      return colors.karmaProven
    case 'trusted':
      return colors.karmaTrusted
    case 'building':
      return colors.karmaBuilding
    default:
      return colors.karmaDormant
  }
}

export function clampKarma(value: number): number {
  return Math.max(0, Math.min(100, value))
}

export const DOMAIN_LABEL: Record<string, string> = {
  trust: 'Trust',
  work: 'Work',
  social: 'Social',
  migration: 'Migration',
}

export const DOMAIN_COLOR: Record<string, string> = {
  trust: colors.karmaGold,
  work: colors.lime,
  social: colors.violet,
  migration: colors.textFaint,
}
