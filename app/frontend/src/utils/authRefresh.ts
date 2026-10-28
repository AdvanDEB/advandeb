/**
 * Shared token-refresh logic.
 *
 * A single in-flight refresh promise is kept so that concurrent 401 responses
 * (e.g. two parallel API calls both expire at the same time) only trigger one
 * POST /api/auth/refresh, not N.
 */

import axios from 'axios'

// Raw axios instance pointing at /api — used only for the auth calls in this
// module (no auth interceptor attached, to avoid infinite loops, and no error
// toasts: a reconnecting socket must not spam the user every two seconds).
const _authClient = axios.create({ baseURL: '/api' })

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
      const res = await _authClient.post('/auth/refresh', { refresh_token: refreshToken })
      const { access_token, refresh_token: newRefresh } = res.data
      localStorage.setItem('access_token', access_token)
      localStorage.setItem('refresh_token', newRefresh)
      await _syncStore(access_token, newRefresh)
      return access_token as string
    } catch {
      // Refresh tokens are single-use, and every tab shares this storage. If
      // another tab rotated the token while this request was in flight, ours
      // was refused for being spent — the session itself is fine, so adopt
      // the pair that tab stored instead of logging every tab out.
      const current = localStorage.getItem('refresh_token')
      const access = localStorage.getItem('access_token')
      if (current && current !== refreshToken && access) {
        await _syncStore(access, current)
        return access
      }
      await _endSession()
      throw new Error('Token refresh failed — session ended')
    } finally {
      _refreshPromise = null
    }
  })()

  return _refreshPromise
}

/**
 * Revoke a refresh token server-side. Best effort: the endpoint answers 200
 * for anything, and a network failure must not keep anyone signed in locally.
 */
export async function revokeRefreshToken(refreshToken: string): Promise<void> {
  try {
    await _authClient.post('/auth/logout', { refresh_token: refreshToken })
  } catch {
    // Nothing to do: the local session is gone either way.
  }
}

/**
 * A one-time credential for a WebSocket URL, from POST /api/auth/ws-ticket.
 *
 * The browser WebSocket API cannot send an Authorization header, so whatever
 * authenticates a socket rides in its URL — and URLs are logged. A ticket is
 * good for one connection within 30 s, so the access token never goes there.
 *
 * Resolves null when there is no usable session (not signed in, refresh
 * failed, or an account that may not open sockets); rejects on transient
 * failures, which a caller may retry.
 */
export async function fetchSocketTicket(): Promise<string | null> {
  const request = (token: string) =>
    _authClient.post('/auth/ws-ticket', null, { headers: { Authorization: `Bearer ${token}` } })

  let token = localStorage.getItem('access_token')
  if (!token) return null
  try {
    return (await request(token)).data.ticket as string
  } catch (err) {
    const status = axios.isAxiosError(err) ? err.response?.status : undefined
    if (status === 403) return null
    if (status !== 401) throw err
  }

  // Expired access token: refresh once, then try again.
  try {
    token = await refreshAccessToken()
  } catch {
    return null
  }
  try {
    return (await request(token)).data.ticket as string
  } catch (err) {
    const status = axios.isAxiosError(err) ? err.response?.status : undefined
    if (status === 401 || status === 403) return null
    throw err
  }
}

/**
 * Mirror freshly stored tokens into the auth store. localStorage alone is not
 * enough: the chat socket and `isAuthenticated` read the store's refs, and a
 * stale ref there is a token that expired an hour ago.
 */
async function _syncStore(accessToken: string, refreshToken: string) {
  try {
    const { useAuthStore } = await import('@/stores/auth')
    useAuthStore().setTokens(accessToken, refreshToken)
  } catch {
    // Pinia not active yet (very early startup) — the store reads
    // localStorage when it is created.
  }
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
    // visitor. clearSession, not logout: the refresh token is already dead, so
    // there is nothing to revoke.
    useAuthStore().clearSession()
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
      // away the app we just booted only to boot it again. The page they were
      // on comes along, so signing in again returns them to it.
      router.replace(
        typeof current.fullPath === 'string'
          ? { name: 'login', query: { redirect: current.fullPath } }
          : { name: 'login' },
      )
    }
  } catch {
    // Router unavailable — leave the visitor where they are rather than
    // guessing. The session is cleared either way.
  }
}
