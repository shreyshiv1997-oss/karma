/**
 * KARMA design tokens — the React Native half of the Sovereign Calm manifesto.
 *
 * Mirrored one-for-one from `frontend/src/theme/tokens.css`. Every colour pair
 * clears WCAG 2.1 AA on its intended background; the radii are the same three;
 * the motion budget is the same 120/220/320 ms with the same fast-out curve.
 */

export const colors = {
  /* surfaces */
  ink: '#0B0B0F',
  paper: '#FAFAF8',
  surface: '#FFFFFF',
  surface2: '#F4F3F0',
  line: '#E4E2DD',
  lineStrong: '#CFCDC4',

  /* text */
  text: '#0B0B0F',
  textMuted: '#5F5C55', // 4.9:1 on paper
  textFaint: '#7D7A72', // large text / decorative only

  /* brand */
  violet: '#7C3AED', // primary action only
  violetInk: '#5B21B6',
  violetWash: '#F5F0FF',
  karmaGold: '#B45309', // reputation, verification, trust
  cyan: '#0E7490', // live / realtime
  lime: '#4D7C0F', // success, completion, availability
  limeWash: '#F3F8EC',
  rose: '#BE123C', // danger, SOS, disputes
  roseWash: '#FDEEF1',
  cyanWash: '#EEF7FA',

  /* karma gradient stops — the one place maximalism is semantically earned */
  karmaDormant: '#BE123C',
  karmaBuilding: '#B45309',
  karmaTrusted: '#4D7C0F',
  karmaProven: '#92400E',

  /* tier tints */
  goldTint: '#FFF8ED',
  silverTint: '#F1F5F9',
  silverText: '#475569',
  bronzeTint: '#FBF3EA',
  bronzeText: '#7C5C3D',

  white: '#FFFFFF',
} as const

export const space = {
  s1: 4,
  s2: 8,
  s3: 12,
  s4: 16,
  s5: 24,
  s6: 32,
  s7: 48,
  s8: 64,
} as const

export const radii = {
  input: 8,
  card: 16,
  pill: 999,
} as const

/** Motion budget: 120 state / 220 entrance / 320 celebration. Nothing beyond. */
export const motion = {
  state: 120,
  enter: 220,
  celebrate: 320,
} as const

/** Fast out, gentle settle — cubic-bezier(0.32, 0.72, 0, 1). */
export const EASE = [0.32, 0.72, 0, 1] as const

export const typography = {
  /** 11.5–12.5 px eyebrow labels, uppercased, tracked. */
  eyebrow: 12,
  caption: 13,
  body: 15,
  title: 17,
  headline: 22,
} as const

export const tapMin = 44
