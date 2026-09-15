/**
 * The gig lifecycle, pushed instead of polled.
 *
 * Mobile cannot attach an `Authorization` header to a WebSocket handshake,
 * and putting the JWT in a query string leaks it into proxy logs and `Referer`
 * headers. So this exchanges the access token for a single-use, 30-second
 * ticket over ordinary authenticated HTTP, then spends that ticket on the
 * socket — the same contract the web and Flutter clients use.
 *
 * Everything here degrades quietly. If the socket cannot be established the
 * caller falls back to the data it already has: a live update is an
 * enhancement, never a dependency.
 */

import { post } from './client'
import { wsBase } from './config'

export type GigEvent = {
  type: string
  gig_id: number
  data: Record<string, unknown>
  at: string | null
}

type TicketResponse = { ticket: string; expires_in: number; ws_path: string }

/** How long to wait before a silent socket is assumed dead and reopened. */
const RECONNECT_DELAY_MS = 2000
/** Give up rather than retrying forever into a broken network. */
const MAX_RECONNECT_ATTEMPTS = 5

export type GigLinkState = 'connecting' | 'live' | 'closed'

export type GigSubscription = {
  close: () => void
}

/**
 * Subscribe to one gig. Returns a handle; call `close()` to stop.
 *
 * `onEvent` fires for every lifecycle push. `onSnapshot` fires once with the
 * current state, so a client that connects mid-gig is not left waiting for
 * the next transition.
 */
export function subscribeToGig(
  gigId: number,
  handlers: {
    onEvent?: (event: GigEvent) => void
    onSnapshot?: (event: GigEvent) => void
    onStateChange?: (state: GigLinkState) => void
  } = {},
): GigSubscription {
  let socket: WebSocket | null = null
  let closedByCaller = false
  let attempts = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  const open = async () => {
    if (closedByCaller) return
    handlers.onStateChange?.('connecting')

    let ticket: string
    try {
      // A fresh ticket each attempt: they are single-use and expire in 30
      // seconds, so a reconnect with the old one would always be refused.
      const issued = await post<TicketResponse>('/realtime/ticket')
      ticket = issued.ticket
    } catch {
      // No token, or the API is unreachable. There is nothing to subscribe with.
      handlers.onStateChange?.('closed')
      return
    }

    if (closedByCaller) return

    socket = new WebSocket(
      `${wsBase()}/api/v1/realtime/gigs/${gigId}?ticket=${encodeURIComponent(ticket)}`,
    )

    socket.onopen = () => {
      attempts = 0
      handlers.onStateChange?.('live')
    }

    socket.onmessage = (message) => {
      let event: GigEvent
      try {
        event = JSON.parse(String(message.data)) as GigEvent
      } catch {
        return // a malformed frame is not worth tearing the socket down over
      }
      if (event.type === 'gig.snapshot') handlers.onSnapshot?.(event)
      else if (event.type !== 'ping' && event.type !== 'pong') handlers.onEvent?.(event)
    }

    socket.onclose = (event) => {
      socket = null
      if (closedByCaller) return

      // 4401/4403 mean the ticket was rejected or the caller may not watch
      // this gig. Retrying cannot help, and hammering the endpoint would look
      // like an attack.
      const refused = event.code === 4401 || event.code === 4403 || event.code === 4429
      if (refused || attempts >= MAX_RECONNECT_ATTEMPTS) {
        handlers.onStateChange?.('closed')
        return
      }

      // Backoff, capped: a flapping network should not produce a burst.
      attempts += 1
      const delay = Math.min(RECONNECT_DELAY_MS * attempts, 15000)
      reconnectTimer = setTimeout(open, delay)
      // `connecting`, not `closed`: a retry is scheduled right here. `closed`
      // means what its label claims — we stopped trying.
      handlers.onStateChange?.('connecting')
    }

    socket.onerror = () => {
      // onclose always follows onerror, so reconnection is handled there.
      socket?.close()
    }
  }

  void open()

  return {
    close: () => {
      closedByCaller = true
      if (reconnectTimer !== null) clearTimeout(reconnectTimer)
      socket?.close()
      socket = null
      handlers.onStateChange?.('closed')
    },
  }
}
