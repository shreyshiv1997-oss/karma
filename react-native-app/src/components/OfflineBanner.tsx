import NetInfo from '@react-native-community/netinfo'
import React, { useState } from 'react'
import { Text, View } from 'react-native'
import { colors } from '../theme/tokens'

/**
 * The honest reading of offline support for an app built on trust: the user
 * sees "you're offline — showing what you last loaded". They never see a lie
 * about someone else's data.
 */

export function OfflineBanner() {
  const [offline, setOffline] = useState(false)

  NetInfo.addEventListener((state) => {
    setOffline(!(state.isConnected ?? true))
  })

  if (!offline) return null

  return (
    <View
      accessibilityLiveRegion="polite"
      style={{
        backgroundColor: colors.cyanWash,
        borderBottomWidth: 1,
        borderBottomColor: colors.line,
        paddingVertical: 8,
        paddingHorizontal: 16,
      }}
    >
      <Text style={{ color: colors.cyan, fontSize: 13, fontWeight: '600' }}>
        You're offline — showing what you last loaded.
      </Text>
    </View>
  )
}
