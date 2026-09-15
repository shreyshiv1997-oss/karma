import { useEffect, useState } from 'react'
import { ApiError, get, patch } from '../api/client'
import type {
  AdminAnalytics,
  AdminDispute,
  AdminIncident,
  PendingVerification,
} from '../api/types'
import { useAuth } from '../store/auth'

/**
 * The trust desk.
 *
 * Everything the operations team could only do with curl before: decide pending KYC
 * submissions, triage disputes and safety incidents, and see the marketplace's
 * headline numbers. Rendered only for accounts holding the `admin` capability —
 * the backend enforces the same on every endpoint, so this gate is convenience,
 * not security.
 */

type Tab = 'verifications' | 'disputes' | 'incidents' | 'overview'

const TABS: { id: Tab; label: string }[] = [
  { id: 'verifications', label: 'Identity reviews' },
  { id: 'disputes', label: 'Disputes' },
  { id: 'incidents', label: 'Safety' },
  { id: 'overview', label: 'Overview' },
]

const CASE_STATUSES = ['in_review', 'resolved', 'dismissed'] as const

// The backend's transition table, mirrored so the desk never offers a button that is
// guaranteed to 409: decided cases are final, and in_review cannot go back to open.
const CASE_TRANSITIONS: Record<string, (typeof CASE_STATUSES)[number][] > = {
  open: ['in_review', 'resolved', 'dismissed'],
  in_review: ['resolved', 'dismissed'],
  resolved: [],
  dismissed: [],
}

export function Admin() {
  const { user } = useAuth()
  const [tab, setTab] = useState<Tab>('verifications')
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const flash = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(null), 3500)
  }

  const reload = () => setRefreshKey((k) => k + 1)

  if (!user) return null

  if (!user.capabilities.includes('admin')) {
    return (
      <main style={{ padding: 'var(--s6) 0' }}>
        <section className="card" style={{ padding: 'var(--s5)' }}>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 20 }}>Trust desk</h1>
          <p style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 6 }}>
            This area is for the operations team. Your account does not hold the admin
            capability.
          </p>
        </section>
      </main>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      <header>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 24, letterSpacing: '-0.02em' }}>
          Trust desk
        </h1>
        <p style={{ fontSize: 13.5, color: 'var(--text-faint)', marginTop: 2 }}>
          Identity reviews, disputes, safety signals — and the numbers behind them.
        </p>
      </header>

      <div
        role="tablist"
        aria-label="Trust desk sections"
        style={{
          display: 'flex',
          gap: 4,
          background: 'var(--surface-2)',
          padding: 4,
          borderRadius: 'var(--r-input)',
          overflowX: 'auto',
        }}
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => {
              setTab(t.id)
              setError(null)
            }}
            style={{
              flex: 1,
              minHeight: 38,
              minWidth: 'max-content',
              padding: '0 12px',
              border: 'none',
              borderRadius: 6,
              background: tab === t.id ? 'var(--surface)' : 'transparent',
              fontWeight: 600,
              fontSize: 13.5,
              cursor: 'pointer',
              color: tab === t.id ? 'var(--text)' : 'var(--text-muted)',
              transition: 'background-color var(--d-state) var(--ease)',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {notice && (
        <p role="status" style={{ color: 'var(--lime)', fontWeight: 600, fontSize: 14 }}>
          {notice}
        </p>
      )}

      {tab === 'verifications' && (
        <Verifications onDone={flash} onError={setError} refreshKey={refreshKey} reload={reload} />
      )}
      {tab === 'disputes' && (
        <Disputes onDone={flash} onError={setError} refreshKey={refreshKey} reload={reload} />
      )}
      {tab === 'incidents' && (
        <Incidents onDone={flash} onError={setError} refreshKey={refreshKey} reload={reload} />
      )}
      {tab === 'overview' && <Overview onError={setError} refreshKey={refreshKey} />}

      {error && (
        <p role="alert" style={{ color: 'var(--rose)', fontWeight: 500, fontSize: 14 }}>
          {error}
        </p>
      )}
    </div>
  )
}

type PanelProps = {
  onDone: (message: string) => void
  onError: (message: string | null) => void
  refreshKey: number
  reload: () => void
}

