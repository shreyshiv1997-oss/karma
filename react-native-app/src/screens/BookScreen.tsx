import React, { useEffect, useState } from 'react'
import { Alert, Pressable, ScrollView, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { SafeAreaView } from 'react-native-safe-area-context'
import type { RootStackParamList } from '../navigation/TabsNavigator'
import type { NativeStackScreenProps } from '@react-navigation/native-stack'
import { ApiError, get, post } from '../api/client'
import type { Candidate, Category, FareBreakdown, GeocodedPlace, Gig } from '../api/types'
import { canHire, useAuth } from '../auth/AuthContext'
import { FareBreakdownView } from '../components/FareBreakdown'
import { MatchCard } from '../components/MatchCard'
import { Button, Card, ErrorText, Field, Segmented, Skeleton } from '../components/primitives'
import { colors, radii, space } from '../theme/tokens'
import { getConsentedDeviceFix } from '../location/location'

/**
 * The booking flow — Labour Link's four-step wizard, kept almost intact, with
 * the estimate updating live and every multiplier shown as it activates.
 *
 * Step 3 is the fusion: ranked matches carrying their reasons *and* their
 * social proof.
 *
 * Location has two explicit paths — neither invents coordinates:
 *   - Use current location shows KARMA's disclosure first (Alert), then asks
 *     the OS for a one-time foreground fix.
 *   - Search address leaves the text as text until the user agrees to send
 *     it to the configured geocoder and chooses one attributed result.
 */

const STEPS = ['What', 'When & where', 'Who', 'Payment'] as const

type SelectedLocation = {
  lat: number
  lng: number
  source: 'device' | 'geocoded'
  accuracy?: number
  provider?: string
  attribution?: string
  note?: string
}

type Props = NativeStackScreenProps<RootStackParamList, 'Book'>

export function BookScreen({ route, navigation }: Props) {
  const { user, grant, refreshUser } = useAuth()
  const [step, setStep] = useState(0)
  const [categories, setCategories] = useState<Category[]>([])
  const [category, setCategory] = useState<Category | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [hours, setHours] = useState(2)
  const [urgency, setUrgency] = useState<'standard' | 'urgent'>('standard')
  const [address, setAddress] = useState('')
  const [location, setLocation] = useState<SelectedLocation | null>(null)
  const [locationResults, setLocationResults] = useState<GeocodedPlace[]>([])
  const [fare, setFare] = useState<FareBreakdown | null>(null)
  const [gig, setGig] = useState<Gig | null>(null)
  const [matches, setMatches] = useState<Candidate[] | null>(null)
  const [bookedWith, setBookedWith] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    get<Category[]>('/categories').then(setCategories).catch(() => undefined)
  }, [])

  // Preselection from a proof post's Hire button.
  useEffect(() => {
    const wanted = route.params?.preselectCategory
    if (!wanted) return
    get<Category[]>('/categories')
      .then((all) => {
        const found = all.find((c) => c.name.toLowerCase() === wanted.toLowerCase())
        if (found) setCategory(found)
      })
      .catch(() => undefined)
  }, [route.params?.preselectCategory])

  // The estimate recomputes live as the inputs change — never on submit.
  useEffect(() => {
    if (!category || !location) {
      setFare(null)
      return
    }
    let cancelled = false
    post<FareBreakdown>('/gigs/estimate', {
      category_id: category.id,
      lat: location.lat,
      lng: location.lng,
      estimated_hours: hours,
      urgency,
    })
      .then((data) => {
        if (!cancelled) setFare(data)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [category, hours, urgency, location])

  const canBook = canHire(user)

  const consentedGeocode = async () => {
    if (address.trim().length < 3) {
      setError('Type at least 3 characters before searching.')
      return
    }
    const ok = await new Promise<boolean>((resolve) =>
      Alert.alert(
        'Share this address?',
        'Send this typed address to KARMA’s configured geocoding provider? Only the result you select will be saved with the gig.',
        [
          { text: 'Not now', style: 'cancel' },
          { text: 'Share', onPress: () => resolve(true) },
        ],
      ),
    )
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      const places = await post<GeocodedPlace[]>('/locations/geocode', {
        query: address.trim(),
        consent: true,
        limit: 5,
      })
      setLocationResults(places)
      if (places.length === 0) setError('No matching address was found.')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Address lookup is unavailable.')
    } finally {
      setBusy(false)
    }
  }

  const useCurrentLocation = async () => {
    const ok = await new Promise<boolean>((resolve) =>
      Alert.alert(
        'Use your current location?',
        'Request your precise location once? KARMA uses it for nearby matching and sends it to the configured geocoder for an address label. It is not requested in the background.',
        [
          { text: 'Not now', style: 'cancel' },
          { text: 'Share once', onPress: () => resolve(true) },
        ],
      ),
    )
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      const fix = await getConsentedDeviceFix()
      const point: SelectedLocation = {
        lat: fix.lat,
        lng: fix.lng,
        source: 'device',
        accuracy: fix.accuracy_m ?? undefined,
        note:
          fix.accuracy_m != null
            ? `One-time device fix selected · ±${Math.round(fix.accuracy_m)} m. Editing the label does not move it.`
            : 'One-time device fix selected. Editing the label does not move it.',
      }
      setLocation(point)
      setLocationResults([])
      try {
        const place = await post<GeocodedPlace | null>('/locations/reverse', {
          lat: point.lat,
          lng: point.lng,
          consent: true,
        })
        setAddress(place?.label ?? `${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}`)
        if (place) {
          setLocation({ ...point, provider: place.provider, attribution: place.attribution })
        }
      } catch {
        setAddress(`${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Location was unavailable or permission was not granted.')
    } finally {
      setBusy(false)
    }
  }

  const selectAddress = (place: GeocodedPlace) => {
    setAddress(place.label)
    setLocation({
      lat: place.lat,
      lng: place.lng,
      source: 'geocoded',
      provider: place.provider,
      attribution: place.attribution,
      note: `Using the result you selected from ${place.provider} · ${place.attribution}. Editing the label does not move it.`,
    })
    setLocationResults([])
  }

  const createGig = async () => {
    if (!category || !location || address.trim().length === 0) {
      setError('Search and select an address, or consent to a one-time device location.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (!canBook) {
        await grant('can_hire')
        await refreshUser()
      }
      const created = await post<Gig>('/gigs', {
        category_id: category.id,
        title: title.trim(),
        description: description.trim(),
        lat: location.lat,
        lng: location.lng,
        address_label: address.trim(),
        location_source: location.source,
        location_accuracy_m: location.accuracy ?? null,
        geocoder: location.provider ?? null,
        location_consent: true,
        estimated_hours: hours,
        urgency,
      })
      setGig(created)
      const found = await post<Candidate[]>('/matching/find', { gig_id: created.id })
      setMatches(found)
      setStep(2)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not post the gig.')
    } finally {
      setBusy(false)
    }
  }

  const book = async (candidate: Candidate) => {
    if (!gig) return
    setBusy(true)
    setError(null)
    try {
      const assigned = await post<Gig>(`/gigs/${gig.id}/assign?worker_id=${candidate.user_id}`, {})
      setGig(assigned)
      setBookedWith(candidate.user_id)
      setStep(3)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not book that worker.')
    } finally {
      setBusy(false)
    }
  }

  const progress = ((step + 1) / STEPS.length) * 100

  return (
    <View style={{ flex: 1, backgroundColor: colors.paper }}>
      <SafeAreaView edges={['top'] as const} style={{ backgroundColor: colors.paper }}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: space.s2,
            paddingHorizontal: space.s4,
            paddingVertical: 10,
            borderBottomWidth: 1,
            borderBottomColor: colors.line,
          }}
        >
          <Pressable
            onPress={() => navigation.goBack()}
            accessibilityRole="button"
            accessibilityLabel="Close"
            style={{ padding: 6 }}
          >
            <Ionicons name="close" size={20} color={colors.textMuted} />
          </Pressable>
          <Text style={{ fontSize: 20, fontWeight: '700', color: colors.text, letterSpacing: -0.4 }}>
            Post a gig
          </Text>
        </View>
      </SafeAreaView>
      <ScrollView contentContainerStyle={{ padding: space.s4, gap: space.s4 }} keyboardShouldPersistTaps="handled">
        <View>
          <View
            style={{
              height: 4,
              backgroundColor: colors.line,
              borderRadius: 999,
              marginTop: space.s3,
              overflow: 'hidden',
            }}
          >
            <View
              style={{
                height: '100%',
                width: `${progress}%`,
                backgroundColor: colors.violet,
              }}
            />
          </View>
          <Text style={{ fontSize: 13, color: colors.textFaint, marginTop: 6 }}>
            Step {step + 1} of {STEPS.length} · {STEPS[step]}
          </Text>
        </View>

        {error && <ErrorText>{error}</ErrorText>}

        {/* ── STEP 1: what ─────────────────────────────────────────── */}
        {step === 0 && (
          <Card style={{ padding: space.s5, gap: space.s4 }}>
            <View style={{ gap: space.s3 }}>
              <Text style={{ fontSize: 15, fontWeight: '600', color: colors.text }}>
                What do you need done?
              </Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.s2 }}>
                {categories.map((c) => {
                  const selected = category?.id === c.id
                  return (
                    <Pressable
                      key={c.id}
                      accessibilityRole="button"
                      accessibilityState={{ selected }}
                      onPress={() => setCategory(c)}
                      style={{
                        flex: 1,
                        flexBasis: '30%',
                        minHeight: 72,
                        padding: space.s3,
                        borderRadius: radii.input,
                        borderWidth: 1,
                        borderColor: selected ? colors.violet : colors.lineStrong,
                        backgroundColor: selected ? colors.violetWash : colors.surface,
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 4,
                      }}
                    >
                      <Text accessibilityElementsHidden style={{ fontSize: 22 }}>
                        {c.emoji}
                      </Text>
                      <Text
                        numberOfLines={1}
                        style={{ fontSize: 13, fontWeight: '600', color: selected ? colors.violetInk : colors.text }}
                      >
                        {c.name}
                      </Text>
                    </Pressable>
                  )
                })}
              </View>
              {categories.length === 0 && <Skeleton height={72} radius={radii.input} />}
            </View>

            <Field label="Title" value={title} onChangeText={setTitle} placeholder="Rewire 3-room flat" />

            <Field
              label="Details"
              value={description}
              onChangeText={setDescription}
              placeholder="Old aluminium wiring, needs full replacement"
              multiline
              rows={3}
              autoCapitalize="sentences"
              autoCorrect
            />

            <Button
              label="Continue"
              onPress={() => setStep(1)}
              disabled={!category || title.trim().length < 3}
            />
          </Card>
        )}

        {/* ── STEP 2: when & where ─────────────────────────────────── */}
        {step === 1 && (
          <Card style={{ padding: space.s5, gap: space.s4 }}>
            <Field
              label="Service address or landmark"
              value={address}
              onChangeText={(t) => {
                setAddress(t)
                setLocationResults([])
              }}
              placeholder="Type, then choose Search address"
            />
            <View style={{ flexDirection: 'row', gap: space.s2 }}>
              <View style={{ flex: 1 }}>
                <Button label="Search address" variant="ghost" onPress={consentedGeocode} disabled={busy} />
              </View>
              <View style={{ flex: 1 }}>
                <Button label="Use current" variant="ghost" onPress={useCurrentLocation} disabled={busy} />
              </View>
            </View>

            {locationResults.length > 0 && (
              <View style={{ gap: 6 }}>
                {locationResults.map((place) => (
                  <Pressable
                    key={place.place_id}
                    accessibilityRole="button"
                    onPress={() => selectAddress(place)}
                    style={{
                      borderWidth: 1,
                      borderColor: colors.lineStrong,
                      borderRadius: radii.input,
                      backgroundColor: colors.surface,
                      padding: 10,
                    }}
                  >
                    <Text style={{ fontSize: 14, color: colors.text }}>{place.label}</Text>
                    <Text style={{ fontSize: 12, color: colors.textFaint, marginTop: 2 }}>
                      {place.provider} · {place.attribution}
                    </Text>
                  </Pressable>
                ))}
              </View>
            )}

            <Text style={{ color: location ? colors.textFaint : colors.karmaGold, fontSize: 12, lineHeight: 18 }}>
              {location
                ? location.note ?? 'Coordinates set. Editing the label does not move them.'
                : 'Typing alone does not assign coordinates. Select a search result or explicitly share current location.'}
            </Text>

            <View style={{ gap: 6 }}>
              <Text style={{ fontSize: 13, fontWeight: '600', color: colors.textMuted }}>Estimated hours</Text>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.s3 }}>
                <Button label="−" variant="ghost" small onPress={() => setHours((h) => Math.max(1, h - 0.5))} style={{ width: 44 }} />
                <Text style={{ fontSize: 15, color: colors.text, fontWeight: '600', minWidth: 70, textAlign: 'center' }}>
                  {hours} {hours === 1 ? 'hour' : 'hours'}
                </Text>
                <Button label="+" variant="ghost" small onPress={() => setHours((h) => Math.min(12, h + 0.5))} style={{ width: 44 }} />
              </View>
            </View>

            <View style={{ gap: space.s2 }}>
              <Text style={{ fontSize: 13, fontWeight: '600', color: colors.textMuted }}>Urgency</Text>
              <Segmented<'standard' | 'urgent'>
                options={[
                  { value: 'standard', label: 'Standard' },
                  { value: 'urgent', label: 'Urgent · today' },
                ]}
                value={urgency}
                onChange={setUrgency}
              />
            </View>

            {/* Live, transparent pricing. */}
            {fare && (
              <View style={{ padding: space.s4, backgroundColor: colors.surface2, borderRadius: radii.input }}>
                <Text style={{ fontSize: 13, fontWeight: '600', color: colors.textMuted, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: space.s3 }}>
                  Estimated price
                </Text>
                <FareBreakdownView fare={fare} />
              </View>
            )}

            <View style={{ flexDirection: 'row', gap: space.s2 }}>
              <View style={{ width: 90 }}>
                <Button label="Back" variant="ghost" onPress={() => setStep(0)} />
              </View>
              <View style={{ flex: 1 }}>
                <Button label={busy ? 'Finding workers…' : 'Find workers'} onPress={createGig} disabled={busy || !location} />
              </View>
            </View>
          </Card>
        )}

        {/* ── STEP 3: who ──────────────────────────────────────────── */}
        {step === 2 && (
          <View style={{ gap: space.s3 }}>
            <Text style={{ fontSize: 18, fontWeight: '600', color: colors.text }}>
              {matches?.length ?? 0} worker{matches?.length === 1 ? '' : 's'} near you
            </Text>
            {matches === null && <Skeleton height={160} radius={radii.card} />}
            {matches?.map((candidate) => (
              <MatchCard
                key={candidate.user_id}
                candidate={candidate}
                onBook={book}
                busy={busy}
                booked={bookedWith === candidate.user_id}
              />
            ))}
            {matches?.length === 0 && (
              <View style={{ alignItems: 'center', paddingVertical: space.s6 }}>
                <Text style={{ color: colors.textMuted, textAlign: 'center', fontSize: 14, lineHeight: 21 }}>
                  No verified workers within 5 km right now.
                  {'\n'}
                  Try a different category or time.
                </Text>
              </View>
            )}
          </View>
        )}

        {/* ── STEP 4: review ───────────────────────────────────────── */}
        {step === 3 && gig && (
          <Card style={{ padding: space.s5, gap: space.s4 }}>
            <View style={{ alignItems: 'center', paddingVertical: space.s4, gap: space.s2 }}>
              <Text accessibilityElementsHidden style={{ fontSize: 40, color: colors.lime }}>
                ✓
              </Text>
              <Text style={{ fontSize: 22, fontWeight: '700', color: colors.text }}>
                Gig booked · payment required
              </Text>
              <Text style={{ color: colors.textMuted, fontSize: 14.5, textAlign: 'center', lineHeight: 22 }}>
                Secure the fixed price under <Text style={{ fontWeight: '700' }}>Gigs</Text>. The worker
                cannot travel until the payment is authorised.
              </Text>
            </View>
            <FareBreakdownView fare={gig.fare_breakdown} emphasis="total" />
            <Button label="Secure payment & track" onPress={() => navigation.navigate('Tabs', { screen: 'Gigs' })} />
          </Card>
        )}
      </ScrollView>
    </View>
  )
}
