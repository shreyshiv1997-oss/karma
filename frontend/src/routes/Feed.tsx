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
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('') // `query`, debounced and trimmed
  const [error, setError] = useState<string | null>(null)

  // Debounce: typing one character must not fire one request -- the feed refetches once
  // the poster of the query has paused, and clearing the box restores the plain feed.
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    let cancelled = false
    setPosts(null)
    const params = new URLSearchParams({ limit: '30' })
    if (filter === 'proof') params.set('kind', 'proof')
    if (search) params.set('q', search)
    get<Post[]>(`/feed/posts?${params.toString()}`)
      .then((data) => !cancelled && setPosts(data))
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [filter, search])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      {/* Search + filters ride together in the sticky header so a long feed stays searchable. */}
      <div
        style={{
          position: 'sticky',
          top: 0,
          paddingTop: 4,
          paddingBottom: 4,
          background: 'var(--paper)',
          zIndex: 1,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        <div role="search" style={{ position: 'relative' }}>
          <svg
            aria-hidden="true"
            viewBox="0 0 20 20"
            fill="none"
            style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', width: 16, height: 16, pointerEvents: 'none' }}
          >
            <circle cx="9" cy="9" r="6" stroke="var(--text-muted)" strokeWidth="2" />
            <path d="m13.5 13.5 3.5 3.5" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search posts, people, #tags…"
            aria-label="Search the feed"
            style={{
              width: '100%',
              minHeight: 40,
              padding: `8px ${query ? 36 : 14}px 8px 36px`,
              borderRadius: 'var(--r-pill)',
              border: '1px solid var(--line-strong)',
              background: 'var(--surface)',
              boxSizing: 'border-box',
              WebkitAppearance: 'none',
              appearance: 'none',
            }}
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Clear search"
              style={{
                position: 'absolute',
                right: 6,
                top: '50%',
                transform: 'translateY(-50%)',
                width: 28,
                height: 28,
                borderRadius: 'var(--r-pill)',
                border: 'none',
                background: 'var(--surface-2)',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                fontSize: 15,
                lineHeight: 1,
              }}
            >
              ×
            </button>
          )}
        </div>
        <div role="group" aria-label="Filter feed" style={{ display: 'flex', gap: 6 }}>
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
          {search ? `Nothing matches “${search}”.` : 'Nothing here yet.'}
        </p>
      )}
    </div>
  )
}
