import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Pressable, ScrollView, Text, View } from 'react-native'
import * as Haptics from 'expo-haptics'
import { ApiError, get, post } from '../api/client'
import { PaymentFlowError, releaseGigPayment, secureGigPayment } from '../api/payments'
import { subscribeToGig, type GigLinkState } from '../api/realtime'
import type { Gig, GigPayment, Stats } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { LifecycleRail } from '../components/LifecycleRail'
import {
  Button,
  Card,
  ErrorText,
  Field,
  GigStatusPill,
  LiveLink,
  NoticeText,
  PaymentLabelText,
  Segmented,
  Skeleton,
  Stat,
} from '../components/primitives'
import { colors, space } from '../theme/tokens'
import {
  asGigStatus,
  isSecuredPayment,
  isTerminal,
  nextStatusLabel,
  WORKER_NEXT,
} from '../utils/gig'
import { inr } from '../utils/format'

/**
 * Gigs — the state machine made visible.
 *
 * The lifecycle rail shows where the work actually is, and the worker drives
 * their own transitions. The SOS control is deliberately unanimated: red,
 * present, instant. Animation in an emergency would be grotesque.
 *
 * The active gig is watched over a WebSocket, so the other party's
 * transitions arrive as they happen rather than on the next reload. Polling
 * is not used as a fallback timer: if the socket is down the last known
 * state is simply shown.
 */

