/**
 * The HTTP boundary, tested against a scripted fetch.
 *
 * Covers the four behaviours the rest of the app depends on: bearer
 * attachment, one transparent refresh on 401, single-flight refresh under
 * concurrent 401s, and a sign-out that revokes the token it holds *at send
 * time* without refreshing first.
 */

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}))
jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true,
  default: {
    getItem: jest.fn(),
    setItem: jest.fn(),
    removeItem: jest.fn(),
  },
}))

import * as SecureStore from 'expo-secure-store'
import { ApiError, api, get, setTokens, signOut } from '../src/api/client'

const fetchMock = jest.fn()
;(global as Record<string, unknown>).fetch = fetchMock

beforeEach(() => {
  fetchMock.mockReset()
  // Deterministic storage: nothing restored, in-memory tokens are what we set.
  ;(SecureStore.getItemAsync as jest.Mock).mockResolvedValue(null)
  ;(SecureStore.setItemAsync as jest.Mock).mockResolvedValue(undefined)
  ;(SecureStore.deleteItemAsync as jest.Mock).mockResolvedValue(undefined)
  setTokens(null)
})

function json(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: `status ${status}`,
    json: () => Promise.resolve(body),
  } as Response
}

const tick = () => new Promise((r) => setTimeout(r, 0))

describe('api', () => {
  it('attaches the bearer token and parses the body', async () => {
    setTokens({ access_token: 'a1', refresh_token: 'r1' })
    fetchMock.mockResolvedValueOnce(json(200, { hello: 'world' }))

    const data = await get<{ hello: string }>('/hello')

    expect(data).toEqual({ hello: 'world' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/hello')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer a1')
  })

  it('refreshes once on a 401 and retries with the new token', async () => {
    setTokens({ access_token: 'a1', refresh_token: 'r1' })
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: 'token expired' })) // the original call
      .mockResolvedValueOnce(json(200, { access_token: 'a2', refresh_token: 'r2' })) // the refresh
      .mockResolvedValueOnce(json(200, { value: 42 })) // the retry

    const data = await api<{ value: number }>('/needs-auth')

    expect(data).toEqual({ value: 42 })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    const refreshCall = fetchMock.mock.calls[1]
    expect(String(refreshCall[0])).toContain('/auth/refresh')
    expect(refreshCall[1].body).toBe(JSON.stringify({ refresh_token: 'r1' }))
    const retryCall = fetchMock.mock.calls[2]
    expect((retryCall[1].headers as Record<string, string>).Authorization).toBe('Bearer a2')
  })

  it('throws an ApiError carrying the server detail when the session is dead', async () => {
    setTokens({ access_token: 'a1', refresh_token: 'r1' })
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: 'token expired' }))
      .mockResolvedValueOnce(json(401, { detail: 'refresh token expired' }))

    let caught: unknown
    try {
      await api('/needs-auth')
    } catch (err) {
      caught = err
    }

    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(401)
    expect((caught as ApiError).detail).toBe('token expired')
    // The refresh failed, so the retry never happens.
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('shares one refresh across concurrent 401s (single-flight)', async () => {
    setTokens({ access_token: 'a1', refresh_token: 'r1' })

    let resolveRefresh: (value: Response) => void
    const refreshPending = new Promise<Response>((resolve) => {
      resolveRefresh = resolve
    })

    let originalCalls = 0
    fetchMock.mockImplementation((url: string) => {
      const u = String(url)
      if (u.includes('/auth/refresh')) return refreshPending
      // The first two calls are the original /one and /two; they 401.
      // Everything after that is a retry and succeeds.
      originalCalls += 1
      if (originalCalls <= 2) return Promise.resolve(json(401, { detail: 'expired' }))
      return Promise.resolve(json(200, u.includes('/one') ? { n: 1 } : { n: 2 }))
    })

    const p1 = api<{ n: number }>('/one')
    const p2 = api<{ n: number }>('/two')
    // Let both 401s land and both call for the refresh.
    await tick()
    await tick()

    resolveRefresh!(json(200, { access_token: 'a2', refresh_token: 'r2' }))
    await expect(p1).resolves.toEqual({ n: 1 })
    await expect(p2).resolves.toEqual({ n: 2 })

    const refreshCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes('/auth/refresh'),
    )
    expect(refreshCalls).toHaveLength(1)
  })

  it('never refreshes on a call marked noRefresh', async () => {
    setTokens({ access_token: 'a1', refresh_token: 'r1' })
    fetchMock.mockResolvedValueOnce(json(401, { detail: 'expired' }))

    let caught: unknown
    try {
      await api('/auth/logout', { method: 'POST', body: '{}' }, { noRefresh: true })
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect(fetchMock).toHaveBeenCalledTimes(1) // no second attempt, no refresh
  })
})

describe('signOut', () => {
  it('revokes with the refresh token held at send time, then wipes locally', async () => {
    setTokens({ access_token: 'a1', refresh_token: 'r-at-send-time' })
    fetchMock.mockResolvedValueOnce(json(200, { detail: 'logged out' }))

    const confirmed = await signOut()

    expect(confirmed).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/auth/logout')
    expect(init.body).toBe(JSON.stringify({ refresh_token: 'r-at-send-time' }))
  })

  it('still signs out locally when the API is unreachable', async () => {
    setTokens({ access_token: 'a1', refresh_token: 'r1' })
    fetchMock.mockRejectedValueOnce(new Error('network down'))

    const confirmed = await signOut()

    expect(confirmed).toBe(false)
    // No throw, no refresh: an offline device can always end its session.
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
