import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
  get,
  hasToken,
  post,
  restoreTokens,
  setAuthLossHandler,
  setTokens,
  signOut,
} from '../api/client'
import type { AuthResponse, User } from '../api/types'

/**
 * The session: one user, additive capabilities, and the two verbs —
 * `can_hire` and `can_work` — granted later, never chosen at the door.
 *
 * RN port of `frontend/src/store/auth.ts`: a token from a previous session is
 * restored from secure storage and validated by `/auth/me`; any 401 that
 * cannot be refreshed signs this device out in every component at once.
 */

export type RegisterPayload = {
  handle: string
  display_name: string
  email?: string
  phone?: string
  password: string
  city?: string
}

type AuthContextValue = {
  user: User | null
  ready: boolean
  login: (identifier: string, password: string) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
  grant: (capability: string) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      // A token from a previous session is restored, then validated by /me.
      const had = await restoreTokens()
      if (!had || !hasToken()) {
        if (!cancelled) setReady(true)
        return
      }
      try {
        const me = await get<User>('/auth/me')
        if (!cancelled) setUser(me)
      } catch {
        setTokens(null)
      } finally {
        if (!cancelled) setReady(true)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  // Any 401 that cannot be refreshed signs this device out, in every
  // component at once. Note the scope: this is local amnesia, not revocation
  // — the tokens on other devices are untouched.
  useEffect(() => {
    setAuthLossHandler(() => setUser(null))
    return () => setAuthLossHandler(null)
  }, [])

  const login = useCallback(async (identifier: string, password: string) => {
    const res = await post<AuthResponse>('/auth/login', { identifier, password })
    setTokens({ access_token: res.access_token, refresh_token: res.refresh_token })
    setUser(res.user)
  }, [])

  const register = useCallback(async (payload: RegisterPayload) => {
    const res = await post<AuthResponse>('/auth/register', payload)
    setTokens({ access_token: res.access_token, refresh_token: res.refresh_token })
    setUser(res.user)
  }, [])

  const logout = useCallback(async () => {
    // Clearing storage proves nothing to the server: the pair stays valid for
    // its own expiry. `signOut` hands the refresh token to /auth/logout —
    // without the transparent refresh that every other call gets, since
    // refreshing in order to sign out would mint the token the call exists to
    // revoke. Fire-and-forget on purpose: an offline phone still has to be
    // able to sign itself out.
    void signOut()
    setUser(null)
  }, [])

  const refreshUser = useCallback(async () => {
    setUser(await get<User>('/auth/me'))
  }, [])

  const grant = useCallback(async (capability: string) => {
    setUser(await post<User>(`/auth/capability/${capability}`))
  }, [])

  const value = useMemo(
    () => ({ user, ready, login, register, logout, refreshUser, grant }),
    [user, ready, login, register, logout, refreshUser, grant],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** Capability helpers: the product has no roles, only additive capabilities. */
export const can = (user: User | null, capability: string) =>
  !!user?.capabilities?.includes(capability)

export const canHire = (user: User | null) => can(user, 'can_hire')
export const canWork = (user: User | null) => can(user, 'can_work')
