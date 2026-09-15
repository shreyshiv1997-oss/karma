/**
 * The single HTTP boundary. Every request goes through here so that token
 * refresh, error shaping and the base path are handled in exactly one place.
 *
 * RN port of `frontend/src/api/client.ts`, with one deliberate improvement:
 * the refresh is **single-flight**. The web client's known gap — two parallel
 * 401s each refreshing, one of the losers left holding a rotated token — is
 * closed here by routing every 401 through one shared promise, the same way
 * the Flutter client's `ApiClient._refresh` already does.
 */

import { API_BASE } from './config'
import { clearTokens, readTokens, writeTokens } from './tokenStore'
import type { TokenPair } from './types'

let accessToken: string | null = null
let refreshToken: string | null = null
let restorePromise: Promise<boolean> | null = null
let refreshInFlight: Promise<boolean> | null = null
let onAuthLoss: ((lost: boolean) => void) | null = null

export function setTokens(tokens: TokenPair | null) {
  if (tokens) {
    accessToken = tokens.access_token
    refreshToken = tokens.refresh_token
    // Fire and forget: persistence is for the next launch, not this response.
    void writeTokens(JSON.stringify(tokens))
  } else {
    accessToken = refreshToken = null
    restorePromise = null
    void clearTokens()
  }
}

/** Restores a token pair from secure storage. Resolves once, memoised. */
export function restoreTokens(): Promise<boolean> {
  if (!restorePromise) {
    restorePromise = readTokens().then((raw) => {
      if (!raw) return false
      try {
        const parsed = JSON.parse(raw) as TokenPair
        if (!parsed?.access_token) return false
        accessToken = parsed.access_token
        refreshToken = parsed.refresh_token ?? null
        return true
      } catch {
        return false
      }
    })
  }
  return restorePromise
}

export function hasToken(): boolean {
  return accessToken !== null
}

export function setAuthLossHandler(handler: ((lost: boolean) => void) | null) {
  onAuthLoss = handler
}

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

type Init = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: string
}

async function attempt(path: string, init: Init): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  return fetch(`${API_BASE}${path}`, { method: init.method ?? 'GET', headers, body: init.body })
}

/** Exchanges the refresh token for a new pair. Returns false if the session is dead. */
async function refreshOnce(): Promise<boolean> {
  if (!refreshToken) return false
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) return false
    const pair = (await res.json()) as TokenPair
    accessToken = pair.access_token
    refreshToken = pair.refresh_token
    restorePromise = null
    void writeTokens(JSON.stringify(pair))
    return true
  } catch {
    return false
  }
}

/** One in-flight refresh at a time, no matter how many 401s arrive together. */
function refresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = refreshOnce().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

export async function api<T>(
  path: string,
  init: Init = {},
  options: { noRefresh?: boolean } = {},
): Promise<T> {
  await restoreTokens()
  let res = await attempt(path, init)

  // One transparent retry on an expired access token, then give up.
  //
  // `noRefresh` opts a call out of that retry, and exactly one call does:
  // signing out. Refreshing in order to log out mints a new pair, the body
  // still carries the old refresh token, and the server duly revokes *that* —
  // leaving the pair it just handed this client valid for another fourteen
  // days. A sign-out that replaces the session it ends is worse than no
  // sign-out, because it looks like one.
  if (!options.noRefresh && res.status === 401 && refreshToken) {
    if (await refresh()) {
      res = await attempt(path, init)
    }
  }

  if (res.status === 401) {
    setTokens(null)
    onAuthLoss?.(true)
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body?.detail === 'string') detail = body.detail
      else if (body?.detail) detail = JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/**
 * Ends this device's session on the server, then forgets both tokens locally.
 *
 * The refresh token is read here, at send time, rather than by the caller:
 * the server can only revoke what it is handed, and a value captured earlier
 * can already have been rotated away by a background refresh.
 *
 * Returns whether the server confirmed the revocation. It never throws: a
 * device with no network must still be able to sign itself out, and the
 * tokens are cleared either way.
 */
export async function signOut(): Promise<boolean> {
  let confirmed = false
  try {
    await api<{ detail: string }>(
      '/auth/logout',
      {
        method: 'POST',
        body: refreshToken ? JSON.stringify({ refresh_token: refreshToken }) : undefined,
      },
      { noRefresh: true },
    )
    confirmed = true
  } catch {
    /* nothing to revoke, an unreachable API, or a session that was already dead */
  }
  setTokens(null)
  return confirmed
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, body?: unknown) =>
  api<T>(
    path,
    body === undefined
      ? { method: 'POST' }
      : { method: 'POST', body: typeof body === 'string' ? body : JSON.stringify(body) },
  )
export const patch = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) })
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' })
