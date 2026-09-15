import { Ionicons } from '@expo/vector-icons'
import { useNavigation } from '@react-navigation/native'
import type { NativeStackNavigationProp } from '@react-navigation/native-stack'
import * as Haptics from 'expo-haptics'
import React, { createContext, useCallback, useContext, useState } from 'react'
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  Text,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { ApiError, post } from '../api/client'
import type { Post } from '../api/types'
import type { RootStackParamList } from '../navigation/TabsNavigator'
import { Button, ErrorText, Field, NoticeText } from './primitives'
import { colors, radii, space } from '../theme/tokens'

/**
 * One button, two verbs.
 *
 * The centre of the bottom bar opens this sheet, and it offers Share and
 * Post-a-gig side by side, equal weight. There is no role-selection screen
 * anywhere in KARMA — capabilities are additive, and a person who hires a
 * plumber on Tuesday can be a verified electrician on Thursday.
 */

type CreateSheetValue = {
  open: (opts?: { preselectCategory?: string }) => void
  close: () => void
}

const CreateSheetContext = createContext<CreateSheetValue | null>(null)

export function CreateSheetProvider({ children }: { children: React.ReactNode }) {
  const [visible, setVisible] = useState(false)
  const [preselectCategory, setPreselectCategory] = useState<string | undefined>(undefined)

  const open = useCallback((opts?: { preselectCategory?: string }) => {
    setPreselectCategory(opts?.preselectCategory)
    setVisible(true)
  }, [])

  const close = useCallback(() => setVisible(false), [])

  return (
    <CreateSheetContext.Provider value={{ open, close }}>
      {children}
      <CreateSheetModal
        visible={visible}
        onClose={close}
        preselectCategory={preselectCategory}
      />
    </CreateSheetContext.Provider>
  )
}

export function useCreateSheet(): CreateSheetValue {
  const ctx = useContext(CreateSheetContext)
  if (!ctx) throw new Error('useCreateSheet must be used inside <CreateSheetProvider>')
  return ctx
}

function CreateSheetModal({
  visible,
  onClose,
  preselectCategory,
}: {
  visible: boolean
  onClose: () => void
  preselectCategory?: string
}) {
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>()
  const [sharing, setSharing] = useState(false)

  const goBook = () => {
    onClose()
    setSharing(false)
    navigation.navigate('Book', { preselectCategory })
  }

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable
        style={{ flex: 1, backgroundColor: 'rgba(11,11,15,0.4)' }}
        onPress={onClose}
        accessibilityLabel="Dismiss"
      />
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1, justifyContent: 'flex-end' }}
      >
        <View
          style={{
            backgroundColor: colors.paper,
            borderTopLeftRadius: radii.card,
            borderTopRightRadius: radii.card,
            borderWidth: 1,
            borderColor: colors.line,
          }}
        >
          <SafeAreaView edges={['bottom'] as const}>
            <View style={{ gap: space.s4, padding: space.s4 }}>
              {/* The two verbs, equal weight. */}
              <View style={{ flexDirection: 'row', gap: space.s3 }}>
                <VerbButton
                  icon="briefcase-outline"
                  label="Post a gig"
                  emphasized={!sharing}
                  onPress={goBook}
                />
                <VerbButton
                  icon="chatbubble-outline"
                  label="Share a post"
                  emphasized={sharing}
                  onPress={() => setSharing((v) => !v)}
                />
              </View>

              {sharing && (
                <ShareComposer onShared={onClose} />
              )}
            </View>
          </SafeAreaView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  )
}

function VerbButton({
  icon,
  label,
  emphasized,
  onPress,
}: {
  icon: keyof typeof Ionicons.glyphMap
  label: string
  emphasized: boolean
  onPress: () => void
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: emphasized }}
      style={{
        flex: 1,
        minHeight: 72,
        borderRadius: radii.input,
        borderWidth: 1,
        borderColor: emphasized ? colors.violet : colors.lineStrong,
        backgroundColor: emphasized ? colors.violetWash : colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
        gap: space.s1,
      }}
    >
      <Ionicons name={icon} size={22} color={emphasized ? colors.violetInk : colors.textMuted} />
      <Text style={{ color: emphasized ? colors.violetInk : colors.text, fontWeight: '600', fontSize: 14 }}>
        {label}
      </Text>
    </Pressable>
  )
}

function ShareComposer({ onShared }: { onShared: () => void }) {
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const share = async () => {
    if (busy || body.trim().length < 1) return
    setBusy(true)
    setError(null)
    try {
      await post<Post>('/feed/posts', { kind: 'post', body: body.trim() })
      setDone(true)
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)
      setTimeout(onShared, 900)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not share. Try again.')
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return <NoticeText>Shared to your feed.</NoticeText>
  }

  return (
    <View style={{ gap: space.s3 }}>
      <Field
        label="What's happening?"
        value={body}
        onChangeText={setBody}
        placeholder="Share an update, or say a little about your day."
        multiline
        rows={3}
        autoCapitalize="sentences"
        autoCorrect
      />
      {error && <ErrorText>{error}</ErrorText>}
      <Button
        label={busy ? 'Sharing…' : 'Share to feed'}
        onPress={share}
        disabled={busy || body.trim().length < 1}
      />
    </View>
  )
}
