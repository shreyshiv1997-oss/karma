import { create } from 'zustand'
import {
  signOut,
  get,
  post,
  setTokens,
  setAuthLossHandler,
  restoreTokens,
  hasToken,
} from '../api/client'
import type { AuthResponse, User } from '../api/types'

type AuthState = {
  user: User | null
  ready: boolean
  load: () => Promise<void>
  login: (identifier: string, password: string) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
  grant: (capability: string) => Promise<void>
}

export type RegisterPayload = {
  handle: string
  display_name: string
  email?: string
  phone?: string
  password: string
  city?: string
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  ready: false,

  load: async () => {
    // A token from a previous session is restored, then validated by /me.
    if (!hasToken() && !restoreTokens()) {
      set({ ready: true, user: null })
      return
    }
    try {
      const user = await get<User>('/auth/me')
      set({ user, ready: true })
    } catch {
      setTokens(null)
      set({ user: null, ready: true })
    }
  },

  login: async (identifier, password) => {
    const res = await post<AuthResponse>('/auth/login', { identifier, password })
    setTokens({ access_token: res.access_token, refresh_token: res.refresh_token })
    set({ user: res.user })
  },

  register: async (payload) => {
    const res = await post<AuthResponse>('/auth/register', payload)
    setTokens({ access_token: res.access_token, refresh_token: res.refresh_token })
    set({ user: res.user })
  },

  logout: () => {
    // Clearing localStorage proves nothing to the server: the pair stays valid for its own expiry,
    // so a token copied before this click keeps working for another 14 days. `signOut` hands the
    // refresh token to /auth/logout -- without the transparent refresh that every other call gets,
    // since refreshing in order to sign out would mint the token the call exists to revoke -- and
    // then clears storage itself. Fire-and-forget on purpose: an offline tab still has to be able
    // to sign out, and a tab whose session was already dead is signed out by the time it hears.
    void signOut()
    set({ user: null })
  },

  refreshUser: async () => {
    const user = await get<User>('/auth/me')
    set({ user })
  },

  grant: async (capability) => {
    const user = await post<User>(`/auth/capability/${capability}`)
    set({ user })
  },
}))

// Any 401 that cannot be refreshed signs this tab out, in every component at once. Note the
// scope: this is local amnesia, not revocation -- the tokens on other devices are untouched,
// which is exactly what /auth/logout-all exists for.
// setState, not set: this runs outside the create() closure.
setAuthLossHandler(() => useAuth.setState({ user: null }))

/** Capability helpers: the product has no roles, only additive capabilities. */
export const can = (user: User | null, capability: string) =>
  !!user?.capabilities?.includes(capability)

export const canHire = (user: User | null) => can(user, 'can_hire')
export const canWork = (user: User | null) => can(user, 'can_work')

export const useCurrentUser = () => useAuth((s) => s.user)
