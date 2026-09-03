import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useChatSocket } from '@/composables/useChatSocket'

/**
 * Pins the socket lifecycle that made chat look dead for users.
 *
 * Three regressions are guarded here, all previously live in
 * ChatInterface.vue:
 *
 *   1. Switching sessions did `ws.close(); connectWebSocket()`, but the
 *      closing socket's onclose still ran its 2 s reconnect afterwards and
 *      reassigned `ws` to a third socket — orphaning the fresh one. Server
 *      logs showed four opens in five seconds for a single session.
 *   2. Sending during the CONNECTING window silently dropped the message,
 *      leaving the composer locked on `responding = true` with no reply.
 *   3. Deliberate teardown never cancelled a pending reconnect timer.
 */

class MockWebSocket {
  static instances: MockWebSocket[] = []
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3

  readyState = MockWebSocket.CONNECTING
  sent: string[] = []
  closeCalls = 0

  onopen: ((e: unknown) => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  onerror: ((e: unknown) => void) | null = null

  constructor(public url: string) {
    MockWebSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.closeCalls += 1
    this.readyState = MockWebSocket.CLOSED
  }

  // --- test drivers -------------------------------------------------------
  /** Simulate the handshake completing. */
  serverOpen() {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.({})
  }

  /** Simulate the server closing the connection. */
  serverClose(code = 1006) {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.({ code })
  }

  serverSend(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
}

const originalWebSocket = globalThis.WebSocket

function makeSocket(overrides: Record<string, unknown> = {}) {
  const events: Record<string, unknown>[] = []
  const authFailures: number[] = []
  const sock = useChatSocket({
    sessionId: () => 'sess-1',
    token: () => 'tok-abc',
    onEvent: (d) => events.push(d),
    onAuthFailure: () => authFailures.push(1),
    ...overrides,
  })
  return { sock, events, authFailures }
}

const live = () => MockWebSocket.instances

beforeEach(() => {
  MockWebSocket.instances = []
  // @ts-expect-error — swapping in the test double
  globalThis.WebSocket = MockWebSocket
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  globalThis.WebSocket = originalWebSocket
})

describe('useChatSocket — single-socket invariant', () => {
  it('does not orphan a socket when a session switch closes then reconnects', () => {
    const { sock } = makeSocket()
    sock.connect()
    const first = live()[0]
    first.serverOpen()

    // The exact sequence startNewSession()/handleLoadSession() perform.
    sock.close()
    sock.connect()
    expect(live()).toHaveLength(2)

    // The real close frame for the *first* socket arrives late. Under the old
    // code this scheduled a reconnect that replaced the socket just created.
    first.serverClose(1006)
    vi.advanceTimersByTime(10_000)

    expect(live()).toHaveLength(2)
    expect(sock.current()).toBe(live()[1])
  })

  it('closing cancels a reconnect already scheduled by an unintentional close', () => {
    const { sock } = makeSocket()
    sock.connect()
    live()[0].serverClose(1006) // schedules a reconnect

    sock.close() // user navigated away before the timer fired
    vi.advanceTimersByTime(10_000)

    expect(live()).toHaveLength(1)
    expect(sock.current()).toBeNull()
  })

  it('connect() closes any existing socket rather than leaking it', () => {
    const { sock } = makeSocket()
    sock.connect()
    const first = live()[0]
    sock.connect()

    expect(first.closeCalls).toBe(1)
    expect(live()).toHaveLength(2)
  })

  it('ignores events from a superseded socket', () => {
    const { sock, events } = makeSocket()
    sock.connect()
    const first = live()[0]
    sock.connect() // supersede

    first.serverSend({ type: 'message', content: 'from the stale socket' })
    expect(events).toHaveLength(0)

    live()[1].serverSend({ type: 'message', content: 'current' })
    expect(events).toHaveLength(1)
  })
})

describe('useChatSocket — reconnect policy', () => {
  it('reconnects after an unintentional close', () => {
    const { sock } = makeSocket()
    sock.connect()
    live()[0].serverClose(1006)

    vi.advanceTimersByTime(1999)
    expect(live()).toHaveLength(1)

    vi.advanceTimersByTime(1)
    expect(live()).toHaveLength(2)
  })

  it('does NOT reconnect after a 4401 auth close, and reports it', () => {
    const { sock, authFailures } = makeSocket()
    sock.connect()
    live()[0].serverClose(4401)

    vi.advanceTimersByTime(10_000)
    expect(live()).toHaveLength(1)
    expect(authFailures).toHaveLength(1)
  })

  it('does not reconnect when there is no session to reconnect to', () => {
    const { sock } = makeSocket({ sessionId: () => '' })
    sock.connect()
    live()[0].serverClose(1006)

    vi.advanceTimersByTime(10_000)
    expect(live()).toHaveLength(1)
  })

  it('reads the token fresh on reconnect so a refreshed token is used', () => {
    let token = 'old-token'
    const { sock } = makeSocket({ token: () => token })
    sock.connect()
    expect(live()[0].url).toContain('old-token')

    token = 'new-token'
    live()[0].serverClose(1006)
    vi.advanceTimersByTime(2000)

    expect(live()[1].url).toContain('new-token')
  })
})

describe('useChatSocket — sends are never dropped', () => {
  it('queues a send issued while CONNECTING and flushes it on open', () => {
    const { sock } = makeSocket()
    sock.connect()
    const s = live()[0]
    expect(s.readyState).toBe(MockWebSocket.CONNECTING)

    sock.send({ type: 'user_message', text: 'hello' })
    expect(s.sent).toHaveLength(0) // still connecting

    s.serverOpen()
    expect(s.sent).toHaveLength(1)
    expect(JSON.parse(s.sent[0])).toMatchObject({ type: 'user_message', text: 'hello' })
  })

  it('sends immediately when the socket is already open', () => {
    const { sock } = makeSocket()
    sock.connect()
    const s = live()[0]
    s.serverOpen()

    sock.send({ type: 'user_message', text: 'hi' })
    expect(JSON.parse(s.sent[0])).toMatchObject({ text: 'hi' })
  })

  it('opens a connection if send() is called with no socket at all', () => {
    const { sock } = makeSocket()
    sock.send({ type: 'user_message', text: 'cold start' })

    expect(live()).toHaveLength(1)
    live()[0].serverOpen()
    expect(JSON.parse(live()[0].sent[0])).toMatchObject({ text: 'cold start' })
  })

  it('drops the queued payload on a deliberate close rather than resending later', () => {
    const { sock } = makeSocket()
    sock.connect()
    sock.send({ type: 'user_message', text: 'abandoned' })

    sock.close()
    sock.connect()
    live()[1].serverOpen()

    expect(live()[1].sent).toHaveLength(0)
  })
})

describe('useChatSocket — robustness', () => {
  it('ignores malformed frames without tearing down the handler', () => {
    const { sock, events } = makeSocket()
    sock.connect()
    const s = live()[0]

    s.onmessage?.({ data: 'not json{' })
    expect(events).toHaveLength(0)

    s.serverSend({ type: 'message', content: 'still working' })
    expect(events).toHaveLength(1)
  })
})
