import React, { useEffect, useRef } from 'react'
import {
  Animated,
  Easing,
  Image,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type DimensionValue,
  type StyleProp,
  type ViewStyle,
} from 'react-native'
import { LinearGradient } from 'expo-linear-gradient'
import { colors, EASE, motion, radii, space, tapMin, typography } from '../theme/tokens'
import { inr } from '../utils/format'
import { isSecuredPayment, paymentLabel } from '../utils/gig'

const easing = () => Easing.bezier(EASE[0], EASE[1], EASE[2], EASE[3])

/* ------------------------------------------------------------------ */
/* Card — flat, 1px border, the only depth in the system               */
/* ------------------------------------------------------------------ */

export function Card({
  style,
  children,
  ...rest
}: { style?: StyleProp<ViewStyle>; children: React.ReactNode } & React.ComponentProps<typeof View>) {
  return (
    <View
      {...rest}
      style={[
        {
          backgroundColor: colors.surface,
          borderWidth: 1,
          borderColor: colors.line,
          borderRadius: radii.card,
        },
        style,
      ]}
    >
      {children}
    </View>
  )
}

/* ------------------------------------------------------------------ */
/* Button — 120 ms press scale, the state-change budget                */
/* ------------------------------------------------------------------ */

type ButtonVariant = 'primary' | 'ghost' | 'danger' | 'neutral'

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled,
  style,
  textStyle,
  small,
}: {
  label: string
  onPress?: () => void
  variant?: ButtonVariant
  disabled?: boolean
  style?: StyleProp<ViewStyle>
  textStyle?: StyleProp<object>
  small?: boolean
}) {
  const scale = useRef(new Animated.Value(1)).current

  const background =
    variant === 'primary'
      ? colors.violet
      : variant === 'danger'
        ? colors.rose
        : variant === 'ghost'
          ? colors.surface
          : colors.ink

  const fg = variant === 'ghost' ? colors.text : colors.white

  return (
    <Animated.View
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled }}
      accessibilityLabel={label}
      style={[
        {
          borderRadius: radii.input,
          backgroundColor: background,
          borderWidth: variant === 'ghost' ? 1 : 0,
          borderColor: colors.lineStrong,
          opacity: disabled ? 0.5 : 1,
          transform: [{ scale }],
        },
        style,
      ]}
    >
      <Pressable
        onPress={onPress}
        disabled={disabled}
        onPressIn={() =>
          Animated.timing(scale, {
            toValue: 0.98,
            duration: motion.state,
            easing: easing(),
            useNativeDriver: true,
          }).start()
        }
        onPressOut={() =>
          Animated.timing(scale, {
            toValue: 1,
            duration: motion.state,
            easing: easing(),
            useNativeDriver: true,
          }).start()
        }
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'center',
          gap: space.s2,
          minHeight: small ? 38 : tapMin,
          paddingHorizontal: space.s4 + 2,
        }}
      >
        <Text
          style={[
            {
              color: fg,
              fontWeight: '600',
              fontSize: small ? 14 : 15,
              lineHeight: small ? 18 : 21,
            },
            textStyle,
          ]}
          numberOfLines={2}
        >
          {label}
        </Text>
      </Pressable>
    </Animated.View>
  )
}

/* ------------------------------------------------------------------ */
/* Segmented control — the tab strip, urgency and role pickers         */
/* ------------------------------------------------------------------ */

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  style,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
  style?: StyleProp<ViewStyle>
}) {
  return (
    <View
      style={[
        {
          flexDirection: 'row',
          backgroundColor: colors.surface2,
          padding: 3,
          borderRadius: radii.input,
        },
        style,
      ]}
    >
      {options.map((opt) => {
        const selected = opt.value === value
        return (
          <Pressable
            key={opt.value}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            onPress={() => onChange(opt.value)}
            style={{
              flex: 1,
              minHeight: 34,
              borderRadius: 6,
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: selected ? colors.surface : 'transparent',
            }}
          >
            <Text
              style={{
                fontWeight: '600',
                fontSize: 13.5,
                color: selected ? colors.text : colors.textMuted,
              }}
            >
              {opt.label}
            </Text>
          </Pressable>
        )
      })}
    </View>
  )
}

