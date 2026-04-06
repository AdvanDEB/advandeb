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
 * Clears localStorage and redirects to /login if the refresh token is
 * missing or the refresh request fails.
 */
export async function refreshAccessToken(): Promise<string> {
  // Coalesce concurrent callers into a single in-flight request
  if (_refreshPromise) return _refreshPromise

  _refreshPromise = (async () => {
    const refreshToken = localStorage.getItem('refresh_token')
    if (!refreshToken) {
      _redirectToLogin()
      throw new Error('No refresh token available')
    }

    try {
      const res = await _refreshClient.post('/auth/refresh', { refresh_token: refreshToken })
      const { access_token, refresh_token: newRefresh } = res.data
      localStorage.setItem('access_token', access_token)
      localStorage.setItem('refresh_token', newRefresh)
      return access_token as string
    } catch {
      _redirectToLogin()
      throw new Error('Token refresh failed — redirecting to login')
    } finally {
      _refreshPromise = null
    }
  })()

  return _refreshPromise
}

function _redirectToLogin() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = '/login'
  }
}

