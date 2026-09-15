import { useState } from 'react'
import type { Post } from '../api/types'
import { post as apiPost } from '../api/client'
import { Avatar, TierBadge } from './MatchCard'
import { KarmaRing } from './KarmaRing'
import { ProofSlider } from './ProofSlider'

/**
 * The feed card.
 *
 * For `kind=proof` it renders the before/after slider, the review, the paid
 * amount and a Hire button beside the Like button — the two products sharing
 * one surface. The karma ring travels with the author, so trust is visible
 * exactly where the hiring decision is made.
 */

const inr = (value: number) =>
  `₹${value.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`

export function PostCard({ post }: { post: Post }) {
  const [likes, setLikes] = useState(post.likes_count)
  const [liked, setLiked] = useState(post.liked_by_me)
  const [burst, setBurst] = useState(false)
  const [busy, setBusy] = useState(false)

  const toggleLike = async () => {
    if (busy) return
    setBusy(true)
    const next = !liked
    // Optimistic, so the button never waits on the network to feel responsive.
    setLiked(next)
    setLikes((n) => Math.max(0, n + (next ? 1 : -1)))
    if (next) {
      setBurst(true)
      window.setTimeout(() => setBurst(false), 260)
    }
    try {
      const updated = await apiPost<Post>(`/feed/posts/${post.id}/like`, {})
      // The server is the one that toggles; believe its count AND its direction, or a
      // stale card (liked in another tab, say) inverts the tap's meaning.
      setLikes(updated.likes_count)
      setLiked(updated.liked_by_me)
    } catch {
      setLiked(!next)
      setLikes((n) => Math.max(0, n + (next ? -1 : 1)))
    } finally {
      setBusy(false)
    }
  }

  const isProof = post.kind === 'proof'

  return (
    <article
      className="card"
      style={{
        padding: 'var(--s4)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--s3)',
        animation: 'rise var(--d-enter) var(--ease)',
      }}
    >
      {/* Identity + trust, always first. */}
      <header style={{ display: 'flex', gap: 'var(--s3)', alignItems: 'center' }}>
        <Avatar name={post.author_name ?? '?'} url={post.author_avatar} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <span style={{ fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 15 }}>
              {post.author_name}
            </span>
            {isProof && post.author_tier && post.author_tier !== 'none' && (
              <TierBadge tier={post.author_tier} />
            )}
          </div>
          <p style={{ fontSize: 12.5, color: 'var(--text-faint)' }}>
            @{post.author_handle} · {relative(post.created_at)}
            {post.category_name ? ` · ${post.category_name}` : ''}
          </p>
        </div>
        {post.author_karma !== null && (
          <KarmaRing value={post.author_karma} size={38} label={`${post.author_name}, karma ${post.author_karma}`} />
        )}
      </header>

      {/* THE PROOF — the moment the two apps become one. */}
      {isProof && post.before_url && post.after_url ? (
        <ProofSlider beforeUrl={post.before_url} afterUrl={post.after_url} />
      ) : null}

      {post.body && (
        <p style={{ fontSize: 15.5, lineHeight: 1.55 }}>
          {post.body}{' '}
          {post.hashtags.map((tag) => (
            <span key={tag} style={{ color: 'var(--violet)', fontWeight: 500 }}>
              #{tag}
            </span>
          ))}
        </p>
      )}

      {/* Evidence of a real transaction — this is what a proof post adds. */}
      {isProof && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 'var(--s3)',
            padding: '10px 12px',
            background: 'var(--surface-2)',
            borderRadius: 'var(--r-input)',
            fontSize: 13.5,
            alignItems: 'center',
          }}
        >
          {post.rating !== null && (
            <span style={{ color: 'var(--karma-gold)', fontWeight: 600 }}>
              {'★'.repeat(post.rating)}
              <span style={{ color: 'var(--text-faint)', fontWeight: 400 }}>
                {'★'.repeat(5 - post.rating)}
              </span>
            </span>
          )}
          {post.amount_earned !== null && (
            <span className="num" style={{ color: 'var(--text-muted)' }}>
              {inr(post.amount_earned)}
            </span>
          )}
          <span style={{ color: 'var(--lime)', fontWeight: 600 }}>✓ Verified gig</span>
        </div>
      )}

      <footer
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--s2)',
          borderTop: '1px solid var(--line)',
          marginTop: 2,
          paddingTop: 'var(--s3)',
        }}
      >
        <button
          type="button"
          onClick={toggleLike}
          aria-pressed={liked}
          aria-label={liked ? 'Unlike this post' : 'Like this post'}
          style={iconButtonStyle(liked ? 'var(--rose)' : 'var(--text-muted)')}
        >
          <span
            aria-hidden="true"
            style={{
              display: 'inline-block',
              transform: burst ? 'scale(1.3)' : 'scale(1)',
              transition: 'transform var(--d-enter) var(--ease)',
            }}
          >
            {liked ? '♥' : '♡'}
          </span>
          <span className="num">{likes}</span>
        </button>

        <span style={iconButtonStyle('var(--text-muted)', true)}>
          <span aria-hidden="true">💬</span>
          <span className="num">{post.comments_count}</span>
        </span>

        {/* Hire sits WITH the like button — the dual-intent surface. */}
        {isProof && (
          <button
            type="button"
            className="btn btn-primary"
            style={{ marginLeft: 'auto', minHeight: 38, padding: '6px 16px', fontSize: 14 }}
            onClick={() => {
              window.location.hash = `#/book?category=${post.category_name ?? ''}`
            }}
          >
            ⟡ Hire
          </button>
        )}
      </footer>
    </article>
  )
}

function iconButtonStyle(color: string, passive = false): React.CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    background: 'none',
    border: 'none',
    padding: '6px 10px',
    minHeight: 38,
    borderRadius: 'var(--r-input)',
    color,
    fontSize: 14,
    fontWeight: 600,
    cursor: passive ? 'default' : 'pointer',
  }
}

function relative(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const seconds = Math.floor((Date.now() - then) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d`
  // Past a month this becomes a date, and a date without a year is a guess -- a post from 2024
  // and one from last March both read "4 Mar". The year is added only when it differs, so this
  // year's rows keep the compact form (the Karma ledger always shows it, which it can afford).
  const date = new Date(iso)
  const format: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' }
  if (date.getFullYear() !== new Date().getFullYear()) format.year = 'numeric'
  return date.toLocaleDateString('en-IN', format)
}
