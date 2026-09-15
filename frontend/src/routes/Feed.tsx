import { useEffect, useState } from 'react'
import { get } from '../api/client'
import type { Post } from '../api/types'
import { PostCard } from '../components/PostCard'

/**
 * Home. One feed, four kinds of content, ranked with proof-of-work interleaved
 * among ordinary posts — because in KARMA the work *is* the content.
 */

type Filter = 'all' | 'proof'

export function Feed() {
  const [posts, setPosts] = useState<Post[] | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setPosts(null)
    get<Post[]>(`/feed/posts?limit=30${filter === 'proof' ? '&kind=proof' : ''}`)
      .then((data) => !cancelled && setPosts(data))
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [filter])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      <div
        role="group"
        aria-label="Filter feed"
        style={{ display: 'flex', gap: 6, position: 'sticky', top: 0, paddingTop: 4, paddingBottom: 4, background: 'var(--paper)', zIndex: 1 }}
      >
        {(
          [
            ['all', 'Everything'],
            ['proof', 'Proof of work'],
          ] as [Filter, string][]
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
            className="btn"
            style={{
              minHeight: 36,
              padding: '6px 14px',
              fontSize: 13.5,
              borderRadius: 'var(--r-pill)',
              background: filter === value ? 'var(--ink)' : 'var(--surface)',
              color: filter === value ? '#fff' : 'var(--text-muted)',
              border: `1px solid ${filter === value ? 'var(--ink)' : 'var(--line-strong)'}`,
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <p role="alert" style={{ color: 'var(--rose)' }}>
          {error}
        </p>
      )}

      {/* Skeletons sized to the final card, so nothing reflows when data lands. */}
      {posts === null &&
        !error &&
        [0, 1].map((i) => (
          <div key={i} className="card" style={{ padding: 'var(--s4)', display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
            <div style={{ display: 'flex', gap: 'var(--s3)', alignItems: 'center' }}>
              <div className="skeleton" style={{ width: 44, height: 44, borderRadius: 'var(--r-pill)' }} />
              <div style={{ flex: 1 }}>
                <div className="skeleton" style={{ height: 14, width: '40%', marginBottom: 6 }} />
                <div className="skeleton" style={{ height: 11, width: '25%' }} />
              </div>
            </div>
            <div className="skeleton" style={{ height: 200, borderRadius: 'var(--r-card)' }} />
            <div className="skeleton" style={{ height: 14, width: '70%' }} />
          </div>
        ))}

      {posts?.map((post) => <PostCard key={post.id} post={post} />)}

      {posts?.length === 0 && (
        <p style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 'var(--s7) 0' }}>
          Nothing here yet.
        </p>
      )}
    </div>
  )
}
