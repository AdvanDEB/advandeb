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

  const isAuthenticated = computed(() => !!accessToken.value)
  const hasRole = (role: string) => user.value?.roles.includes(role) || false
  const hasCapability = (capability: string) => user.value?.capabilities.includes(capability) || false

  async function login(code: string, redirectUri: string) {
    const response = await api.post('/auth/google', { code, redirect_uri: redirectUri })
    accessToken.value = response.data.access_token
    refreshToken.value = response.data.refresh_token
    user.value = response.data.user
    
    localStorage.setItem('access_token', accessToken.value)
    localStorage.setItem('refresh_token', refreshToken.value)
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
    isAuthenticated,
    hasRole,
    hasCapability,
    login,
    logout,
    fetchCurrentUser
  }
})
