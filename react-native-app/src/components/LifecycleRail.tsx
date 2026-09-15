import React from 'react'
import { Text, View } from 'react-native'
import { colors } from '../theme/tokens'
import { RAIL, STATUS_LABELS } from '../utils/gig'

/**
 * Where the work actually is. Dots fill lime as stages complete; the current
 * stage is outlined, not coloured alone, so the state reads on any display.
 */
export function LifecycleRail({ status }: { status: string }) {
  const currentIndex = (RAIL as readonly string[]).indexOf(status)

  return (
    <View
      accessibilityLabel={`Gig progress: ${STATUS_LABELS[status] ?? status}`}
      style={{ flexDirection: 'row', alignItems: 'center' }}
    >
      {RAIL.map((stage, index) => {
        const done = currentIndex >= 0 && index <= currentIndex
        const isCurrent = index === currentIndex
        return (
          <View
            key={stage}
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              flex: index === RAIL.length - 1 ? 0 : 1,
            }}
          >
            <View style={{ alignItems: 'center', gap: 4 }}>
              <View
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: 999,
                  backgroundColor: done ? colors.lime : colors.line,
                  borderWidth: isCurrent ? 3 : 0,
                  borderColor: '#D9ECC0',
                }}
              />
              <Text
                numberOfLines={1}
                style={{
                  fontSize: 10.5,
                  color: done ? colors.text : colors.textFaint,
                  fontWeight: isCurrent ? '700' : '500',
                  maxWidth: 56,
                }}
              >
                {STATUS_LABELS[stage]}
              </Text>
            </View>
            {index < RAIL.length - 1 && (
              <View
                style={{
                  flex: 1,
                  height: 2,
                  backgroundColor: done ? colors.lime : colors.line,
                  marginBottom: 16,
                  marginHorizontal: 3,
                }}
              />
            )}
          </View>
        )
      })}
    </View>
  )
}
