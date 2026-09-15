import React, { useRef } from 'react'
import { Animated, Text, View } from 'react-native'
import { colors } from '../theme/tokens'
import { inr } from '../utils/format'
import type { FareBreakdown as Breakdown } from '../api/types'

/**
 * Transparent pricing, rendered exactly as the backend computed it.
 *
 * Each multiplier shows as a labelled row only when it is active (≠ 1.0), so
 * the total never changes without explaining itself. Rows fade in when they
 * first appear — 220 ms, opacity only.
 */

export function FareBreakdownView({ fare, emphasis = 'total' }: { fare: Breakdown; emphasis?: 'none' | 'total' }) {
  const fade = useRef(new Animated.Value(0)).current
  React.useEffect(() => {
    Animated.timing(fade, { toValue: 1, duration: 220, useNativeDriver: true }).start()
  }, [fade])

  const activeMultipliers = [
    { key: 'skill', label: 'Skill tier', value: fare.skill_multiplier, hint: tierHint(fare.skill_multiplier) },
    { key: 'urgency', label: 'Urgent', value: fare.urgency_multiplier, hint: 'same-day dispatch' },
    { key: 'night', label: 'Night (22:00–06:00)', value: fare.night_multiplier, hint: 'out-of-hours' },
  ].filter((m) => m.value !== 1)

  return (
    <View style={{ gap: 6 }}>
      <Row label="Base fare" value={inr(fare.base_fare, 2)} />
      <Row label="Distance" value={inr(fare.distance_fare, 2)} />
      <Row label="Time" value={inr(fare.time_fare, 2)} />

      <Animated.View style={{ opacity: fade }}>
        {activeMultipliers.map((m) => (
          <Row key={m.key} label={m.label} value={`×${m.value.toFixed(2)}`} accent hint={m.hint} />
        ))}
      </Animated.View>

      <Separator />
      <Row label="Subtotal" value={inr(fare.subtotal, 2)} strong />
      <Row label="Platform fee (15%)" value={inr(fare.platform_fee, 2)} muted />
      <Separator />

      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', paddingTop: 2 }}>
        <Text style={{ fontSize: 15, fontWeight: '600', color: colors.text }}>Total</Text>
        <Text style={{ fontSize: emphasis === 'total' ? 24 : 20, fontWeight: '700', color: colors.text, letterSpacing: -0.4 }}>
          {inr(fare.total, 2)}
        </Text>
      </View>
    </View>
  )
}

function tierHint(multiplier: number): string {
  if (multiplier >= 1.18) return 'gold tier'
  if (multiplier >= 1.08) return 'silver tier'
  return 'standard tier'
}

function Row({
  label,
  value,
  muted,
  strong,
  accent,
  hint,
}: {
  label: string
  value: string
  muted?: boolean
  strong?: boolean
  accent?: boolean
  hint?: string
}) {
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
      <Text style={{ color: muted ? colors.textFaint : colors.textMuted, fontSize: 14, flexShrink: 1 }} numberOfLines={1}>
        {label}
        {hint ? (
          <Text style={{ color: colors.textFaint, fontSize: 12.5 }}> · {hint}</Text>
        ) : null}
      </Text>
      <Text
        style={{
          fontWeight: strong || accent ? '600' : '400',
          color: accent ? colors.karmaGold : colors.text,
          fontSize: 14.5,
        }}
      >
        {value}
      </Text>
    </View>
  )
}

function Separator() {
  return <View style={{ height: 1, backgroundColor: colors.line, marginVertical: 4 }} />
}