/* ------------------------------------------------------------------ */
/* Fields                                                              */
/* ------------------------------------------------------------------ */

export function Field({
  label,
  value,
  onChangeText,
  placeholder,
  secure,
  multiline,
  maxLength,
  keyboardType,
  autoCapitalize = "none",
  autoCorrect = false,
  rows,
}: {
  label: string
  value: string
  onChangeText: (t: string) => void
  placeholder?: string
  secure?: boolean
  multiline?: boolean
  maxLength?: number
  keyboardType?: 'default' | 'email-address' | 'numeric' | 'phone-pad'
  autoCapitalize?: 'none' | 'sentences' | 'words' | 'characters'
  autoCorrect?: boolean
  rows?: number
}) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={{ fontSize: 13, fontWeight: '600', color: colors.textMuted }}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.textFaint}
        secureTextEntry={secure}
        multiline={multiline}
        maxLength={maxLength}
        keyboardType={keyboardType}
        autoCapitalize={autoCapitalize}
        autoCorrect={autoCorrect}
        textAlignVertical={multiline ? 'top' : 'center'}
        style={[
          {
            minHeight: tapMin,
            paddingVertical: 10,
            paddingHorizontal: 12,
            borderWidth: 1,
            borderColor: colors.lineStrong,
            borderRadius: radii.input,
            backgroundColor: colors.surface,
            fontSize: 15.5,
            color: colors.text,
            ...(multiline ? { minHeight: (rows ?? 3) * 24 } : {}),
          },
          Platform.select({ ios: { fontFamily: 'System' } }),
        ]}
      />
    </View>
  )
}

/* ------------------------------------------------------------------ */
/* Text helpers                                                        */
/* ------------------------------------------------------------------ */

export function SectionTitle({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <Text
      style={[
        {
          fontSize: typography.eyebrow,
          fontWeight: '600',
          color: colors.textMuted,
          textTransform: 'uppercase',
          letterSpacing: 0.6,
        },
        style,
      ]}
    >
      {children}
    </Text>
  )
}

export function ErrorText({ children }: { children: React.ReactNode }) {
  return (
    <Text accessibilityLiveRegion="polite" style={{ color: colors.rose, fontWeight: '500', fontSize: 14 }}>
      {children}
    </Text>
  )
}

export function NoticeText({ children }: { children: React.ReactNode }) {
  return (
    <Text accessibilityLiveRegion="polite" style={{ color: colors.lime, fontWeight: '600', fontSize: 14 }}>
      {children}
    </Text>
  )
}

/* ------------------------------------------------------------------ */
/* Pill                                                                */
/* ------------------------------------------------------------------ */

export function Pill({
  children,
  color,
  background,
  style,
}: {
  children: React.ReactNode
  color: string
  background: string
  style?: StyleProp<ViewStyle>
}) {
  return (
    <View
      style={[
        {
          flexDirection: 'row',
          alignItems: 'center',
          gap: 5,
          paddingVertical: 3,
          paddingHorizontal: 10,
          borderRadius: radii.pill,
          borderWidth: 1,
          borderColor: color,
          backgroundColor: background,
        },
        style,
      ]}
    >
      {children}
    </View>
  )
}

export function GigStatusPill({ status }: { status: string }) {
  const done = status === 'completed'
  const cancelled = status === 'cancelled'
  const color = done ? colors.lime : cancelled ? colors.textFaint : colors.cyan
  const background = done ? colors.limeWash : cancelled ? colors.surface2 : colors.cyanWash
  const labels: Record<string, string> = {
    searching: 'Searching',
    assigned: 'Assigned',
    en_route: 'On the way',
    arrived: 'Arrived',
    in_progress: 'Working',
    completion_pending: 'Awaiting approval',
    completed: 'Completed',
    cancelled: 'Cancelled',
  }
  return (
    <Pill color={color} background={background} style={{ borderWidth: 0 }}>
      <Text style={{ fontSize: 12.5, fontWeight: '600', color }}>{labels[status] ?? status}</Text>
    </Pill>
  )
}

