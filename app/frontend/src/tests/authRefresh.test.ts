import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/**
 * Pins the behaviour that an expired session must not evict a visitor from a
 * public page.
 *
 * The regression these guard against: app startup hydrates by calling
 * /users/me, a stale token 401s, the refresh fails, and the failure handler
 * redirected to /login unconditionally — so nobody who had ever signed in
 * could see the landing page at `/` again.
 */

const replace = vi.fn()
const currentRoute = { value: {} as { name?: string; meta: Record<string, unknown> } }

vi.mock('@/router', () => ({ default: { replace, currentRoute } }))

/**
 * jsdom swallows `window.location.href = ...` without navigating or throwing,
 * so asserting only on the router mock would let a hard redirect pass the
 * suite unnoticed — which is precisely the bug being guarded. Trap the
 * assignment explicitly.
 */
function trapHardNavigation() {
  const hits: string[] = []
  const loc = { pathname: '/', origin: 'https://advandeb.com' }
  Object.defineProperty(loc, 'href', {
    get: () => 'https://advandeb.com/',
    set: (v: string) => hits.push(v),
  })
  vi.stubGlobal('location', loc)
  return hits
}

// Imported dynamically per-test so the module-level in-flight refresh promise
// does not leak between cases.
async function loadRefresher() {
  vi.resetModules()
  return (await import('@/utils/authRefresh')).refreshAccessToken
}

describe('refreshAccessToken session teardown', () => {
  beforeEach(() => {
    replace.mockClear()
    localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('leaves the visitor on the public landing page when the session is dead', async () => {
    currentRoute.value = { name: 'home', meta: {} }
    const hardNavs = trapHardNavigation()
    const refreshAccessToken = await loadRefresher()

    await expect(refreshAccessToken()).rejects.toThrow()

    expect(replace).not.toHaveBeenCalled()
    expect(hardNavs).toEqual([])
  })

  it('redirects to login when the dead session is on a protected route', async () => {
    currentRoute.value = { name: 'knowledge-builder', meta: { requiresAuth: true } }
    const refreshAccessToken = await loadRefresher()

    await expect(refreshAccessToken()).rejects.toThrow()

    expect(replace).toHaveBeenCalledWith({ name: 'login' })
  })

  it('does not redirect to login when already on login', async () => {
    currentRoute.value = { name: 'login', meta: { requiresAuth: true } }
    const refreshAccessToken = await loadRefresher()

    await expect(refreshAccessToken()).rejects.toThrow()

    expect(replace).not.toHaveBeenCalled()
  })

  it('clears both tokens and the auth store so the page renders anonymously', async () => {
    currentRoute.value = { name: 'home', meta: {} }
    localStorage.setItem('access_token', 'stale')
    const { useAuthStore } = await import('@/stores/auth')
    const auth = useAuthStore()
    auth.accessToken = 'stale'
    auth.user = { id: '1', email: 'a@b.c', roles: [], capabilities: [], chat_history_visible_to_admin: false }

    const refreshAccessToken = await loadRefresher()
    await expect(refreshAccessToken()).rejects.toThrow()

    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
    // Clearing localStorage alone would leave isAuthenticated true against a
    // null user, and HomeView would show the signed-in dashboard to a
    // logged-out visitor.
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBeNull()
  })

  it('the teardown is complete once the promise settles, not still in flight', async () => {
    // main.ts mounts the app off hydrate() and the router guard reads
    // isAuthenticated immediately; an un-awaited teardown would let the guard
    // decide against a token that is already dead.
    currentRoute.value = { name: 'home', meta: {} }
    localStorage.setItem('access_token', 'stale')
    const refreshAccessToken = await loadRefresher()

    await refreshAccessToken().catch(() => {})

    expect(localStorage.getItem('access_token')).toBeNull()
  })
})
