/**
 * Chat WebSocket lifecycle: one live socket, auto-reconnect, no lost sends.
 *
 * Extracted from ChatInterface.vue, where three defects were live:
 *
 *  1. **Orphaned sockets.** Switching or starting a session did
 *     `ws.close(); connectWebSocket()`. The closing socket's `onclose` still
 *     fired its 2 s reconnect afterwards, which reassigned `ws` to a *third*
 *     socket and orphaned the one just created. Server logs showed four opens
 *     in five seconds for a single session, with opens far outnumbering closes.
 *
 *  2. **Silently dropped sends.** `sendOverWs` was a no-op unless the socket
 *     was already OPEN. Pressing send during the CONNECTING window (right
 *     after mount, or just after switching sessions) threw the message away.
 *     The UI had already flipped `responding = true`, so the composer stayed
 *     locked and the chat looked dead until a page reload.
 *
 *  3. **Reconnect storms.** Nothing cancelled a pending reconnect timer, so
 *     deliberate teardowns still queued a reconnect to a session the user had
 *     already navigated away from.
 *
 * The invariant this module enforces: **at most one socket is current at any
 * time**, and only the current socket's handlers may act. Superseded sockets
 * are detached before close, and every handler re-checks identity before
 * touching shared state.
 */

export interface ChatSocketOptions {
  /** Session id to connect to. Read fresh on every (re)connect. */
  sessionId: () => string
  /** Access token for the `?token=` param. Read fresh so reconnects use the current one. */
  token: () => string | null
  /** Called with each parsed server event from the current socket. */
  onEvent: (data: Record<string, unknown>) => void
  /** Called when the server closes with 4401 (invalid/expired token). No reconnect follows. */
  onAuthFailure: () => void
  /** Delay before an unintentional-close reconnect. */
  reconnectDelayMs?: number
}

export interface ChatSocket {
  connect: () => void
  close: () => void
  /** Send a payload, queueing it if the socket is still connecting. */
  send: (payload: unknown) => void
  /** Test/debug seam: the current socket, or null. */
  current: () => WebSocket | null
}

export function useChatSocket(opts: ChatSocketOptions): ChatSocket {
  const reconnectDelayMs = opts.reconnectDelayMs ?? 2000

  let socket: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  /** Payload captured while CONNECTING, flushed on open. */
  let outbox: string | null = null

  function cancelReconnect() {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  function buildUrl(): string {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const token = opts.token()
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : ''
    return `${proto}//${window.location.host}/ws/chat/${opts.sessionId()}${tokenParam}`
  }

  /**
   * Tear down deliberately. Detaching the handlers *before* close() is the
   * whole point: otherwise the outgoing socket's onclose schedules a reconnect
   * for a session we are navigating away from.
   */
  function close() {
    cancelReconnect()
    outbox = null
    if (!socket) return
    socket.onopen = null
    socket.onmessage = null
    socket.onclose = null
    socket.onerror = null
    try {
      socket.close()
    } catch {
      // Already closing/closed — nothing to do.
    }
    socket = null
  }

  function connect() {
    // Guarantees the single-socket invariant even if a caller forgets to close.
    close()

    const s = new WebSocket(buildUrl())
    socket = s

    s.onopen = () => {
      if (s !== socket) return
      if (outbox !== null) {
        const payload = outbox
        outbox = null
        s.send(payload)
      }
    }

    s.onmessage = (event: MessageEvent) => {
      if (s !== socket) return
      let data: Record<string, unknown>
      try {
        data = JSON.parse(event.data as string)
      } catch {
        return // Ignore malformed frames rather than killing the handler.
      }
      opts.onEvent(data)
    }

    s.onclose = (event: CloseEvent) => {
      // A superseded socket closing must not touch shared state or reconnect.
      if (s !== socket) return
      socket = null

      if (event.code === 4401) {
        opts.onAuthFailure()
        return
      }

      cancelReconnect()
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        // Don't reconnect if the view has since torn down or has no session.
        if (opts.sessionId()) connect()
      }, reconnectDelayMs)
    }
  }

  function send(payload: unknown) {
    const text = JSON.stringify(payload)
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(text)
      return
    }
    // Still CONNECTING (or gone): hold it rather than dropping it on the floor.
    // Order matters — connect() clears the outbox, so open the socket first and
    // queue afterwards, or the payload we are about to hold is wiped.
    if (!socket) connect()
    outbox = text
  }

  return { connect, close, send, current: () => socket }
}