export function PaymentLabelText({ status }: { status: string }) {
  const secured = isSecuredPayment(status)
  return (
    <Text style={{ color: secured ? colors.lime : colors.karmaGold, fontWeight: '600', fontSize: 13 }}>
      {paymentLabel(status)}
    </Text>
  )
}

/** Live-link chip: is this gig being pushed to, or showing its last known state? */
export function LiveLink({ state }: { state: 'connecting' | 'live' | 'closed' }) {
  const label = state === 'live' ? 'Live' : state === 'connecting' ? 'Connecting…' : 'Updates paused'
  const color = state === 'live' ? colors.lime : state === 'connecting' ? colors.cyan : colors.textFaint
  return (
    <View accessibilityLabel={label} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
      <View style={{ width: 7, height: 7, borderRadius: radii.pill, backgroundColor: color }} />
      <Text style={{ fontSize: 11.5, fontWeight: '600', color }}>{label}</Text>
    </View>
  )
}

export function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <View>
      <Text
        style={{
          fontSize: 11.5,
          color: colors.textFaint,
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}
      >
        {label}
      </Text>
      <Text style={{ fontSize: 20, fontWeight: '700', color: colors.text }}>{value}</Text>
    </View>
  )
}

/* ------------------------------------------------------------------ */
/* Skeleton — the shimmer stops after three cycles, never a strobe     */
/* ------------------------------------------------------------------ */

export function Skeleton({ height = 12, width, radius = radii.input, style }: { height?: number; width?: DimensionValue; radius?: number; style?: StyleProp<ViewStyle> }) {
  const pos = useRef(new Animated.Value(0)).current

  useEffect(() => {
    const loop = Animated.loop(
      Animated.timing(pos, {
        toValue: 1,
        duration: 1400,
        easing: easing(),
        useNativeDriver: true,
      }),
      { iterations: 3 },
    )
    loop.start()
    return () => loop.stop()
  }, [pos])

  const translateX = pos.interpolate({ inputRange: [0, 1], outputRange: [-200, 200] })

  return (
    <View
      style={[
        {
          height,
          width,
          borderRadius: radius,
          backgroundColor: colors.surface2,
          overflow: 'hidden',
        },
        style,
      ]}
      accessibilityElementsHidden
    >
      <Animated.View
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: -50,
          right: -50,
          transform: [{ translateX }],
        }}
      >
        <LinearGradient
          colors={['transparent', 'rgba(236,234,229,0.9)', 'transparent']}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 0 }}
          style={StyleSheet.absoluteFill}
        />
      </Animated.View>
    </View>
  )
}

/* ------------------------------------------------------------------ */
/* RiseIn — the 220 ms entrance, transform + opacity only              */
/* ------------------------------------------------------------------ */

export function RiseIn({
  children,
  delay = 0,
  style,
}: {
  children: React.ReactNode
  delay?: number
  style?: StyleProp<ViewStyle>
}) {
  const t = useRef(new Animated.Value(0)).current
  useEffect(() => {
    Animated.timing(t, {
      toValue: 1,
      duration: motion.enter,
      delay,
      easing: easing(),
      useNativeDriver: true,
    }).start()
  }, [t, delay])
  return (
    <Animated.View
      style={[
        { opacity: t, transform: [{ translateY: t.interpolate({ inputRange: [0, 1], outputRange: [8, 0] }) }] },
        style,
      ]}
    >
      {children}
    </Animated.View>
  )
}

/* ------------------------------------------------------------------ */
/* Media image — never a remote-link problem; these are same-origin    */
/* ------------------------------------------------------------------ */

export function MediaImage({ uri, height, style }: { uri: string; height: number; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[{ height, borderRadius: radii.card, overflow: 'hidden', backgroundColor: colors.surface2 }, style]}>
      <Image source={{ uri }} style={StyleSheet.absoluteFill} resizeMode="cover" />
    </View>
  )
}

export function money(value: number): string {
  return inr(value)
}
