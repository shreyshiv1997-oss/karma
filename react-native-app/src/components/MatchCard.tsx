import React, { useRef, useState } from 'react'
import { Animated, Pressable, Text, View } from 'react-native'
import { Avatar, TierBadge } from './Avatar'
import { Button, Card } from './primitives'
import { KarmaRing } from './KarmaRing'
import { colors, radii, space } from '../theme/tokens'
import type { Candidate } from '../api/types'

/**
 * The Match Card — explainability as design.
 *
 * Every ranked worker arrives with human-readable `reasons[]` from the
 * backend scorer. They are shown verbatim, never paraphrased: "never show a
 * number you cannot justify" is the product's whole strategy. The match
 * score and the worker's karma ring travel with the card, so the hiring
 * decision and its audit trail share one surface.
 */

type Props = {
  candidate: Candidate
  onBook?: (candidate: Candidate) => void
  booked?: boolean
  busy?: boolean
}

export function MatchCard({ candidate, onBook, booked, busy }: Props) {
  const [expanded, setExpanded] = useState(false)
  const chevron = useRef(new Animated.Value(0)).current

  const toggle = () => {
    const next = expanded ? 0 : 90
    Animated.timing(chevron, {
      toValue: next,
      duration: 120,
      useNativeDriver: true,
    }).start()
    setExpanded((v) => !v)
  }

  return (
    <Card style={{ padding: space.s4, gap: space.s3 }}>
      <View style={{ flexDirection: 'row', gap: space.s3, alignItems: 'center' }}>
        <Avatar name={candidate.display_name} url={candidate.avatar_url} />
        <View style={{ flex: 1, minWidth: 0, gap: 3 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <Text style={{ fontSize: 16, fontWeight: '600', color: colors.text, flexShrink: 1 }} numberOfLines={1}>
              {candidate.display_name}
            </Text>
            <TierBadge tier={candidate.verification_tier} />
          </View>
          <Text style={{ fontSize: 13, color: colors.textMuted }}>
            {candidate.total_jobs} jobs · ★ {candidate.rating.toFixed(1)} · {candidate.distance_km} km · ETA{' '}
            {candidate.eta_minutes} min
          </Text>
        </View>
        <View style={{ alignItems: 'center', flexShrink: 0 }}>
          <KarmaRing value={candidate.karma} size={40} label={`${candidate.display_name}, karma ${candidate.karma}`} />
          <Text style={{ fontSize: 10.5, color: colors.textFaint, marginTop: 2 }}>
            {Math.round(candidate.score)} match
          </Text>
        </View>
      </View>

      {/* Why this match — the explainability contract. */}
      <Pressable
        onPress={toggle}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        style={{ flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 4 }}
      >
        <Animated.Text
          style={{
            transform: [{ rotate: `rotate(${chevron}deg)` }],
            color: colors.textMuted,
            fontWeight: '700',
            fontSize: 13,
          }}
        >
          ›
        </Animated.Text>
        <Text style={{ fontSize: 12.5, fontWeight: '600', color: colors.textMuted, textTransform: 'uppercase', letterSpacing: 0.3 }}>
          Why this match
        </Text>
      </Pressable>

      {expanded && (
        <View style={{ gap: 3, paddingLeft: 20 }}>
          {candidate.reasons.map((reason) => (
            <View key={reason} style={{ flexDirection: 'row', gap: 6, alignItems: 'flex-start' }}>
              <Text style={{ color: colors.lime, fontWeight: '700' }} accessibilityElementsHidden>
                ✓
              </Text>
              <Text style={{ fontSize: 14, color: colors.text, flex: 1 }}>{reason}</Text>
            </View>
          ))}
        </View>
      )}

      {candidate.proof_count > 0 && (
        <Text style={{ fontSize: 12.5, color: colors.textFaint }}>
          {candidate.proof_count} verified proof{candidate.proof_count === 1 ? '' : 's'} of work on profile
        </Text>
      )}

      {onBook && (
        <View style={{ flexDirection: 'row', gap: space.s2 }}>
          <Button
            label={booked ? 'Booked ✓' : 'Book now'}
            onPress={() => onBook(candidate)}
            disabled={booked || busy}
            style={{ flex: 1 }}
          />
        </View>
      )}
    </Card>
  )
}
