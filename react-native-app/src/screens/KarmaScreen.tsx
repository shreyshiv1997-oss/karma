import React, { useEffect, useState } from 'react'
import { ScrollView, Text, View } from 'react-native'
import { get } from '../api/client'
import type { KarmaLedger } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { KarmaRing } from '../components/KarmaRing'
import { Card, ErrorText, SectionTitle, Skeleton } from '../components/primitives'
import { colors, space } from '../theme/tokens'
import { DOMAIN_COLOR, DOMAIN_LABEL, karmaBand, karmaHue } from '../utils/karma'
import { ledgerDate } from '../utils/format'

/**
 * The Karma Ledger — the audit trail behind the number.
 *
 * The split view is the honesty mechanism: you can see that social
 * popularity is not the same as work reputation, and exactly how the two
 * blend. That is the UI answer to "can I farm social karma to get hired?" —
 * no, and here is why, in public.
 */

export function KarmaScreen() {
  const { user } = useAuth()
  const [ledger, setLedger] = useState<KarmaLedger | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    get<KarmaLedger>('/karma/ledger')
      .then(setLedger)
      .catch((err: Error) => setError(err.message))
  }, [])

  if (error) return <ErrorText>{error}</ErrorText>

  if (!ledger) {
    return (
      <View style={{ padding: space.s4, flex: 1, backgroundColor: colors.paper }}>
        <Skeleton height={320} radius={16} />
      </View>
    )
  }

  const band = karmaBand(ledger.blended)

  return (
    <ScrollView
      contentContainerStyle={{ padding: space.s4, gap: space.s4, paddingBottom: space.s7 }}
      style={{ backgroundColor: colors.paper, flex: 1 }}
    >
      <Card style={{ padding: space.s5, alignItems: 'center', gap: space.s2 }}>
        <KarmaRing value={ledger.blended} size={88} label={`Karma ${ledger.blended} of 100, ${band}`} />
        <Text style={{ fontSize: 22, fontWeight: '700', color: colors.text, marginTop: space.s2 }}>
          {band.charAt(0).toUpperCase() + band.slice(1)}
        </Text>
        <Text style={{ fontSize: 14, color: colors.textMuted }}>
          {user?.display_name} · @{user?.handle}
        </Text>
      </Card>

      {/* The split — marketplace trust and social reputation, shown separately. */}
      <Card style={{ padding: space.s5, gap: space.s4 }}>
        <SectionTitle>How it blends</SectionTitle>
        <Meter label="Work karma" value={ledger.work} weight="60%" color={colors.lime} />
        <Meter label="Social karma" value={ledger.social} weight="40%" color={colors.violet} />
        <View style={{ height: 1, backgroundColor: colors.line }} />
        <Meter label="Blended" value={ledger.blended} color={karmaHue(ledger.blended)} strong />
        <Text style={{ fontSize: 12.5, color: colors.textFaint, lineHeight: 19 }}>
          Work is weighted higher than social, because trusting someone in your home should
          depend on their work record — not on how popular they are.
        </Text>
      </Card>

      {/* The ledger itself. Append-only, auditable. */}
      <Card style={{ padding: space.s5 }}>
        <SectionTitle style={{ marginBottom: space.s3 }}>
          Ledger · {ledger.total_events} event{ledger.total_events === 1 ? '' : 's'}
        </SectionTitle>
        {ledger.events.map((event) => (
          <View
            key={event.id}
            style={{
              flexDirection: 'row',
              gap: space.s3,
              alignItems: 'flex-start',
              paddingVertical: 10,
              borderBottomWidth: 1,
              borderBottomColor: colors.line,
            }}
          >
            <Text
              style={{
                width: 40,
                flexShrink: 0,
                fontWeight: '700',
                fontSize: 14,
                color: event.delta > 0 ? colors.lime : event.delta < 0 ? colors.rose : colors.textFaint,
              }}
            >
              {event.delta > 0 ? `+${event.delta}` : event.delta}
            </Text>
            <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
              <Text style={{ fontSize: 14.5, color: colors.text, lineHeight: 21 }}>{event.reason}</Text>
              <Text style={{ fontSize: 12, color: colors.textFaint }}>
                <Text style={{ color: DOMAIN_COLOR[event.domain] }}>
                  {DOMAIN_LABEL[event.domain] ?? event.domain}
                </Text>
                {' · '}
                {ledgerDate(event.created_at)}
              </Text>
            </View>
          </View>
        ))}
        {ledger.truncated && (
          <Text style={{ color: colors.textFaint, fontSize: 12.5, paddingTop: space.s3 }}>
            Showing the {ledger.events.length} most recent of {ledger.total_events}.
          </Text>
        )}
        {ledger.total_events === 0 && (
          <Text style={{ color: colors.textMuted, paddingVertical: space.s4 }}>
            No events yet. Verify your phone to earn your first karma.
          </Text>
        )}
      </Card>
    </ScrollView>
  )
}

function Meter({
  label,
  value,
  weight,
  color,
  strong,
}: {
  label: string
  value: number
  weight?: string
  color: string
  strong?: boolean
}) {
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 5 }}>
        <Text style={{ fontSize: 14, fontWeight: strong ? '600' : '400', color: colors.text }}>
          {label}
          {weight ? (
            <Text style={{ color: colors.textFaint, fontSize: 12.5 }}> · {weight} of blend</Text>
          ) : null}
        </Text>
        <Text style={{ fontWeight: '700', fontSize: strong ? 20 : 16, color }}>{value}</Text>
      </View>
      <View
        accessibilityRole="progressbar"
        accessibilityLabel={`${label}: ${value} of 100`}
        style={{ height: strong ? 8 : 6, backgroundColor: colors.surface2, borderRadius: 999, overflow: 'hidden' }}
      >
        <View
          style={{
            height: '100%',
            width: `${clamped}%`,
            backgroundColor: color,
            borderRadius: 999,
          }}
        />
      </View>
    </View>
  )
}
