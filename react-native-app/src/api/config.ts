import Constants from 'expo-constants'
import { Platform } from 'react-native'

/**
 * Where the API lives, decided in exactly one place.
 *
 * On a phone there is no reverse proxy, so the base is always an absolute
 * origin. Precedence:
 *
 *   1. `extra.apiOrigin` in app.json (baked into the bundle at build time —
 *      the production answer: `EXPO_PUBLIC_API_ORIGIN=https://api… npx expo export`)
 *   2. `EXPO_PUBLIC_API_ORIGIN` environment variable (Expo inlines it)
 *   3. the platform default, which reaches a backend running on the
 *      developer's machine: `10.0.2.2` aliases the host on the Android
 *      emulator; `127.0.0.1` is the host on the iOS simulator. A physical
 *      device needs the backend's LAN or deployed origin — set (1).
 */

const configured =
  (Constants.expoConfig?.extra as { apiOrigin?: string } | undefined)?.apiOrigin?.trim() ??
  process.env.EXPO_PUBLIC_API_ORIGIN?.trim() ??
  ''

const DEFAULT_ORIGIN =
  Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://127.0.0.1:8000'

export const API_ORIGIN = (configured || DEFAULT_ORIGIN).replace(/\/+$/, '')
export const API_BASE = `${API_ORIGIN}/api/v1`

/**
 * The WebSocket endpoint, derived from the same decision. A `https` origin
 * becomes `wss`, so a socket behind a TLS-terminating proxy works without a
 * second configuration value.
 */
export function wsBase(): string {
  if (API_ORIGIN.startsWith('https://')) return `wss://${API_ORIGIN.slice('https://'.length)}`
  if (API_ORIGIN.startsWith('http://')) return `ws://${API_ORIGIN.slice('http://'.length)}`
  return API_ORIGIN
}

export const isAndroid = Platform.OS === 'android'
