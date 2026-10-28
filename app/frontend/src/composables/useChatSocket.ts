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
 *
 * The credential is a one-time ticket (POST /api/auth/ws-ticket), fetched for
 * every (re)connect, so the access token never appears in a URL. Fetching it
 * is asynchronous, which opens a window in which close() or another connect()
 * can run before the socket exists; a generation counter makes the fetch that
 * lost that race give up instead of opening a socket nobody owns.
 *
 * Reconnects back off exponentially (2 s, 4 s, 8 s … capped at 30 s) with
 * jitter. A fixed 2 s retry meant that while the backend was restarting, every
 * open chat tab hit it every two seconds in lockstep — and kept doing so for
 * as long as it was down. The backoff only resets once a connection has
 * stayed up for a while; resetting on mere open would let a server that
 * accepts and immediately drops the socket drive the same 2 s loop. A failed
 * ticket fetch counts as a failure too.
 */

export interface ChatSocketOptions {
  /** Session id to connect to. Read fresh on every (re)connect. */
  sessionId: () => string
  /**
   * Credential for the `?ticket=` param, fetched fresh on every (re)connect —
   * a ticket is good for one connection. May be async. Resolving null means
   * there is no session to connect with (reported via onAuthFailure);
   * rejecting is treated as a transient failure and retried like a drop.
   */
  ticket: () => string | null | Promise<string | null>
  /** Called with each parsed server event from the current socket. */
  onEvent: (data: Record<string, unknown>) => void
  /** Called when the server closes with 4401 (invalid/expired credential), or no
   *  ticket can be had. No reconnect follows. */
  onAuthFailure: () => void
  /** Delay before the first reconnect; doubles with each consecutive failure. */
  reconnectDelayMs?: number
  /** Ceiling for the backoff. */
  maxReconnectDelayMs?: number
  /** A connection open at least this long counts as healthy and resets the backoff. */
  stableAfterMs?: number
  /** Randomness for jitter, in [0, 1). Tests pin it. */
  random?: () => number
}

export interface ChatSocket {
  connect: () => void
  close: () => void
  /** Send a payload, queueing it if the socket is still connecting. */
  send: (payload: unknown) => void
  /** Test/debug seam: the current socket, or null. */
  current: () => WebSocket | null
  /** Test/debug seam: consecutive failed connections since the last healthy one. */
  failures: () => number
}

export function useChatSocket(opts: ChatSocketOptions): ChatSocket {
  const reconnectDelayMs = opts.reconnectDelayMs ?? 2000
  const maxReconnectDelayMs = opts.maxReconnectDelayMs ?? 30_000
  const stableAfterMs = opts.stableAfterMs ?? 5000
  const random = opts.random ?? Math.random

  let socket: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  /** Payload captured while CONNECTING, flushed on open. */
  let outbox: string | null = null
  /** Bumped by every connect() and close(); a ticket fetch from an older
   *  generation has been superseded and must not open a socket. */
  let generation = 0
  /** A connect() is waiting for its ticket (no socket exists yet). */
  let fetchingTicket = false
  /** Consecutive failures (drops, failed ticket fetches) without a healthy connection between. */
  let failures = 0
  /** When the current socket opened, or null while it has not. */
  let openedAt: number | null = null

  function cancelReconnect() {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  function buildUrl(ticket: string): string {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/ws/chat/${opts.sessionId()}?ticket=${encodeURIComponent(ticket)}`
  }

  /**
   * "Equal jitter": half the exponential delay is fixed, half random, so tabs
   * that lost the server together do not all come back on the same tick.
   */
  function nextDelay(): number {
    const exp = Math.min(maxReconnectDelayMs, reconnectDelayMs * 2 ** failures)
    return Math.round(exp / 2 + (exp / 2) * random())
  }

  function scheduleReconnect() {
    const delay = nextDelay()
    failures += 1
    cancelReconnect()
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      // Don't reconnect if the view has since torn down or has no session.
      if (opts.sessionId()) connect()
    }, delay)
  }

  /**
   * Tear down deliberately. Detaching the handlers *before* close() is the
   * whole point: otherwise the outgoing socket's onclose schedules a reconnect
   * for a session we are navigating away from.
   */
  function detach() {
    cancelReconnect()
    generation += 1
    fetchingTicket = false
    outbox = null
    openedAt = null
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

  /** Deliberate teardown; the next connect() starts with a fresh backoff. */
  function close() {
    detach()
    failures = 0
  }

  function connect() {
    // Guarantees the single-socket invariant even if a caller forgets to close.
    // detach(), not close(): a reconnect is the same outage continuing, so the
    // failure count must survive it.
    detach()
    const mine = generation

    const credential = opts.ticket()
    if (credential === null || typeof credential === 'string') {
      openWith(credential)
      return
    }
    fetchingTicket = true
    credential.then(
      (ticket) => {
        if (mine !== generation) return // closed or superseded meanwhile
        fetchingTicket = false
        openWith(ticket)
      },
      () => {
        if (mine !== generation) return
        fetchingTicket = false
        scheduleReconnect()
      },
    )
  }

  function openWith(ticket: string | null) {
    if (ticket === null) {
      outbox = null
      opts.onAuthFailure()
      return
    }

    const s = new WebSocket(buildUrl(ticket))
    socket = s

    s.onopen = () => {
      if (s !== socket) return
      openedAt = Date.now()
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

      const wasHealthy = openedAt !== null && Date.now() - openedAt >= stableAfterMs
      openedAt = null
      if (wasHealthy) failures = 0
      scheduleReconnect()
    }
  }

  function send(payload: unknown) {
    const text = JSON.stringify(payload)
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(text)
      return
    }
    // Still CONNECTING, still fetching a ticket, or gone: hold it rather than
    // dropping it on the floor. Order matters — connect() clears the outbox,
    // so open the socket first and queue afterwards, or the payload we are
    // about to hold is wiped.
    if (!socket && !fetchingTicket) connect()
    outbox = text
  }

  return { connect, close, send, current: () => socket, failures: () => failures }
}
