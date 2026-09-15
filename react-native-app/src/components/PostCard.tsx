import React, { useState } from 'react'
import { Pressable, Text, View } from 'react-native'
import { post as apiPost } from '../api/client'
import type { Post } from '../api/types'
import { Avatar, TierBadge } from './Avatar'
import { Card, RiseIn } from './primitives'
import { KarmaRing } from './KarmaRing'
import { ProofSlider } from './ProofSlider'
import { colors, space } from '../theme/tokens'
import { inr, relative } from '../utils/format'

/**
 * The feed card.
 *
 * For `kind=proof` it renders the before/after slider, the review, the paid
 * amount and a Hire button beside the Like button — the two products sharing
 * one surface. The karma ring travels with the author, so trust is visible
 * exactly where the hiring decision is made.
 */

export function PostCard({ post, onHire }: { post: Post; onHire?: (post: Post) => void }) {
  const [likes, setLikes] = useState(post.likes_count)
  const [liked, setLiked] = useState(false)
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
      setTimeout(() => setBurst(false), 260)
    }
    try {
      const updated = await apiPost<Post>(`/feed/posts/${post.id}/like`)
      setLikes(updated.likes_count)
    } catch {
      setLiked(!next)
      setLikes((n) => Math.max(0, n + (next ? -1 : 1)))
    } finally {
      setBusy(false)
    }
  }

  const isProof = post.kind === 'proof'

  return (
    <RiseIn>
      <Card style={{ padding: space.s4, gap: space.s3 }}>
        {/* Identity + trust, always first. */}
        <View style={{ flexDirection: 'row', gap: space.s3, alignItems: 'center' }}>
          <Avatar name={post.author_name ?? '?'} url={post.author_avatar} />
          <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <Text style={{ fontWeight: '600', fontSize: 15, color: colors.text, flexShrink: 1 }} numberOfLines={1}>
                {post.author_name}
              </Text>
              {isProof && post.author_tier && post.author_tier !== 'none' && (
                <TierBadge tier={post.author_tier} />
              )}
            </View>
            <Text style={{ fontSize: 12.5, color: colors.textFaint }} numberOfLines={1}>
              @{post.author_handle} · {relative(post.created_at)}
              {post.category_name ? ` · ${post.category_name}` : ''}
            </Text>
          </View>
          {post.author_karma !== null && (
            <KarmaRing value={post.author_karma} size={38} label={`${post.author_name}, karma ${post.author_karma}`} />
          )}
        </View>

        {/* THE PROOF — the moment the two apps become one. */}
        {isProof && post.before_url && post.after_url && (
          <ProofSlider beforeUrl={post.before_url} afterUrl={post.after_url} />
        )}

        {post.body ? (
          <Text style={{ fontSize: 15.5, lineHeight: 24, color: colors.text }}>
            {post.body}{' '}
            {post.hashtags.map((tag) => (
              <Text key={tag} style={{ color: colors.violet, fontWeight: '500' }}>
                #{tag}{' '}
              </Text>
            ))}
          </Text>
        ) : null}

        {/* Evidence of a real transaction — this is what a proof post adds. */}
        {isProof && (
          <View
            style={{
              flexDirection: 'row',
              flexWrap: 'wrap',
              gap: space.s3,
              paddingVertical: 10,
              paddingHorizontal: 12,
              backgroundColor: colors.surface2,
              borderRadius: 8,
              alignItems: 'center',
            }}
          >
            {post.rating !== null && (
              <Text style={{ color: colors.karmaGold, fontWeight: '600', fontSize: 13.5 }}>
                {'★'.repeat(post.rating)}
                <Text style={{ color: colors.textFaint, fontWeight: '400' }}>{'★'.repeat(5 - post.rating)}</Text>
              </Text>
            )}
            {post.amount_earned !== null && (
              <Text style={{ color: colors.textMuted, fontSize: 13.5 }}>{inr(post.amount_earned)}</Text>
            )}
            <Text style={{ color: colors.lime, fontWeight: '600', fontSize: 13.5 }}>✓ Verified gig</Text>
          </View>
        )}

        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: space.s2,
            borderTopWidth: 1,
            borderTopColor: colors.line,
            paddingTop: space.s3,
          }}
        >
          <Pressable
            onPress={toggleLike}
            accessibilityRole="button"
            accessibilityState={{ selected: liked }}
            accessibilityLabel={liked ? 'Unlike this post' : 'Like this post'}
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: 6,
              paddingVertical: 6,
              paddingHorizontal: 10,
              borderRadius: 8,
              minHeight: 38,
            }}
          >
            <Text
              accessibilityElementsHidden
              style={{
                color: liked ? colors.rose : colors.textMuted,
                fontSize: burst ? 19 : 16,
                lineHeight: 1,
              }}
            >
              {liked ? '♥' : '♡'}
            </Text>
            <Text style={{ color: colors.textMuted, fontSize: 14, fontWeight: '600' }}>{likes}</Text>
          </Pressable>

          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: 6,
              paddingVertical: 6,
              paddingHorizontal: 10,
              borderRadius: 8,
              minHeight: 38,
            }}
          >
            <Text accessibilityElementsHidden style={{ fontSize: 15 }}>
              💬
            </Text>
            <Text style={{ color: colors.textMuted, fontSize: 14, fontWeight: '600' }}>{post.comments_count}</Text>
          </View>

          {/* Hire sits WITH the like button — the dual-intent surface. */}
          {isProof && onHire && (
            <Pressable
              onPress={() => onHire(post)}
              accessibilityRole="button"
              accessibilityLabel={`Hire ${post.author_name}`}
              style={{
                marginLeft: 'auto',
                minHeight: 38,
                paddingHorizontal: 16,
                borderRadius: 8,
                backgroundColor: colors.violet,
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ color: colors.white, fontSize: 14, fontWeight: '600' }}>Hire</Text>
            </Pressable>
          )}
        </View>
      </Card>
    </RiseIn>
  )
}
