/**
 * Shared token-refresh logic.
 *
 * A single in-flight refresh promise is kept so that concurrent 401 responses
 * (e.g. two parallel API calls both expire at the same time) only trigger one
 * POST /api/auth/refresh, not N.
 */

import axios from 'axios'

// Raw axios instance pointing at /api — used only for the refresh call itself
// (no auth interceptor attached, to avoid infinite loops).
const _refreshClient = axios.create({ baseURL: '/api' })

let _refreshPromise: Promise<string> | null = null

/**
 * Attempt a token refresh.  Returns the new access token on success.
 * Ends the session if the refresh token is missing or the refresh request
 * fails — see `_endSession` for what "ends" means per route.
 */
export async function refreshAccessToken(): Promise<string> {
  // Coalesce concurrent callers into a single in-flight request
  if (_refreshPromise) return _refreshPromise

  _refreshPromise = (async () => {
    const refreshToken = localStorage.getItem('refresh_token')
    if (!refreshToken) {
      // Awaited so the session is fully torn down before this promise settles.
      // main.ts mounts the app off the back of hydrate(), and the router guard
      // reads `isAuthenticated` immediately — leaving the teardown in flight
      // would let the guard decide against a token that is already dead.
      await _endSession()
      throw new Error('No refresh token available')
    }

    try {
      const res = await _refreshClient.post('/auth/refresh', { refresh_token: refreshToken })
      const { access_token, refresh_token: newRefresh } = res.data
      localStorage.setItem('access_token', access_token)
      localStorage.setItem('refresh_token', newRefresh)
      return access_token as string
    } catch {
      await _endSession()
      throw new Error('Token refresh failed — session ended')
    } finally {
      _refreshPromise = null
    }
  })()

  return _refreshPromise
}

/**
 * Drop the dead session, and send the visitor to /login *only* if the page
 * they are on actually requires auth.
 *
 * This used to redirect unconditionally, which meant a returning visitor with
 * an expired token never saw the public landing page: app startup hydrates by
 * calling /users/me, the stale token 401s, the refresh fails, and the hard
 * `window.location` assignment bounced `/` straight to `/login`. An expired
 * session is not a reason to hide public pages — it just means the visitor is
 * anonymous, which is exactly what those pages are built to render.
 *
 * `requiresAuth` is read off the matched route rather than a path list here, so
 * this stays correct as routes are added — the router remains the single source
 * of truth for what is protected.
 */
async function _endSession() {
  // Lazy imports: this module sits inside the router's import cycle
  // (router → stores/auth → utils/api → this), so pulling either in at module
  // scope would be a load-order hazard. api.ts uses the same trick for stores.
  try {
    const { useAuthStore } = await import('@/stores/auth')
    // Clears the store refs as well as localStorage — dropping only the
    // localStorage keys would leave `isAuthenticated` true against a null user,
    // so the landing page would render the signed-in dashboard to a logged-out
    // visitor.
    useAuthStore().logout()
  } catch {
    // Pinia not active yet (very early startup) — fall back to the raw keys.
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  try {
    const { default: router } = await import('@/router')
    const current = router.currentRoute.value
    if (current.meta.requiresAuth && current.name !== 'login') {
      // replace(), not window.location: a full page reload here would throw
      // away the app we just booted only to boot it again.
      router.replace({ name: 'login' })
    }
  } catch {
    // Router unavailable — leave the visitor where they are rather than
    // guessing. The session is cleared either way.
  }
}

