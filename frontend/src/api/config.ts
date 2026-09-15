/**
 * Where the API lives.
 *
 * The web build talks to its own origin: `/api/v1` is proxied by Vite in dev and by nginx in
 * production. That is deliberate -- no CORS, no exposed API host, one reverse proxy.
 *
 * A Capacitor WebView breaks that assumption. The app is served from `capacitor://localhost`
 * (iOS) or `http://localhost` (Android), so a relative `/api/v1` resolves against the *app's*
 * own origin and finds nothing. The native build therefore needs an absolute origin, injected
 * at build time via `VITE_API_ORIGIN`.
 *
 * The rule is: if an origin was configured, use it; otherwise stay relative and let the
 * reverse proxy do its job. Nothing else in the codebase should need to know which case it is
 * in -- that is what this module is for.
 */

/** Absolute origin, no trailing slash. Empty string means "same origin". */
export const API_ORIGIN: string = (
  import.meta.env.VITE_API_ORIGIN ?? ''
).replace(/\/+$/, '')

/** The HTTP base every request is prefixed with. */
export const API_BASE = `${API_ORIGIN}/api/v1`

/**
 * True when running inside the Capacitor WebView, false in every browser tab.
 *
 * Read from the bridge the shell injects before the bundle runs, not from the origin: an
 * origin test would false-positive on a local dev server and, worse, would require importing
 * Capacitor core into the web bundle just to answer a yes/no question. The global costs
 * nothing.
 */
export const IS_NATIVE: boolean =
  typeof window !== 'undefined' &&
  // Duck-typed on purpose — pulling in @capacitor/core here would ship native code to the web.
  Boolean((window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor?.isNativePlatform?.())

/**
 * The WebSocket base, derived from the same origin decision.
 *
 * This cannot reuse `API_BASE` by string-swapping alone: `https` must become `wss` and `http`
 * must become `ws`, and in the same-origin case the scheme has to come from the live page so
 * the socket works behind TLS-terminating proxies without a rebuild.
 */
export function wsBase(): string {
  if (API_ORIGIN) {
    return `${API_ORIGIN.replace(/^http/, 'ws')}/api/v1`
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/v1`
}
