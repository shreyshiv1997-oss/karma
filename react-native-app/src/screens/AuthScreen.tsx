import React, { useState } from 'react'
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Text,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { KarmaRing } from '../components/KarmaRing'
import { Button, Card, ErrorText, Field, Segmented } from '../components/primitives'
import { colors, space } from '../theme/tokens'

/**
 * One form, two entry doors (email or phone) — and crucially, no question
 * asking "are you a customer or a worker?". Capabilities are additive and
 * granted later, so the population is never split at the door.
 */

type Mode = 'login' | 'register'

export function AuthScreen() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [handle, setHandle] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') {
        await login(identifier.trim(), password)
      } else {
        await register({
          handle: handle.trim(),
          display_name: displayName.trim(),
          // An '@' means email; otherwise treat it as a phone number.
          ...(identifier.includes('@')
            ? { email: identifier.trim() }
            : { phone: identifier.trim() }),
          password,
          city: 'Indore',
        })
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.ink }}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', padding: space.s5 }}
          keyboardShouldPersistTaps="handled"
        >
          {/* The wordmark. The gradient here is earned: it is the karma gradient. */}
          <View style={{ alignItems: 'center', marginBottom: space.s6 }}>
            <KarmaRing value={88} size={56} label="KARMA" />
            <Text
              style={{
                fontSize: 34,
                fontWeight: '700',
                letterSpacing: -1.0,
                color: colors.white,
                marginTop: space.s3,
              }}
            >
              KARMA
            </Text>
            <Text style={{ color: '#A5A29A', fontSize: 14.5, marginTop: 6 }}>
              Thou art the work you do.
            </Text>
          </View>

          <Card
            style={{ padding: space.s5, gap: space.s4, backgroundColor: colors.surface }}
            accessibilityViewIsModal
          >
            <Segmented<Mode>
              options={[
                { value: 'login', label: 'Sign in' },
                { value: 'register', label: 'Create account' },
              ]}
              value={mode}
              onChange={(m) => {
                setMode(m)
                setError(null)
              }}
            />

            {mode === 'register' && (
              <>
                <Field label="Handle" value={handle} onChangeText={setHandle} placeholder="yourname" />
                <Field
                  label="Name"
                  value={displayName}
                  onChangeText={setDisplayName}
                  placeholder="Priya Malviya"
                  autoCapitalize="words"
                />
              </>
            )}

            <Field
              label={mode === 'login' ? 'Handle, email or phone' : 'Email or phone'}
              value={identifier}
              onChangeText={setIdentifier}
              placeholder="priya  ·  priya@example.com  ·  9876500001"
              keyboardType="email-address"
            />

            <Field
              label="Password"
              value={password}
              onChangeText={setPassword}
              placeholder="At least 8 characters"
              secure
            />

            {error && <ErrorText>{error}</ErrorText>}

            <Button
              label={busy ? 'Working…' : mode === 'login' ? 'Sign in' : 'Create account'}
              onPress={submit}
              disabled={busy}
            />

            <Text style={{ fontSize: 12.5, color: colors.textFaint, textAlign: 'center', lineHeight: 18 }}>
              Demo: priya / StrongPass!234
              {'\n'}
              Worker: ramesh.electric / StrongPass!234
            </Text>
          </Card>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}