export function GigsScreen() {
  const { user, refreshUser } = useAuth()
  const [role, setRole] = useState<'customer' | 'worker'>('customer')
  const [gigs, setGigs] = useState<Gig[] | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [sosSent, setSosSent] = useState(false)
  const [linkState, setLinkState] = useState<GigLinkState>('closed')

  const isWorker = !!user?.capabilities?.includes('can_work')

  const load = useCallback(() => {
    get<Gig[]>(`/gigs/mine?role=${role}`)
      .then(setGigs)
      .catch((err: Error) => setError(err.message))
    get<Stats>('/gigs/stats/summary')
      .then(setStats)
      .catch(() => undefined)
    void refreshUser()
  }, [role, refreshUser])

  useEffect(() => {
    load()
  }, [load])

  const active = gigs?.find((g) => !isTerminal(g.status))
  const activeId = active?.id ?? null

  // Keep the latest updater in a ref so the subscription effect does not have
  // to re-subscribe every time the list changes.
  const setGigsRef = useRef(setGigs)
  setGigsRef.current = setGigs
  const loadRef = useRef(load)
  loadRef.current = load

  useEffect(() => {
    if (activeId === null) {
      setLinkState('closed')
      return
    }

    const subscription = subscribeToGig(activeId, {
      onStateChange: setLinkState,
      onSnapshot: (event) => {
        // Adopt the server's view on connect: it may have moved while we were away.
        const status = asGigStatus(event.data.status)
        const payment =
          typeof event.data.payment_status === 'string' ? event.data.payment_status : undefined
        if (!status) return
        setGigsRef.current((current) =>
          current?.map((g) =>
            g.id === activeId ? { ...g, status, payment_status: payment ?? g.payment_status } : g,
          ) ?? null,
        )
      },
      onEvent: (event) => {
        const status = asGigStatus(event.data.status)
        if (!status) return
        setGigsRef.current((current) =>
          current?.map((g) =>
            g.id === event.gig_id
              ? {
                  ...g,
                  status,
                  payment_status:
                    (typeof event.data.payment_status === 'string'
                      ? event.data.payment_status
                      : undefined) ?? g.payment_status,
                }
              : g,
          ) ?? null,
        )
        // A completed gig publishes proof and moves karma, so the surrounding
        // numbers need refreshing — the push tells us *that* it happened, not
        // every consequence of it.
        if (status === 'completed' || event.type === 'gig.reviewed') {
          loadRef.current()
          void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)
        }
      },
    })

    return subscription.close
  }, [activeId])

  const advance = async (gig: Gig) => {
    const next = WORKER_NEXT[gig.status]
    if (!next) return
    setBusyId(gig.id)
    setError(null)
    try {
      const updated = await post<Gig>(`/gigs/${gig.id}/status`, { status: next })
      setGigs((current) => current?.map((g) => (g.id === gig.id ? updated : g)) ?? null)
      if (next === 'completion_pending') load()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not update the gig.')
    } finally {
      setBusyId(null)
    }
  }

  const securePayment = async (gig: Gig) => {
    setBusyId(gig.id)
    setError(null)
    try {
      const payment = await secureGigPayment(gig.id)
      if (isSecuredPayment(payment.status)) load()
    } catch (err) {
      setError(
        err instanceof PaymentFlowError
          ? err.message
          : err instanceof ApiError
            ? err.detail
            : 'Could not secure the payment.',
      )
    } finally {
      setBusyId(null)
    }
  }

  const releasePayment = async (gig: Gig) => {
    const ok = await new Promise<boolean>((resolve) =>
      Alert.alert(
        'Approve the work?',
        `Approve the completed work and capture ${inr(Number(gig.total))}?`,
        [
          { text: 'Not yet', style: 'cancel' },
          { text: 'Release payment', onPress: () => resolve(true) },
        ],
      ),
    )
    if (!ok) return
    setBusyId(gig.id)
    setError(null)
    try {
      await releaseGigPayment(gig.id)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not release the payment.')
    } finally {
      setBusyId(null)
    }
  }

  const sos = async (gig: Gig | null) => {
    setError(null)
    try {
      await post('/safety/emergency', { gig_id: gig?.id ?? null })
      setSosSent(true)
      setTimeout(() => setSosSent(false), 4000)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not send the signal.')
    }
  }

  return (
    <ScrollView
      contentContainerStyle={{ padding: space.s4, gap: space.s4, paddingBottom: space.s7 }}
      keyboardShouldPersistTaps="handled"
      style={{ backgroundColor: colors.paper, flex: 1 }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.s3 }}>
        <Text style={{ fontSize: 24, fontWeight: '700', color: colors.text, letterSpacing: -0.5, flex: 1 }}>
          Gigs
        </Text>
        {isWorker && (
          <Segmented<'customer' | 'worker'>
            options={[
              { value: 'customer', label: 'Hiring' },
              { value: 'worker', label: 'Working' },
            ]}
            value={role}
            onChange={setRole}
            style={{ flex: 0 }}
          />
        )}
      </View>

      {stats && (
        <Card style={{ padding: space.s4, flexDirection: 'row', gap: space.s5, flexWrap: 'wrap' }}>
          <Stat label="Completed" value={stats.gigs_completed} />
          <Stat label="Wallet" value={inr(stats.wallet_balance)} />
          <Stat label="Lifetime" value={inr(stats.lifetime_earned)} />
        </Card>
      )}

      {error && <ErrorText>{error}</ErrorText>}
      {sosSent && (
        <NoticeText>Emergency signal sent to your trusted contacts and the safety team.</NoticeText>
      )}

      {/* The active gig gets the live view (worker side). */}
      {role === 'worker' && active && (
        <Card style={{ padding: space.s5, gap: space.s4 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.s3 }}>
            <Text style={{ fontSize: 17, fontWeight: '600', color: colors.text, flex: 1 }} numberOfLines={2}>
              {active.title}
            </Text>
            <LiveLink state={linkState} />
          </View>
          <LifecycleRail status={active.status} />
          <View style={{ flexDirection: 'row', gap: space.s2 }}>
            <View style={{ flex: 1 }}>
              <Button
                label={
                  busyId === active.id
                    ? 'Updating…'
                    : active.status === 'assigned' && !isSecuredPayment(active.payment_status)
                      ? 'Waiting for secured payment'
                      : WORKER_NEXT[active.status]
                        ? nextStatusLabel(active.status)
                        : 'Awaiting customer approval'
                }
                onPress={() => advance(active)}
                disabled={
                  busyId === active.id ||
                  !WORKER_NEXT[active.status] ||
                  (active.status === 'assigned' && !isSecuredPayment(active.payment_status))
                }
              />
            </View>
            {/* SOS: no animation, no confirmation. Friction is the enemy here. */}
            <View style={{ width: 84 }}>
              <Button label="SOS" variant="danger" onPress={() => sos(active)} disabled={busyId === active.id} />
            </View>
          </View>
        </Card>
      )}

      {gigs === null && !error && <Skeleton height={120} radius={16} />}

      <View style={{ gap: space.s3 }}>
        {gigs?.map((gig) => (
          <GigRow
            key={gig.id}
            gig={gig}
            role={role}
            busy={busyId === gig.id}
            onAdvance={() => advance(gig)}
            onSecure={() => securePayment(gig)}
            onRelease={() => releasePayment(gig)}
          />
        ))}

        {gigs?.length === 0 && (
          <View style={{ alignItems: 'center', paddingVertical: space.s7 }}>
            <Text style={{ color: colors.textMuted, fontSize: 15 }}>No gigs yet.</Text>
          </View>
        )}
      </View>
    </ScrollView>
  )
}