// --------------------------------------------------------------------------
// identity reviews — the KYC queue
// --------------------------------------------------------------------------
function Verifications({ onDone, onError, refreshKey, reload }: PanelProps) {
  const [rows, setRows] = useState<PendingVerification[] | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [notes, setNotes] = useState<Record<number, string>>({})

  useEffect(() => {
    get<PendingVerification[]>('/admin/verifications')
      .then((data) => {
        setRows(data)
        onError(null)
      })
      .catch((err) => onError(err instanceof ApiError ? err.detail : 'Could not load the queue.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  const decide = async (submission: PendingVerification, decision: 'approved' | 'rejected') => {
    setBusyId(submission.id)
    onError(null)
    try {
      const note = (notes[submission.id] ?? '').trim()
      await patch(`/admin/verifications/${submission.id}`, {
        decision,
        ...(note ? { note } : {}),
      })
      onDone(
        decision === 'approved'
          ? `Approved ${submission.display_name} — their karma and tier already moved.`
          : `Rejected ${submission.display_name}'s submission.`,
      )
      reload()
    } catch (err) {
      onError(err instanceof ApiError ? err.detail : 'The decision did not save.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <PanelShell
      empty={rows !== null && rows.length === 0}
      emptyText="Nobody is waiting for review. When someone submits a document, it lands here."
      loading={rows === null}
    >
      {rows?.map((row) => (
        <article
          key={row.id}
          className="card"
          style={{ padding: 'var(--s4)', display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
            <span
              className="pill"
              aria-hidden="true"
              style={{ background: 'var(--surface-2)', border: 'none', color: 'var(--text-muted)' }}
            >
              {DOC_TIER[row.document_type]}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <strong style={{ fontSize: 14.5 }}>{row.display_name}</strong>
              <span style={{ fontSize: 13, color: 'var(--text-faint)' }}> @{row.handle}</span>
            </div>
            {row.created_at && (
              <time
                dateTime={row.created_at}
                style={{ fontSize: 12, color: 'var(--text-faint)', whiteSpace: 'nowrap' }}
              >
                {new Date(row.created_at).toLocaleDateString('en-IN', {
                  day: 'numeric',
                  month: 'short',
                })}
              </time>
            )}
          </div>

          <dl style={{ display: 'flex', gap: 'var(--s5)', fontSize: 13.5 }}>
            <div>
              <dt style={{ fontSize: 11.5, color: 'var(--text-faint)', textTransform: 'uppercase' }}>
                Document
              </dt>
              <dd>{DOC_LABEL[row.document_type]}</dd>
            </div>
            <div>
              <dt style={{ fontSize: 11.5, color: 'var(--text-faint)', textTransform: 'uppercase' }}>
                Reference
              </dt>
              <dd className="num">{row.document_ref}</dd>
            </div>
          </dl>

          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor={`note-${row.id}`} style={{ fontSize: 12.5 }}>
              Reviewer note (optional, never public)
            </label>
            <input
              id={`note-${row.id}`}
              value={notes[row.id] ?? ''}
              maxLength={500}
              placeholder="e.g. Name matches the account; hologram visible"
              onChange={(e) => setNotes((prev) => ({ ...prev, [row.id]: e.target.value }))}
            />
          </div>

          <div style={{ display: 'flex', gap: 'var(--s2)' }}>
            <button
              type="button"
              className="btn btn-primary"
              style={{ flex: 1 }}
              disabled={busyId !== null}
              onClick={() => decide(row, 'approved')}
            >
              {busyId === row.id ? 'Saving…' : 'Approve'}
            </button>
            <button
              type="button"
              className="btn"
              style={{
                flex: 1,
                background: 'var(--surface)',
                color: 'var(--rose)',
                border: '1px solid var(--rose)',
              }}
              disabled={busyId !== null}
              onClick={() => decide(row, 'rejected')}
            >
              Reject
            </button>
          </div>
        </article>
      ))}
    </PanelShell>
  )
}

const DOC_LABEL: Record<PendingVerification['document_type'], string> = {
  aadhaar: 'Aadhaar',
  pan: 'PAN',
  govt_id: 'Government ID',
}

const DOC_TIER: Record<PendingVerification['document_type'], string> = {
  aadhaar: 'Gold tier on approval',
  pan: 'Silver tier on approval',
  govt_id: 'Bronze tier on approval',
}

// --------------------------------------------------------------------------
// disputes & safety incidents — the same triage shape, two queues
// --------------------------------------------------------------------------
function Disputes({ onDone, onError, refreshKey, reload }: PanelProps) {
  const [rows, setRows] = useState<AdminDispute[] | null>(null)

  useEffect(() => {
    get<AdminDispute[]>('/admin/disputes')
      .then((data) => {
        setRows(data)
        onError(null)
      })
      .catch((err) => onError(err instanceof ApiError ? err.detail : 'Could not load disputes.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  return (
    <PanelShell
      empty={rows !== null && rows.length === 0}
      emptyText="No disputes filed. A calm marketplace, at least on paper."
      loading={rows === null}
    >
      {rows?.map((row) => (
        <CaseCard
          key={row.id}
          title={`${row.gig_title} · gig #${row.gig_id}`}
          status={row.status}
          createdAt={row.created_at}
          lines={[
            ['Filed by', `${row.raised_by_name} (@${row.raised_by_handle})`],
            ['Reason', row.reason],
          ]}
          onAct={async (status) => {
            try {
              await patch(`/admin/disputes/${row.id}`, { status })
              onDone(
                status === 'dismissed'
                  ? 'Dispute dismissed — the karma it cost is being restored.'
                  : `Dispute marked ${status.replace('_', ' ')}.`,
              )
              reload()
            } catch (err) {
              onError(err instanceof ApiError ? err.detail : 'The status did not save.')
            }
          }}
        />
      ))}
    </PanelShell>
  )
}

function Incidents({ onDone, onError, refreshKey, reload }: PanelProps) {
  const [rows, setRows] = useState<AdminIncident[] | null>(null)

  useEffect(() => {
    get<AdminIncident[]>('/admin/safety/incidents')
      .then((data) => {
        setRows(data)
        onError(null)
      })
      .catch((err) => onError(err instanceof ApiError ? err.detail : 'Could not load incidents.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  return (
    <PanelShell
      empty={rows !== null && rows.length === 0}
      emptyText="No SOS signals. The best queue is the empty one."
      loading={rows === null}
    >
      {rows?.map((row) => (
        <CaseCard
          key={row.id}
          title={row.gig_id ? `SOS · gig #${row.gig_id}` : 'SOS · no gig cited'}
          status={row.status}
          createdAt={row.created_at}
          lines={[
            ['Raised by', `${row.raised_by_name} (@${row.raised_by_handle})`],
            [
              'Against',
              row.against_user_name
                ? `${row.against_user_name} (@${row.against_user_handle})`
                : '—',
            ],
            ...(row.note ? ([['Note', row.note]] as [string, string][]) : []),
            ...(row.lat != null && row.lng != null
              ? ([['Location', `${row.lat.toFixed(4)}, ${row.lng.toFixed(4)}`]] as [string, string][])
              : []),
          ]}
          urgent={row.status === 'open'}
          onAct={async (status) => {
            try {
              await patch(`/admin/safety/incidents/${row.id}`, { status })
              onDone(
                status === 'dismissed'
                  ? 'Incident dismissed — the karma it cost is being restored.'
                  : `Incident marked ${status.replace('_', ' ')}.`,
              )
              reload()
            } catch (err) {
              onError(err instanceof ApiError ? err.detail : 'The status did not save.')
            }
          }}
        />
      ))}
    </PanelShell>
  )
}

function CaseCard({
  title,
  status,
  createdAt,
  lines,
  urgent,
  onAct,
}: {
  title: string
  status: string
  createdAt: string | null
  lines: [string, string][]
  urgent?: boolean
  onAct: (status: (typeof CASE_STATUSES)[number]) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)

  const act = async (next: (typeof CASE_STATUSES)[number]) => {
    setBusy(true)
    try {
      await onAct(next)
    } finally {
      setBusy(false)
    }
  }

  // Only moves the backend would accept are offered: same-status clicks are idempotent
  // but noisy, and anything outside the transition table is a guaranteed 409.
  const options = (CASE_TRANSITIONS[status] ?? []).filter((s) => s !== status)

  return (
    <article
      className="card"
      style={{
        padding: 'var(--s4)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--s3)',
        borderColor: urgent ? 'var(--rose)' : undefined,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
        <strong style={{ flex: 1, fontSize: 14.5 }}>{title}</strong>
        <StatusPill status={status} />
        {createdAt && (
          <time dateTime={createdAt} style={{ fontSize: 12, color: 'var(--text-faint)' }}>
            {new Date(createdAt).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
          </time>
        )}
      </div>

      <dl style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13.5 }}>
        {lines.map(([label, value]) => (
          <div key={label} style={{ display: 'flex', gap: 'var(--s2)' }}>
            <dt style={{ color: 'var(--text-faint)', minWidth: 72 }}>{label}</dt>
            <dd style={{ flex: 1 }}>{value}</dd>
          </div>
        ))}
      </dl>

      {options.length > 0 && (
        <div style={{ display: 'flex', gap: 'var(--s2)', flexWrap: 'wrap' }}>
          {options.map((next) => (
            <button
              key={next}
              type="button"
              className="btn btn-ghost"
              style={{ minHeight: 36, padding: '6px 14px', fontSize: 13.5 }}
              disabled={busy}
              onClick={() => act(next)}
            >
              Mark {next.replace('_', ' ')}
            </button>
          ))}
        </div>
      )}
    </article>
  )
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === 'open'
      ? { color: 'var(--rose)', background: '#fbe9ee' }
      : status === 'in_review'
        ? { color: 'var(--karma-gold)', background: '#fdf3e3' }
        : { color: 'var(--lime)', background: '#f3f8ec' }
  return (
    <span
      className="pill"
      style={{ border: 'none', color: tone.color, background: tone.background, fontSize: 11.5 }}
    >
      {status.replace('_', ' ')}
    </span>
  )
}

// --------------------------------------------------------------------------
// overview — the marketplace's headline numbers
// --------------------------------------------------------------------------
function Overview({ onError, refreshKey }: { onError: (m: string | null) => void; refreshKey: number }) {
  const [data, setData] = useState<AdminAnalytics | null>(null)

  useEffect(() => {
    get<AdminAnalytics>('/admin/analytics')
      .then((d) => {
        setData(d)
        onError(null)
      })
      .catch((err) => onError(err instanceof ApiError ? err.detail : 'Could not load the numbers.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  if (!data) return <div className="skeleton" style={{ height: 220, borderRadius: 'var(--r-card)' }} />

  const metrics: [string, string | number][] = [
    ['Users', data.users],
    ['Workers', data.workers],
    ['Gigs', data.gigs],
    ['Gigs completed', data.gigs_completed],
    ['Posts', data.posts],
    ['Proof posts', data.proof_posts],
    ['Pending verifications', data.pending_verifications],
    ['Open disputes', data.open_disputes],
    ['Open safety signals', data.open_incidents],
    ['Proof rate', `${Math.round(data.proof_rate * 100)}%`],
  ]

  return (
    <section className="card" style={{ padding: 'var(--s5)' }}>
      <h2
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          marginBottom: 'var(--s4)',
        }}
      >
        The marketplace at a glance
      </h2>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
          gap: 'var(--s4)',
        }}
      >
        {metrics.map(([label, value]) => (
          <div key={label}>
            <div
              style={{
                fontSize: 11.5,
                color: 'var(--text-faint)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              {label}
            </div>
            <div
              className="num"
              style={{ fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 700 }}
            >
              {value}
            </div>
          </div>
        ))}
      </div>
      <p style={{ fontSize: 12.5, color: 'var(--text-faint)', marginTop: 'var(--s4)', lineHeight: 1.5 }}>
        Proof rate is the merger's north star: the share of completed gigs that became
        gig-backed proof posts.
      </p>
    </section>
  )
}

// --------------------------------------------------------------------------
// shared plumbing
// --------------------------------------------------------------------------
function PanelShell({
  children,
  loading,
  empty,
  emptyText,
}: {
  children: React.ReactNode
  loading: boolean
  empty: boolean
  emptyText: string
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
      {loading && (
        <div className="skeleton" style={{ height: 160, borderRadius: 'var(--r-card)' }} />
      )}
      {!loading && empty && (
        <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 'var(--s6) var(--s4)' }}>
          {emptyText}
        </p>
      )}
      {children}
    </div>
  )
}
