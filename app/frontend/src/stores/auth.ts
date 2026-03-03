import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/utils/api'

export interface User {
  id: string
  email: string
  full_name?: string
  avatar_url?: string
  roles: string[]
  capabilities: string[]
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const accessToken = ref<string | null>(localStorage.getItem('access_token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const googleOAuthEnabled = ref<boolean>(false)

  const isAuthenticated = computed(() => !!accessToken.value)
  const hasRole = (role: string) => user.value?.roles.includes(role) || false
  const hasCapability = (capability: string) => user.value?.capabilities.includes(capability) || false

  function _storeTokens(data: { access_token: string; refresh_token: string; user: User }) {
    accessToken.value = data.access_token
    refreshToken.value = data.refresh_token
    user.value = data.user
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
  }

  async function login(code: string, redirectUri: string) {
    const response = await api.post('/auth/google', { code, redirect_uri: redirectUri })
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

  function logout() {
    user.value = null
    accessToken.value = null
    refreshToken.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  async function fetchCurrentUser() {
    if (!accessToken.value) return

    try {
      const response = await api.get('/users/me')
      user.value = response.data
    } catch (error) {
      logout()
    }
  }

  return {
    user,
    accessToken,
    refreshToken,
    googleOAuthEnabled,
    isAuthenticated,
    hasRole,
    hasCapability,
    login,
    loginNative,
    fetchAuthConfig,
    logout,
    fetchCurrentUser
  }
})
