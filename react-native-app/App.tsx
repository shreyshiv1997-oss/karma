import { NavigationContainer, useNavigation } from '@react-navigation/native'
import type { NativeStackNavigationProp } from '@react-navigation/native-stack'
import { StatusBar } from 'expo-status-bar'
import React, { useCallback } from 'react'
import { Alert, View } from 'react-native'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { AuthProvider, useAuth } from './src/auth/AuthContext'
import { CreateSheetProvider } from './src/components/CreateSheet'
import { OfflineBanner } from './src/components/OfflineBanner'
import { KarmaRing } from './src/components/KarmaRing'
import { AppHeader, RootNavigator, type RootStackParamList } from './src/navigation/TabsNavigator'
import { AuthScreen } from './src/screens/AuthScreen'
import { colors } from './src/theme/tokens'

/**
 * The root. One provider per concern, in dependency order:
 *
 *   SafeArea — notches and the home indicator never cover the chrome
 *   Auth     — the session, restored from secure storage and validated
 *   Sheet    — the ✚'s two verbs, available to the tab bar and to screens
 *
 * Unauthenticated → the door (one form, two entry doors, no role question).
 * Authenticated   → the shell: header with the live ring, tabs, and the
 * modal Book stack.
 */

export default function App() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="dark" />
        <RootGate />
      </AuthProvider>
    </SafeAreaProvider>
  )
}

function RootGate() {
  const { user, ready } = useAuth()

  if (!ready) {
    // Hold on the thesis, not on a spinner: the ring at a neutral 50.
    return (
      <View style={{ flex: 1, backgroundColor: colors.paper, alignItems: 'center', justifyContent: 'center' }}>
        <KarmaRing value={50} size={56} label="Loading" />
      </View>
    )
  }

  if (!user) return <AuthScreen />

  return <AuthedShell />
}

function AuthedShell() {
  const { user, logout } = useAuth()
  const karma = user?.karma ?? 0

  const confirmSignOut = useCallback(() => {
    Alert.alert('Sign out?', 'This ends the session on this device. Other devices stay signed in.', [
      { text: 'Stay', style: 'cancel' },
      { text: 'Sign out', style: 'destructive', onPress: () => void logout() },
    ])
  }, [logout])

  return (
    <NavigationContainer>
      <CreateSheetProvider>
        <View style={{ flex: 1, backgroundColor: colors.paper }}>
          <HeaderAndTabs karma={karma} onSignOut={confirmSignOut} />
          <RootNavigator />
        </View>
      </CreateSheetProvider>
    </NavigationContainer>
  )
}

/** Header above the tabs, so it persists while screen state survives below it. */
function HeaderAndTabs({ karma, onSignOut }: { karma: number; onSignOut: () => void }) {
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>()

  return (
    <>
      <OfflineBanner />
      <AppHeader
        karma={karma}
        onPressKarma={() => navigation.navigate('Tabs', { screen: 'Karma' })}
        onPressSignOut={onSignOut}
      />
    </>
  )
}
