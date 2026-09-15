import React, { useEffect, useRef, useState } from 'react'
import { Animated, StyleSheet, Text, View } from 'react-native'
import Svg, { Circle } from 'react-native-svg'
import { colors, motion } from '../theme/tokens'
import { clampKarma, karmaBand, karmaHue } from '../utils/karma'

/**
 * The Karma Ring — the product's thesis rendered as ~60 lines of SVG.
 *
 * Not a badge. A conic progress ring that fills as you earn and changes hue
 * along the karma gradient:
 *
 *   0 ─────── 40 ─────── 70 ─────── 100
 *  rose ──── amber ──── lime ──── karma-gold
 *  dormant   building    trusted    proven
 *
 * The number counts with the arc — one animation, one value — and pulses
 * (320 ms, transform only) when an event lands.
 */

const SIZE = 44
const STROKE = 4
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

type Props = {
  value: number
  size?: number
  /** When set and non-zero, a `+N` floats up — a karma event just landed. */
  celebrate?: number | null
  label?: string
}

export function KarmaRing({ value, size = SIZE, celebrate = null, label }: Props) {
  const clamped = clampKarma(value)
  const [shown, setShown] = useState(clamped)
  const shownRef = useRef(clamped)
  const pulse = useRef(new Animated.Value(1)).current
  const float = useRef(new Animated.Value(0)).current

  // Count-animate on change. The arc is driven by `shown`, the same value the
  // number reads — the two halves of one animation must not disagree.
  useEffect(() => {
    const from = shownRef.current
    const to = clamped
    shownRef.current = to
    if (from === to) return

    // Pulse: transform only, fast-out.
    pulse.setValue(1)
    Animated.sequence([
      Animated.timing(pulse, { toValue: 1.12, duration: motion.celebrate / 2, useNativeDriver: true }),
      Animated.timing(pulse, { toValue: 1, duration: motion.celebrate / 2, useNativeDriver: true }),
    ]).start()

    const start = Date.now()
    let frame = 0
    const tick = () => {
      const t = Math.min(1, (Date.now() - start) / motion.celebrate)
      const eased = 1 - Math.pow(1 - t, 3)
      setShown(Math.round(from + (to - from) * eased))
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [clamped, pulse])

  // The floating `+N`, 900 ms — the one celebration budget allows to exceed 320.
  useEffect(() => {
    if (celebrate === null || celebrate === 0) return
    float.setValue(0)
    Animated.timing(float, {
      toValue: 1,
      duration: 900,
      useNativeDriver: true,
    }).start()
    const timer = setTimeout(() => float.setValue(0), 1000)
    return () => clearTimeout(timer)
  }, [celebrate, float])

  const dash = (shown / 100) * CIRCUMFERENCE
  const hue = karmaHue(clamped)
  const stroke = size < 40 ? 3 : STROKE
  const numeralSize = size < 40 ? 12 : 13

  return (
    <View
      accessibilityLabel={label ?? `Karma ${clamped} of 100 — ${karmaBand(clamped)}`}
      style={{ position: 'relative', width: size, height: size }}
    >
      <Animated.View style={{ width: size, height: size, transform: [{ scale: pulse }] }}>
        <Svg width={size} height={size} viewBox={`0 0 ${SIZE} ${SIZE}`}>
          <Circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke={colors.line}
            strokeWidth={stroke}
          />
          <Circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke={hue}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${CIRCUMFERENCE}`}
            transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          />
        </Svg>
        <View pointerEvents="none" style={StyleSheet.absoluteFill}>
          <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
            <Text style={{ fontSize: numeralSize, fontWeight: '700', color: hue, letterSpacing: -0.2 }}>
              {shown}
            </Text>
          </View>
        </View>
      </Animated.View>

      {celebrate !== null && celebrate !== 0 && (
        <Animated.View
          pointerEvents="none"
          style={{
            position: 'absolute',
            top: -4,
            left: '50%',
            opacity: float,
            transform: [
              { translateX: -12 },
              { translateY: float.interpolate({ inputRange: [0, 1], outputRange: [0, -24] }) },
              { scale: float.interpolate({ inputRange: [0, 0.25, 1], outputRange: [0.9, 1, 1] }) },
            ],
          }}
        >
          <Text style={{ fontSize: 12, fontWeight: '700', color: celebrate > 0 ? colors.lime : colors.rose }}>
            {celebrate > 0 ? `+${celebrate}` : celebrate}
          </Text>
        </Animated.View>
      )}
    </View>
  )
}
