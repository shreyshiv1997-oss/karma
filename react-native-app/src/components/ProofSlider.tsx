import React, { useRef, useState } from 'react'
import {
  Image,
  PanResponder,
  StyleSheet,
  Text,
  View,
  type GestureResponderEvent,
} from 'react-native'
import { colors, radii } from '../theme/tokens'

/**
 * The Proof Slider — the component that justifies the merger.
 *
 * A completed, *paid* gig produces before/after evidence. Dragging the handle
 * wipes between them, making a stranger's competence visceral in a way a star
 * rating never can. It is unfakeable by construction: the backend only
 * publishes `kind=proof` for a gig whose payment_status is `paid`.
 *
 * Touch- and pointer-driven through PanResponder (which owns the horizontal
 * gesture end to end, the way the web version owns it through pointer
 * capture). The before/after text labels are always present, so the
 * information is never image-only.
 */

type Props = {
  beforeUrl: string
  afterUrl: string
  beforeLabel?: string
  afterLabel?: string
  height?: number
}

function clampPct(value: number): number {
  return Math.max(0, Math.min(100, value))
}

export function ProofSlider({
  beforeUrl,
  afterUrl,
  beforeLabel = 'Before',
  afterLabel = 'After',
  height = 220,
}: Props) {
  const [width, setWidth] = useState(0)
  const [pct, setPct] = useState(50)
  const widthRef = useRef(0)

  const pan = useRef(
    PanResponder.create({
      onMoveShouldSetPanResponder: () => true,
      onPanResponderTerminationRequest: () => false,
      onPanResponderGrant: (e: GestureResponderEvent) => {
        if (widthRef.current > 0) setPct(clampPct((e.nativeEvent.locationX / widthRef.current) * 100))
      },
      onPanResponderMove: (e: GestureResponderEvent) => {
        if (widthRef.current > 0) setPct(clampPct((e.nativeEvent.locationX / widthRef.current) * 100))
      },
    }),
  ).current

  const wipeX = width > 0 ? (width * pct) / 100 : 0

  return (
    <View
      onLayout={(e) => {
        const w = e.nativeEvent.layout.width
        widthRef.current = w
        setWidth(w)
      }}
      {...pan.panHandlers}
      accessibilityRole="adjustable"
      accessibilityLabel={`Compare ${beforeLabel.toLowerCase()} and ${afterLabel.toLowerCase()}.`}
      accessibilityValue={{ min: 0, max: 100, now: Math.round(pct) }}
      style={{
        height,
        borderRadius: radii.card,
        overflow: 'hidden',
        borderWidth: 1,
        borderColor: colors.line,
        backgroundColor: colors.surface2,
      }}
    >
      {/* AFTER is the base layer; BEFORE is clipped from the left. */}
      <Image source={{ uri: afterUrl }} style={StyleSheet.absoluteFill} resizeMode="cover" />
      <View
        pointerEvents="none"
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: 0,
          width: wipeX,
          overflow: 'hidden',
        }}
      >
        <Image
          source={{ uri: beforeUrl }}
          style={{ position: 'absolute', top: 0, left: 0, width, height }}
          resizeMode="cover"
        />
      </View>

      {/* Labels: always present, so the information is never image-only. */}
      <View pointerEvents="none" style={[labelWrap, { left: 10 }]}>
        <Text style={labelText}>{beforeLabel}</Text>
      </View>
      <View pointerEvents="none" style={[labelWrap, { right: 10 }]}>
        <Text style={labelText}>{afterLabel}</Text>
      </View>

      {/* The handle. */}
      <View
        pointerEvents="none"
        accessibilityElementsHidden
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: wipeX - 1,
          width: 2,
          backgroundColor: colors.white,
        }}
      >
        <View
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            width: 34,
            height: 34,
            marginLeft: -17,
            marginTop: -17,
            borderRadius: radii.pill,
            backgroundColor: colors.white,
            borderWidth: 1,
            borderColor: colors.lineStrong,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ color: colors.textMuted, fontSize: 14, fontWeight: '700', letterSpacing: -0.8 }}>
            ⇔
          </Text>
        </View>
      </View>
    </View>
  )
}

const labelWrap = {
  position: 'absolute',
  bottom: 10,
  paddingVertical: 2,
  paddingHorizontal: 8,
  borderRadius: radii.pill,
  backgroundColor: 'rgba(11,11,15,0.72)',
} as const

const labelText = {
  color: colors.white,
  fontSize: 11.5,
  fontWeight: '700' as const,
  letterSpacing: 0.4,
  textTransform: 'uppercase' as const,
}
