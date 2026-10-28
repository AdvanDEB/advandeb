import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/utils/api'
import { revokeRefreshToken } from '@/utils/authRefresh'

export interface User {
  id: string
  email: string
  full_name?: string
  avatar_url?: string
  roles: string[]
  capabilities: string[]
  chat_history_visible_to_admin: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const accessToken = ref<string | null>(localStorage.getItem('access_token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const googleOAuthEnabled = ref<boolean>(false)

  const isAuthenticated = computed(() => !!accessToken.value)
  const hasRole = (role: string) => user.value?.roles.includes(role) || false
  const hasCapability = (capability: string) => user.value?.capabilities.includes(capability) || false

  /** Adopt a token pair: the refs and localStorage, kept in step. */
  function setTokens(access: string, refresh: string) {
    accessToken.value = access
    refreshToken.value = refresh
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
  }

  function _storeTokens(data: { access_token: string; refresh_token: string; user: User }) {
    setTokens(data.access_token, data.refresh_token)
    user.value = data.user
  }

  /** Google sign-in callback. `codeVerifier` is the PKCE secret for this flow. */
  async function login(code: string, redirectUri: string, codeVerifier?: string) {
    const response = await api.post('/auth/google', {
      code,
      redirect_uri: redirectUri,
      code_verifier: codeVerifier,
    })
    _storeTokens(response.data)
  }

  async function loginNative(email: string, password: string) {
    const response = await api.post('/auth/login', { email, password })
    _storeTokens(response.data)
  }

  async function fetchAuthConfig() {
    try {
      const response = await api.get('/auth/config')
      googleOAuthEnabled.value = response.data.google_oauth_enabled
    } catch {
      googleOAuthEnabled.value = false
    }
  }

  /** Forget the session locally. For a session that is already dead. */
  function clearSession() {
    user.value = null
    accessToken.value = null
    refreshToken.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  /**
   * Sign out: forget the session here and revoke its refresh token on the
   * server. Without the revocation the token stays valid for 30 days — a
   * copy taken from this browser would keep working after "sign out".
   *
   * The local state is cleared synchronously, before the request, so callers
   * that navigate right after (without awaiting) already see a signed-out app.
   */
  function logout(): Promise<void> {
    const token = refreshToken.value || localStorage.getItem('refresh_token')
    clearSession()
    return token ? revokeRefreshToken(token) : Promise.resolve()
  }

  async function fetchCurrentUser() {
    if (!accessToken.value) return

    try {
      const response = await api.get('/users/me')
      user.value = response.data
    } catch {
      clearSession()
    }
  }

  // Single in-flight hydration, shared by app startup and the router guard.
  // Role-gated routes (/kb, /admin/*) can only be decided once `user` is
  // populated; without something to await, a hard load or refresh resolves the
  // guard against a null user and bounces to home.
  let _hydration: Promise<void> | null = null

  function hydrate(): Promise<void> {
    if (!_hydration) {
      _hydration = fetchCurrentUser().finally(() => {
        // Clear on failure so a later navigation can retry rather than
        // replaying a rejected hydration forever.
        if (!user.value) _hydration = null
      })
    }
    return _hydration
  }

  // Tabs share localStorage but not this store. Follow the other tabs: a
  // refresh there rotates the pair (ours would be spent), a sign-out there
  // ends the session here too.
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (event: StorageEvent) => {
      if (event.key !== null && event.key !== 'access_token' && event.key !== 'refresh_token') return
      const access = localStorage.getItem('access_token')
      const refresh = localStorage.getItem('refresh_token')
      if (access && refresh) {
        accessToken.value = access
        refreshToken.value = refresh
      } else if (accessToken.value) {
        user.value = null
        accessToken.value = null
        refreshToken.value = null
      }
    })
  }

  return {
    user,
    accessToken,
    refreshToken,
    googleOAuthEnabled,
    isAuthenticated,
    hasRole,
    hasCapability,
    setTokens,
    login,
    loginNative,
    fetchAuthConfig,
    clearSession,
    logout,
    fetchCurrentUser,
    hydrate
  }
})
