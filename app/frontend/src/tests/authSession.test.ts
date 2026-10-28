import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * The session plumbing around a working refresh endpoint.
 *
 * Refresh was refused server-side from 2026-05-21 until it was fixed, so none
 * of this had ever run: these pin what has to hold now that it does.
 */

const post = vi.fn()

vi.mock('axios', () => {
  const instance = {
    post,
    get: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  }
  return {
    default: {
      create: () => instance,
      isAxiosError: (e: unknown) => !!(e as { isAxiosError?: boolean })?.isAxiosError,
    },
  }
})

const replace = vi.fn()
const currentRoute = { value: {} as { name?: string; fullPath?: string; meta: Record<string, unknown> } }
vi.mock('@/router', () => ({ default: { replace, currentRoute } }))

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { isAxiosError: true, response: { status } })
}

async function load() {
  vi.resetModules()
  const refresh = await import('@/utils/authRefresh')
  const { useAuthStore } = await import('@/stores/auth')
  return { ...refresh, auth: useAuthStore() }
}

beforeEach(() => {
  post.mockReset()
  replace.mockClear()
  localStorage.clear()
  currentRoute.value = { name: 'home', meta: {} }
})

describe('refreshAccessToken', () => {
  it('updates the store as well as localStorage', async () => {
    localStorage.setItem('refresh_token', 'r-old')
    const { refreshAccessToken, auth } = await load()
    post.mockResolvedValueOnce({ data: { access_token: 'a-new', refresh_token: 'r-new' } })

    await expect(refreshAccessToken()).resolves.toBe('a-new')

    // The chat socket and isAuthenticated read the store; a ref left at the
    // old value is a token that expired an hour ago.
    expect(auth.accessToken).toBe('a-new')
    expect(auth.refreshToken).toBe('r-new')
    expect(localStorage.getItem('refresh_token')).toBe('r-new')
  })

  it('adopts the pair another tab stored instead of logging everyone out', async () => {
    localStorage.setItem('refresh_token', 'r-shared')
    localStorage.setItem('access_token', 'a-shared')
    const { refreshAccessToken, auth } = await load()
    post.mockImplementationOnce(async () => {
      // Another tab won the rotation while this request was in flight.
      localStorage.setItem('access_token', 'a-other-tab')
      localStorage.setItem('refresh_token', 'r-other-tab')
      throw httpError(401)
    })

    await expect(refreshAccessToken()).resolves.toBe('a-other-tab')
    expect(auth.accessToken).toBe('a-other-tab')
    expect(localStorage.getItem('refresh_token')).toBe('r-other-tab')
  })

  it('ends the session when the refresh is genuinely refused', async () => {
    localStorage.setItem('refresh_token', 'r-dead')
    localStorage.setItem('access_token', 'a-dead')
    const { refreshAccessToken, auth } = await load()
    post.mockRejectedValueOnce(httpError(401))

    await expect(refreshAccessToken()).rejects.toThrow()
    expect(auth.isAuthenticated).toBe(false)
    expect(localStorage.getItem('refresh_token')).toBeNull()
    // Already dead: nothing is sent to /auth/logout.
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('remembers the protected page, so signing in again returns to it', async () => {
    currentRoute.value = { name: 'kb', fullPath: '/kb?tab=graph', meta: { requiresAuth: true } }
    const { refreshAccessToken } = await load()

    await expect(refreshAccessToken()).rejects.toThrow()
    expect(replace).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/kb?tab=graph' } })
  })
})

describe('logout', () => {
  it('revokes the refresh token server-side and clears the session at once', async () => {
    localStorage.setItem('access_token', 'a')
    localStorage.setItem('refresh_token', 'r-to-revoke')
    const { auth } = await load()
    post.mockResolvedValueOnce({ data: { message: 'Logged out' } })

    const pending = auth.logout()
    // Cleared before the request settles: callers navigate without awaiting.
    expect(auth.isAuthenticated).toBe(false)
    expect(localStorage.getItem('refresh_token')).toBeNull()
    await pending

    expect(post).toHaveBeenCalledWith('/auth/logout', { refresh_token: 'r-to-revoke' })
  })

  it('a network failure does not keep anyone signed in', async () => {
    localStorage.setItem('access_token', 'a')
    localStorage.setItem('refresh_token', 'r')
    const { auth } = await load()
    post.mockRejectedValueOnce(new Error('offline'))

    await expect(auth.logout()).resolves.toBeUndefined()
    expect(auth.isAuthenticated).toBe(false)
  })
})

describe('fetchSocketTicket', () => {
  it('asks for a ticket with the access token in the header', async () => {
    localStorage.setItem('access_token', 'a-live')
    const { fetchSocketTicket } = await load()
    post.mockResolvedValueOnce({ data: { ticket: 't-1', expires_in: 30 } })

    await expect(fetchSocketTicket()).resolves.toBe('t-1')
    expect(post).toHaveBeenCalledWith('/auth/ws-ticket', null,
      { headers: { Authorization: 'Bearer a-live' } })
  })

  it('refreshes an expired access token once, then retries', async () => {
    localStorage.setItem('access_token', 'a-expired')
    localStorage.setItem('refresh_token', 'r')
    const { fetchSocketTicket } = await load()
    post
      .mockRejectedValueOnce(httpError(401)) // ticket: expired access token
      .mockResolvedValueOnce({ data: { access_token: 'a-fresh', refresh_token: 'r2' } }) // refresh
      .mockResolvedValueOnce({ data: { ticket: 't-2', expires_in: 30 } }) // ticket again

    await expect(fetchSocketTicket()).resolves.toBe('t-2')
    expect(post.mock.calls[2][2]).toEqual({ headers: { Authorization: 'Bearer a-fresh' } })
  })

  it('resolves null without a session, or for an account that may not open sockets', async () => {
    let { fetchSocketTicket } = await load()
    await expect(fetchSocketTicket()).resolves.toBeNull()
    expect(post).not.toHaveBeenCalled()

    localStorage.setItem('access_token', 'a')
    ;({ fetchSocketTicket } = await load())
    post.mockRejectedValueOnce(httpError(403))
    await expect(fetchSocketTicket()).resolves.toBeNull()
  })

  it('rejects on a transient failure so the socket retries', async () => {
    localStorage.setItem('access_token', 'a')
    const { fetchSocketTicket } = await load()
    post.mockRejectedValueOnce(httpError(502))
    await expect(fetchSocketTicket()).rejects.toThrow()
  })
})

describe('cross-tab', () => {
  it('a sign-out in another tab ends the session here too', async () => {
    localStorage.setItem('access_token', 'a')
    localStorage.setItem('refresh_token', 'r')
    const { auth } = await load()
    expect(auth.isAuthenticated).toBe(true)

    localStorage.clear()
    window.dispatchEvent(new StorageEvent('storage', { key: 'access_token' }))

    expect(auth.isAuthenticated).toBe(false)
  })

  it('a refresh in another tab is adopted here', async () => {
    localStorage.setItem('access_token', 'a')
    localStorage.setItem('refresh_token', 'r')
    const { auth } = await load()

    localStorage.setItem('access_token', 'a2')
    localStorage.setItem('refresh_token', 'r2')
    window.dispatchEvent(new StorageEvent('storage', { key: 'refresh_token' }))

    expect(auth.accessToken).toBe('a2')
    expect(auth.refreshToken).toBe('r2')
  })
})
