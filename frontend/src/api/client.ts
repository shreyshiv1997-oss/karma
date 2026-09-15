/**
 * The single HTTP boundary. Every request goes through here so that token
 * refresh, error shaping and the base path are handled in exactly one place.
 *
 * On the web, requests are same-origin: Vite proxies /api to the backend in dev, and a
 * reverse proxy does the same in production. No CORS, no exposed API host.
 *
 * In the native shell there is no reverse proxy -- the WebView serves the app from its own
 * origin -- so the base becomes an absolute origin supplied at build time. `config.ts` owns
 * that decision; this module just consumes it.
 */

import { API_BASE } from './config'

const BASE = API_BASE

export type TokenPair = { access_token: string; refresh_token: string }

let accessToken: string | null = null
let refreshToken: string | null = null
let onAuthLoss: (() => void) | null = null

export function setTokens(tokens: TokenPair | null) {
  if (tokens) {
    accessToken = tokens.access_token
    refreshToken = tokens.refresh_token
    // localStorage survives a reload; sessionStorage would log the user out.
    try {
      localStorage.setItem('karma.tokens', JSON.stringify(tokens))
    } catch {
      /* private mode -- tokens stay in memory only */
    }
  } else {
    accessToken = refreshToken = null
    try {
      localStorage.removeItem('karma.tokens')
    } catch {
      /* ignore */
    }
  }
}

export function restoreTokens(): boolean {
  try {
    const raw = localStorage.getItem('karma.tokens')
    if (!raw) return false
    const parsed = JSON.parse(raw) as TokenPair
    if (!parsed?.access_token) return false
    accessToken = parsed.access_token
    refreshToken = parsed.refresh_token
    return true
  } catch {
    return false
  }
}

export function hasToken(): boolean {
  return accessToken !== null
}

export function setAuthLossHandler(handler: () => void) {
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

async function attempt(path: string, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  return fetch(`${BASE}${path}`, { ...init, headers })
}

/** Exchanges the refresh token for a new pair. Returns false if the session is dead. */
async function refresh(): Promise<boolean> {
  if (!refreshToken) return false
  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) return false
    setTokens((await res.json()) as TokenPair)
    return true
  } catch {
    return false
  }
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
  options: { noRefresh?: boolean } = {},
): Promise<T> {
  let res = await attempt(path, init)

  // One transparent retry on an expired access token, then give up.
  //
  // `noRefresh` opts a call out of that retry, and exactly one call does: signing out. Refreshing
  // in order to log out mints a new pair, the body still carries the old refresh token, and the
  // server duly revokes *that* -- leaving the pair it just handed this client valid for another
  // fourteen days. A sign-out that replaces the session it ends is worse than no sign-out, because
  // it looks like one.
  if (!options.noRefresh && res.status === 401 && refreshToken) {
    if (await refresh()) {
      res = await attempt(path, init)
    }
  }

  if (res.status === 401) {
    setTokens(null)
    onAuthLoss?.()
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
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
 * The refresh token is read here, at send time, rather than by the caller: the server can only
 * revoke what it is handed, and a value captured earlier can already have been rotated away by a
 * background refresh. The endpoint accepts this call with an expired or missing access token -- a
 * tab asleep for an hour is exactly the one that needs to sign out -- so there is nothing to
 * pre-check locally.
 *
 * Returns whether the server confirmed the revocation. It never throws: a device with no network
 * must still be able to sign itself out, and the tokens are cleared either way. The local wipe is
 * not conditional on the server agreeing, but it is also not a substitute for it -- which is why
 * the result is reported at all.
 */
export async function signOut(): Promise<boolean> {
  let confirmed = false
  try {
    await api<{ detail: string }>(
      '/auth/logout',
      { method: 'POST', body: refreshToken ? JSON.stringify({ refresh_token: refreshToken }) : undefined },
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
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
export const patch = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) })
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' })
