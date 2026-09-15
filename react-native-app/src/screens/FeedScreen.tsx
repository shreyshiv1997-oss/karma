import React, { useCallback, useRef, useState } from 'react'
import { FlatList, Pressable, RefreshControl, Text, View } from 'react-native'
import { get } from '../api/client'
import type { Post } from '../api/types'
import { PostCard } from '../components/PostCard'
import { useCreateSheet } from '../components/CreateSheet'
import { ErrorText, Skeleton } from '../components/primitives'
import { colors, space } from '../theme/tokens'

/**
 * Home. One feed, four kinds of content, ranked with proof-of-work interleaved
 * among ordinary posts — because in KARMA the work *is* the content.
 *
 * Keyset pagination, exactly as the backend serves it: `before_id` is the
 * last id of the previous page, and a short page is the end of the feed.
 * Offset would reshuffle rows between pages whenever anyone posted in the
 * gap — the same post twice, or none at all.
 */

type Filter = 'all' | 'proof'

const PAGE = 20

export function FeedScreen() {
  const [posts, setPosts] = useState<Post[] | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [ended, setEnded] = useState(false)
  const lastIdRef = useRef<number | null>(null)
  const sheet = useCreateSheet()

  const load = useCallback(
    async (opts: { reset?: boolean } = {}) => {
      setError(null)
      if (opts.reset) {
        setPosts(null)
        setEnded(false)
        lastIdRef.current = null
      }
      try {
        const params = new URLSearchParams({ limit: String(PAGE) })
        if (filter === 'proof') params.set('kind', 'proof')
        if (lastIdRef.current !== null) params.set('before_id', String(lastIdRef.current))
        const data = await get<Post[]>(`/feed/posts?${params.toString()}`)
        const next = opts.reset ? data : [...(posts ?? []), ...data]
        setPosts(next)
        if (data.length < PAGE) setEnded(true)
        else if (data.length > 0) {
          lastIdRef.current = data[data.length - 1].id
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not load the feed.')
      }
    },
    [filter, posts],
  )

  React.useEffect(() => {
    void load({ reset: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  const onRefresh = async () => {
    setRefreshing(true)
    await load({ reset: true })
    setRefreshing(false)
  }

  const onEndReached = () => {
    if (ended || loadingMore || (posts ?? []).length === 0) return
    setLoadingMore(true)
    void load().finally(() => setLoadingMore(false))
  }

  const renderSkeleton = () => (
    <View style={{ padding: space.s4, gap: space.s4 }}>
      {[0, 1].map((i) => (
        <View
          key={i}
          style={{
            padding: space.s4,
            gap: space.s3,
            backgroundColor: colors.surface,
            borderRadius: 16,
            borderWidth: 1,
            borderColor: colors.line,
          }}
        >
          <View style={{ flexDirection: 'row', gap: space.s3, alignItems: 'center' }}>
            <Skeleton height={44} width={44} radius={999} />
            <View style={{ flex: 1, gap: 6 }}>
              <Skeleton height={14} width="40%" />
              <Skeleton height={11} width="25%" />
            </View>
          </View>
          <Skeleton height={160} radius={16} />
          <Skeleton height={14} width="70%" />
        </View>
      ))}
    </View>
  )

  return (
    <View style={{ flex: 1, backgroundColor: colors.paper }}>
      {/* Filter chips. */}
      <View style={{ flexDirection: 'row', gap: 6, paddingHorizontal: space.s4, paddingTop: space.s2, paddingBottom: space.s2 }}>
        {([
          ['all', 'Everything'],
          ['proof', 'Proof of work'],
        ] as [Filter, string][]).map(([value, label]) => {
          const selected = filter === value
          return (
            <Pressable
              key={value}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              onPress={() => setFilter(value)}
              style={{
                minHeight: 36,
                paddingHorizontal: 14,
                borderRadius: 999,
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: selected ? colors.ink : colors.surface,
                borderWidth: 1,
                borderColor: selected ? colors.ink : colors.lineStrong,
              }}
            >
              <Text style={{ fontSize: 13.5, fontWeight: '600', color: selected ? colors.white : colors.textMuted }}>
                {label}
              </Text>
            </Pressable>
          )
        })}
      </View>

      <FlatList
        data={posts ?? []}
        keyExtractor={(p) => String(p.id)}
        renderItem={({ item }) => (
          <View style={{ padding: space.s4 }}>
            <PostCard
              post={item}
              onHire={(post) => sheet.open({ preselectCategory: post.category_name ?? undefined })}
            />
          </View>
        )}
        contentContainerStyle={posts === null ? undefined : { paddingBottom: space.s6 }}
        ListEmptyComponent={
          posts === null ? (
            renderSkeleton()
          ) : (
            <View style={{ alignItems: 'center', paddingVertical: space.s7 }}>
              <Text style={{ color: colors.textMuted, fontSize: 15 }}>Nothing here yet.</Text>
              <Text style={{ color: colors.violet, fontWeight: '600', fontSize: 14, marginTop: space.s2 }}>
                Tap the + to share the first post.
              </Text>
            </View>
          )
        }
        ListFooterComponent={loadingMore ? (
          <View style={{ padding: space.s4 }}>
            <Skeleton height={120} radius={16} />
          </View>
        ) : null}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.violet} />
        }
        onEndReachedThreshold={0.4}
        onEndReached={onEndReached}
        style={{ backgroundColor: colors.paper }}
      />

      {error && (
        <View style={{ paddingHorizontal: space.s4, paddingVertical: space.s2 }}>
          <ErrorText>{error}</ErrorText>
        </View>
      )}
    </View>
  )
}
