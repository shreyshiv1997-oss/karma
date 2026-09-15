import React, { useCallback, useEffect, useState } from 'react'
import { Alert, Pressable, ScrollView, Text, View } from 'react-native'
import { del, get, patch, post } from '../api/client'
import { ApiError } from '../api/client'
import type { Category, MyWorkerProfile, TrustedContact } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { TierBadge } from '../components/Avatar'
import { KarmaRing } from '../components/KarmaRing'
import { Button, Card, ErrorText, Field, NoticeText, SectionTitle } from '../components/primitives'
import { colors, radii, space } from '../theme/tokens'
import { getConsentedDeviceFix } from '../location/location'
import { inr } from '../utils/format'

/**
 * Your profile — the portfolio view.
 *
 * One person, additive capabilities. If you are verified you can open a
 * worker profile from here; hiring is a one-tap opt-in. There is no role
 * switch, because there are no roles.
 */

export function ProfileScreen() {
  const { user, grant, refreshUser, logout } = useAuth()
  const [worker, setWorker] = useState<MyWorkerProfile | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [contacts, setContacts] = useState<TrustedContact[] | null>(null)

  const isWorker = !!user?.capabilities?.includes('can_work')

  useEffect(() => {
    if (!isWorker) return
    get<MyWorkerProfile>('/workers/me/profile')
      .then(setWorker)
      .catch(() => undefined)
  }, [isWorker])

  useEffect(() => {
    get<Category[]>('/categories').then(setCategories).catch(() => undefined)
    get<TrustedContact[]>('/safety/trusted-contacts')
      .then(setContacts)
      .catch(() => setContacts([]))
  }, [])

  if (!user) return null

  const flash = (message: string) => {
    setNotice(message)
    setTimeout(() => setNotice(null), 3500)
  }

  const optIntoHiring = async () => {
    setBusy(true)
    setError(null)
    try {
      await grant('can_hire')
      await refreshUser()
      flash('You can now post gigs.')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  const toggleAvailable = async () => {
    const goingOnline = !worker?.is_available
    if (goingOnline) {
      const ok = await new Promise<boolean>((resolve) =>
        Alert.alert(
          'Go online?',
          'Share a fresh precise location once to appear in nearby matching? KARMA does not request location in the background.',
          [
            { text: 'Not now', style: 'cancel' },
            { text: 'Share once', onPress: () => resolve(true) },
          ],
        ),
      )
      if (!ok) return
    }
    setBusy(true)
    setError(null)
    try {
      let location: Record<string, unknown> = {}
      if (goingOnline) {
        const fix = await getConsentedDeviceFix()
        location = {
          lat: fix.lat,
          lng: fix.lng,
          accuracy_m: fix.accuracy_m,
          location_source: 'device',
          location_consent: true,
        }
      }
      await patch('/workers/me/location', { ...location, is_available: goingOnline })
      const updated = await get<MyWorkerProfile>('/workers/me/profile')
      setWorker(updated)
      flash(
        goingOnline
          ? 'You are online at the location you just shared.'
          : 'You are offline. Location will not be requested.',
      )
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  const confirmSignOut = () => {
    Alert.alert('Sign out?', 'This ends the session on this device. Other devices stay signed in.', [
      { text: 'Stay', style: 'cancel' },
      { text: 'Sign out', style: 'destructive', onPress: () => void logout() },
    ])
  }

  return (
    <ScrollView
      contentContainerStyle={{ padding: space.s4, gap: space.s4, paddingBottom: space.s7 }}
      style={{ backgroundColor: colors.paper, flex: 1 }}
      keyboardShouldPersistTaps="handled"
    >
      <Card style={{ padding: space.s5, gap: space.s4 }}>
        <View style={{ flexDirection: 'row', gap: space.s4, alignItems: 'center' }}>
          <KarmaRing value={user.karma} size={72} label={`Karma ${user.karma} of 100`} />
          <View style={{ flex: 1, minWidth: 0, gap: 4 }}>
            <Text style={{ fontSize: 22, fontWeight: '700', color: colors.text, letterSpacing: -0.4 }} numberOfLines={1}>
              {user.display_name}
            </Text>
            <Text style={{ fontSize: 14, color: colors.textMuted }} numberOfLines={1}>
              @{user.handle}
              {user.city ? ` · ${user.city}` : ''}
            </Text>
            {user.verification_tier !== 'none' && <TierBadge tier={user.verification_tier} />}
          </View>
        </View>

        {user.bio ? (
          <Text style={{ fontSize: 15, lineHeight: 23, color: colors.text }}>{user.bio}</Text>
        ) : null}

        <View style={{ flexDirection: 'row', gap: space.s5, flexWrap: 'wrap' }}>
          <Count label="Posts" value={user.posts_count} />
          <Count label="Karma · work" value={user.karma_work} />
          <Count label="Karma · social" value={user.karma_social} />
          <Count label="Streak" value={`${user.streak}d`} />
        </View>
      </Card>

      {notice && <NoticeText>{notice}</NoticeText>}
      {error && <ErrorText>{error}</ErrorText>}

      {/* Capabilities: additive, never a role. */}
      <Card style={{ padding: space.s5, gap: space.s3 }}>
        <SectionTitle style={{ marginBottom: space.s1 }}>What you can do</SectionTitle>
        <CapabilityRow
          title="Post and follow"
          detail="Share updates and proof of work."
          granted={user.capabilities.includes('can_post')}
        />
        <CapabilityRow
          title="Hire workers"
          detail="Post gigs and book verified professionals near you."
          granted={user.capabilities.includes('can_hire')}
          action={
            user.capabilities.includes('can_hire') ? undefined : (
              <Button
                label={busy ? 'Enabling…' : 'Enable'}
                variant="ghost"
                small
                onPress={optIntoHiring}
                disabled={busy}
              />
            )
          }
        />
        <CapabilityRow
          title="Take work"
          detail="Requires approved identity verification — someone is letting you into their home."
          granted={isWorker}
          action={isWorker ? undefined : (
            <Text style={{ fontSize: 12.5, color: colors.textFaint }}>Needs KYC</Text>
          )}
        />
      </Card>

      {/* The worker dashboard. */}
      {isWorker && worker && (
        <Card style={{ padding: space.s5, gap: space.s4 }}>
          <SectionTitle>Your work profile</SectionTitle>
          <View style={{ flexDirection: 'row', gap: space.s5, flexWrap: 'wrap' }}>
            <Count label="Jobs done" value={worker.total_jobs} />
            <Count label="Rating" value={`★ ${worker.rating.toFixed(1)}`} />
            <Count label="Hourly" value={inr(worker.hourly_rate)} />
          </View>
          {worker.category && (
            <Text style={{ fontSize: 14, color: colors.textMuted }}>Category: {worker.category}</Text>
          )}
          {worker.skills.length > 0 && (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
              {worker.skills.map((skill) => (
                <View
                  key={skill}
                  style={{
                    paddingVertical: 3,
                    paddingHorizontal: 10,
                    borderRadius: 999,
                    backgroundColor: colors.surface2,
                  }}
                >
                  <Text style={{ fontSize: 12.5, fontWeight: '600', color: colors.textMuted }}>{skill}</Text>
                </View>
              ))}
            </View>
          )}
          <Button
            label={
              busy
                ? 'Updating…'
                : worker.is_available
                  ? '● Online — visible to nearby customers'
                  : '○ Go online'
            }
            variant={worker.is_available ? 'neutral' : 'ghost'}
            textStyle={{ color: worker.is_available ? colors.white : colors.text }}
            onPress={toggleAvailable}
            disabled={busy}
          />
          <Text style={{ fontSize: 12.5, color: colors.textFaint, lineHeight: 19 }}>
            Proof posts published from completed gigs are tied to paid transactions and cannot
            be deleted.
          </Text>
        </Card>
      )}

      {/* Verification, for those who want to work. */}
      {!isWorker && <VerificationCard />}

      <SafetyContacts
        contacts={contacts}
        onChanged={(next) => setContacts(next)}
        onError={setError}
      />

      <Button label="Sign out" variant="ghost" onPress={confirmSignOut} />
    </ScrollView>
  )
}

/* ------------------------------------------------------------------ */

function Count({ label, value }: { label: string; value: string | number }) {
  return (
    <View>
      <Text style={{ fontSize: 11.5, color: colors.textFaint, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </Text>
      <Text style={{ fontSize: 19, fontWeight: '700', color: colors.text }}>{value}</Text>
    </View>
  )
}

function CapabilityRow({
  title,
  detail,
  granted,
  action,
}: {
  title: string
  detail: string
  granted: boolean
  action?: React.ReactNode
}) {
  return (
    <View style={{ flexDirection: 'row', gap: space.s3, alignItems: 'center' }}>
      <View
        accessibilityElementsHidden
        style={{
          width: 22,
          height: 22,
          borderRadius: 999,
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          backgroundColor: granted ? colors.limeWash : colors.surface2,
          borderWidth: 1,
          borderColor: granted ? colors.lime : colors.lineStrong,
        }}
      >
        <Text style={{ fontSize: 12, fontWeight: '700', color: granted ? colors.lime : colors.textFaint }}>
          {granted ? '✓' : '·'}
        </Text>
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={{ fontSize: 14.5, fontWeight: '600', color: colors.text }}>{title}</Text>
        <Text style={{ fontSize: 12.5, color: colors.textMuted, lineHeight: 18 }}>{detail}</Text>
      </View>
      {action}
    </View>
  )
}

/* ------------------------------------------------------------------ */

function VerificationCard() {
  const [documentType, setDocumentType] = useState('aadhaar')
  const [documentRef, setDocumentRef] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await post('/verification/submit', { document_type: documentType, document_ref: documentRef.trim() })
      setSubmitted(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not submit.')
    } finally {
      setBusy(false)
    }
  }

  if (submitted) {
    return (
      <Card style={{ padding: space.s5 }}>
        <Text style={{ fontSize: 17, fontWeight: '600', color: colors.text }}>Verification submitted</Text>
        <Text style={{ fontSize: 14, color: colors.textMuted, marginTop: 6, lineHeight: 22 }}>
          Only the last four digits are stored — never the full document number. An operator
          reviews it, and approval raises your karma and unlocks taking work.
        </Text>
      </Card>
    )
  }

  return (
    <Card style={{ padding: space.s5, gap: space.s3 }}>
      <SectionTitle>Want to take work?</SectionTitle>
      <Text style={{ fontSize: 14, color: colors.textMuted, lineHeight: 22 }}>
        Verify your identity first. It is the reason customers can trust a stranger in their
        home — and it is worth up to 20 karma.
      </Text>
      <View style={{ gap: 4 }}>
        {([
          ['aadhaar', 'Aadhaar — Gold tier'],
          ['pan', 'PAN — Silver tier'],
          ['govt_id', 'Other government ID — Bronze tier'],
        ] as [string, string][]).map(([value, label]) => {
          const selected = documentType === value
          return (
            <Pressable
              key={value}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              onPress={() => setDocumentType(value)}
              style={{
                borderWidth: 1,
                borderColor: selected ? colors.violet : colors.lineStrong,
                borderRadius: radii.input,
                backgroundColor: selected ? colors.violetWash : colors.surface,
                paddingVertical: 12,
                paddingHorizontal: 14,
                marginBottom: 4,
              }}
            >
              <Text style={{ fontSize: 14.5, fontWeight: selected ? '600' : '400', color: selected ? colors.violetInk : colors.text }}>
                {label}
              </Text>
            </Pressable>
          )
        })}
      </View>
      <Field
        label="Document number"
        value={documentRef}
        onChangeText={setDocumentRef}
        placeholder="1234 5678 9012"
        keyboardType="numeric"
      />
      <Text style={{ fontSize: 12.5, color: colors.textFaint }}>
        Service categories unlock once approved.
      </Text>
      {error && <ErrorText>{error}</ErrorText>}
      <Button label={busy ? 'Submitting…' : 'Submit for review'} variant="ghost" onPress={submit} disabled={busy || documentRef.trim().length < 4} />
    </Card>
  )
}

/* ------------------------------------------------------------------ */

/**
 * Trusted contacts — the people an SOS reaches. SOS is keyed on user id,
 * not IP, and a signal without a contact is just a log line, so the list
 * lives here, one tap from the emergency button.
 */
function SafetyContacts({
  contacts,
  onChanged,
  onError,
}: {
  contacts: TrustedContact[] | null
  onChanged: (next: TrustedContact[]) => void
  onError: (msg: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [relationship, setRelationship] = useState('')
  const [busy, setBusy] = useState(false)

  const add = useCallback(async () => {
    if (!contacts) return
    setBusy(true)
    try {
      const created = await post<TrustedContact>('/safety/trusted-contacts', {
        name: name.trim(),
        phone: phone.trim(),
        relationship: relationship.trim(),
      })
      onChanged([...contacts, created])
      setAdding(false)
      setName('')
      setPhone('')
      setRelationship('')
    } catch (err) {
      onError(err instanceof ApiError ? err.detail : 'Could not add the contact.')
    } finally {
      setBusy(false)
    }
  }, [contacts, name, phone, relationship, onChanged, onError])

  const remove = (contact: TrustedContact) => {
    Alert.alert('Remove contact?', `${contact.name} will no longer receive your SOS signal.`, [
      { text: 'Keep', style: 'cancel' },
      {
        text: 'Remove',
        style: 'destructive',
        onPress: async () => {
          try {
            await del(`/safety/trusted-contacts/${contact.id}`)
            onChanged(contacts?.filter((c) => c.id !== contact.id) ?? [])
          } catch (err) {
            onError(err instanceof ApiError ? err.detail : 'Could not remove the contact.')
          }
        },
      },
    ])
  }

  if (contacts === null) return null

  return (
    <Card style={{ padding: space.s5, gap: space.s3 }}>
      <SectionTitle style={{ marginBottom: space.s1 }}>Safety · trusted contacts</SectionTitle>
      {contacts.length === 0 && !adding && (
        <Text style={{ fontSize: 13.5, color: colors.textMuted, lineHeight: 20 }}>
          No trusted contacts yet. An SOS signal reaches the safety team — and the people you
          list here.
        </Text>
      )}
      {contacts.map((contact) => (
        <View
          key={contact.id}
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: space.s3,
            paddingVertical: 10,
            borderBottomWidth: 1,
            borderBottomColor: colors.line,
          }}
        >
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={{ fontSize: 14.5, fontWeight: '600', color: colors.text }} numberOfLines={1}>
              {contact.name}
              {contact.relationship ? (
                <Text style={{ fontWeight: '400', color: colors.textMuted }}> · {contact.relationship}</Text>
              ) : null}
            </Text>
            <Text style={{ fontSize: 13, color: colors.textMuted }}>{contact.phone}</Text>
          </View>
          <Pressable
            onPress={() => remove(contact)}
            accessibilityRole="button"
            accessibilityLabel={`Remove ${contact.name}`}
            style={{ padding: 8 }}
          >
            <Text style={{ color: colors.rose, fontWeight: '700', fontSize: 14 }}>✕</Text>
          </Pressable>
        </View>
      ))}

      {adding ? (
        <View style={{ gap: space.s3, paddingTop: space.s2 }}>
          <Field label="Name" value={name} onChangeText={setName} autoCapitalize="words" />
          <Field label="Phone" value={phone} onChangeText={setPhone} keyboardType="phone-pad" />
          <Field label="Relationship (optional)" value={relationship} onChangeText={setRelationship} autoCapitalize="words" />
          <View style={{ flexDirection: 'row', gap: space.s2 }}>
            <View style={{ flex: 1 }}>
              <Button label="Cancel" variant="ghost" small onPress={() => setAdding(false)} />
            </View>
            <View style={{ flex: 1 }}>
              <Button label={busy ? 'Adding…' : 'Add'} small onPress={add} disabled={busy || name.trim().length < 1 || phone.trim().length < 8} />
            </View>
          </View>
        </View>
      ) : (
        <Button label="+ Add trusted contact" variant="ghost" small onPress={() => setAdding(true)} />
      )}
    </Card>
  )
}
