import React from 'react'
import { Image, Text, View } from 'react-native'
import { colors, radii } from '../theme/tokens'

/** Initials circle when the user has no avatar — never a broken image. */
export function Avatar({ name, url, size = 44 }: { name: string; url: string | null; size?: number }) {
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()

  if (url) {
    return (
      <Image
        source={{ uri: url }}
        accessibilityLabel=""
        accessibilityElementsHidden
        style={{ width: size, height: size, borderRadius: radii.pill, flexShrink: 0 }}
      />
    )
  }

  return (
    <View
      accessibilityElementsHidden
      style={{
        width: size,
        height: size,
        borderRadius: radii.pill,
        backgroundColor: colors.surface2,
        borderWidth: 1,
        borderColor: colors.line,
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}
    >
      <Text style={{ fontSize: size * 0.36, fontWeight: '700', color: colors.textMuted }}>{initials}</Text>
    </View>
  )
}

/**
 * The verification tier. Document type is the tier: Aadhaar → gold, PAN →
 * silver, other government ID → bronze. The glyph differs so colour is never
 * the sole carrier of meaning.
 */
export function TierBadge({ tier }: { tier: string }) {
  if (!tier || tier === 'none') return null
  const label = tier === 'gold' ? 'Gold verified' : tier === 'silver' ? 'Silver verified' : 'Verified'
  const glyph = tier === 'gold' ? '◆' : tier === 'silver' ? '◇' : '○'
  const color = tier === 'gold' ? colors.karmaGold : tier === 'silver' ? colors.silverText : colors.bronzeText
  const background = tier === 'gold' ? colors.goldTint : tier === 'silver' ? colors.silverTint : colors.bronzeTint

  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        paddingVertical: 2,
        paddingHorizontal: 8,
        borderRadius: radii.pill,
        backgroundColor: background,
        borderWidth: 1,
        borderColor: color,
      }}
    >
      <Text style={{ fontSize: 10, color }} accessibilityElementsHidden>
        {glyph}
      </Text>
      <Text style={{ fontSize: 11.5, fontWeight: '600', color }}>{label}</Text>
    </View>
  )
}
