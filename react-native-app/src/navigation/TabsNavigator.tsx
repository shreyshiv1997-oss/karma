import { Ionicons } from '@expo/vector-icons'
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import { createNativeStackNavigator } from '@react-navigation/native-stack'
import React from 'react'
import { Pressable, Text, View } from 'react-native'
import { useCreateSheet } from '../components/CreateSheet'
import { KarmaRing } from '../components/KarmaRing'
import { BookScreen } from '../screens/BookScreen'
import { FeedScreen } from '../screens/FeedScreen'
import { GigsScreen } from '../screens/GigsScreen'
import { KarmaScreen } from '../screens/KarmaScreen'
import { ProfileScreen } from '../screens/ProfileScreen'
import { colors, radii } from '../theme/tokens'

/**
 * The app shell: bottom tabs with the centre ✚ as the dual-intent surface —
 * one button, two verbs, no role selection, no wall.
 */

export type TabParamList = {
  Home: undefined
  Gigs: undefined
  Create: undefined
  Karma: undefined
  You: undefined
}

export type RootStackParamList = {
  Tabs: { screen?: keyof TabParamList } | undefined
  Book: { preselectCategory?: string } | undefined
}

const Tab = createBottomTabNavigator<TabParamList>()
const RootStack = createNativeStackNavigator<RootStackParamList>()

export function RootNavigator() {
  return (
    <RootStack.Navigator>
      <RootStack.Screen name="Tabs" component={TabNavigator} options={{ headerShown: false }} />
      <RootStack.Screen
        name="Book"
        component={BookScreen}
        options={{ headerShown: false, presentation: 'modal' }}
      />
    </RootStack.Navigator>
  )
}

function TabNavigator() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.violet,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: {
          backgroundColor: colors.paper,
          borderTopWidth: 1,
          borderTopColor: colors.line,
          height: 60,
          paddingTop: 4,
          paddingBottom: 6,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '500' },
      }}
    >
      <Tab.Screen name="Home" component={FeedScreen} options={{ title: 'Home' }} />
      <Tab.Screen name="Gigs" component={GigsScreen} options={{ title: 'Gigs' }} />
      <Tab.Screen
        name="Create"
        component={CreatePlaceholder}
        options={{
          title: 'Post a gig',
          tabBarIcon: () => null,
          tabBarButton: (props) => <CreateButton {...props} />,
        }}
      />
      <Tab.Screen name="Karma" component={KarmaScreen} options={{ title: 'Karma' }} />
      <Tab.Screen name="You" component={ProfileScreen} options={{ title: 'You' }} />
    </Tab.Navigator>
  )
}

/**
 * One button, two verbs. The ✚ is a violet disc — the only elevated element
 * in the chrome — and it opens the sheet rather than assuming a side.
 */
function CreateButton() {
  const sheet = useCreateSheet()
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Post a gig or share a post"
      onPress={() => sheet.open()}
      style={{ alignItems: 'center', justifyContent: 'center' }}
    >
      <View
        style={{
          width: 46,
          height: 46,
          borderRadius: radii.pill,
          backgroundColor: colors.violet,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text style={{ color: colors.white, fontSize: 24, fontWeight: '300', lineHeight: 26 }}>+</Text>
      </View>
    </Pressable>
  )
}

/** No body: the ✚ is an action, not a destination. */
function CreatePlaceholder() {
  return <View style={{ flex: 1, backgroundColor: colors.paper }} />
}

/**
 * The shared header: wordmark, live karma ring (tap for the ledger) and
 * sign out. It is the one place the product's thesis is always one tap away
 * from its own audit trail.
 */
export function AppHeader({
  karma,
  onPressKarma,
  onPressSignOut,
}: {
  karma: number
  onPressKarma: () => void
  onPressSignOut: () => void
}) {
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 16,
        paddingVertical: 10,
        backgroundColor: colors.paper,
        borderBottomWidth: 1,
        borderBottomColor: colors.line,
      }}
    >
      <Text style={{ fontSize: 19, fontWeight: '700', color: colors.text, letterSpacing: -0.4, flex: 1 }}>
        KARMA
      </Text>
      <Pressable
        onPress={onPressKarma}
        accessibilityRole="button"
        accessibilityLabel={`Your karma is ${karma} of 100. View your ledger.`}
        style={{ padding: 2 }}
      >
        <KarmaRing value={karma} size={34} />
      </Pressable>
      <Pressable
        onPress={onPressSignOut}
        accessibilityRole="button"
        accessibilityLabel="Sign out"
        style={{
          minHeight: 36,
          minWidth: 36,
          borderWidth: 1,
          borderColor: colors.lineStrong,
          borderRadius: radii.input,
          backgroundColor: colors.surface,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Ionicons name="log-out-outline" size={16} color={colors.textMuted} />
      </Pressable>
    </View>
  )
}