function GigRow({
  gig,
  role,
  busy,
  onAdvance,
  onSecure,
  onRelease,
}: {
  gig: Gig
  role: 'customer' | 'worker'
  busy: boolean
  onAdvance: () => void
  onSecure: () => void
  onRelease: () => void
}) {
  const showAdvance = role === 'worker' && !!WORKER_NEXT[gig.status]
  const waitingForPayment =
    role === 'worker' && gig.status === 'assigned' && !isSecuredPayment(gig.payment_status)

  return (
    <Card style={{ padding: space.s4, gap: space.s3 }}>
      <View style={{ flexDirection: 'row', gap: space.s3, alignItems: 'center' }}>
        <Text style={{ fontSize: 16, fontWeight: '600', color: colors.text, flex: 1 }} numberOfLines={2}>
          {gig.title}
        </Text>
        <GigStatusPill status={gig.status} />
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
        <Text style={{ fontSize: 13, color: colors.textMuted, flexShrink: 1 }} numberOfLines={1}>
          {gig.address_label || 'Location unavailable'} · gig #{gig.id} · {inr(Number(gig.total))} ·
        </Text>
        <PaymentLabelText status={gig.payment_status} />
      </View>

      {showAdvance && (
        <Button
          label={waitingForPayment ? 'Waiting for secured payment' : nextStatusLabel(gig.status)}
          variant="ghost"
          onPress={onAdvance}
          disabled={busy || waitingForPayment}
        />
      )}

      {role === 'worker' && gig.status === 'completion_pending' && (
        <NoticeText>Proof submitted · waiting for customer approval</NoticeText>
      )}

      {role === 'customer' && gig.status === 'assigned' && !isSecuredPayment(gig.payment_status) && (
        <Button
          label={busy ? 'Securing payment…' : `Secure ${inr(Number(gig.total))}`}
          onPress={onSecure}
          disabled={busy}
        />
      )}

      {role === 'customer' && gig.status === 'completion_pending' && (
        <Button
          label={busy ? 'Releasing…' : 'Approve work & release payment'}
          onPress={onRelease}
          disabled={busy}
        />
      )}

      {role === 'customer' && gig.status === 'completed' && <ReviewForm gigId={gig.id} />}
    </Card>
  )
}

/**
 * Rate, say what went well, and the same review moves both the worker's work
 * karma and the blended number — the marketplace speaking to the social half.
 */
function ReviewForm({ gigId }: { gigId: number }) {
  const [rating, setRating] = useState(5)
  const [comment, setComment] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (done) {
    return <NoticeText>Review posted — their karma just moved.</NoticeText>
  }

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await post(`/gigs/${gigId}/review`, { rating, comment: comment.trim() })
      setDone(true)
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not post the review.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <View style={{ gap: space.s2 }}>
      <Text style={{ fontSize: 13, fontWeight: '600', color: colors.textMuted }}>Rate this work</Text>
      <View style={{ flexDirection: 'row', gap: 2 }}>
        {[1, 2, 3, 4, 5].map((n) => (
          <Pressable
            key={n}
            accessibilityRole="button"
            accessibilityState={{ selected: rating === n }}
            accessibilityLabel={`${n} star${n === 1 ? '' : 's'}`}
            onPress={() => setRating(n)}
            style={{ padding: 4 }}
          >
            <Text style={{ fontSize: 26, lineHeight: 32, color: n <= rating ? colors.karmaGold : colors.lineStrong }}>
              ★
            </Text>
          </Pressable>
        ))}
      </View>
      <Field label="What went well?" value={comment} onChangeText={setComment} multiline rows={2} autoCapitalize="sentences" autoCorrect />
      {error && <ErrorText>{error}</ErrorText>}
      <Button label={busy ? 'Posting…' : 'Post review'} variant="ghost" onPress={submit} disabled={busy} />
    </View>
  )
}
