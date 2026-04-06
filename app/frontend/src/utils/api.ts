import axios from 'axios'
import { refreshAccessToken } from '@/utils/authRefresh'

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json'
  }
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // On 401: attempt silent token refresh + retry once
    if (error.response?.status === 401 && !originalRequest._retried) {
      originalRequest._retried = true
      try {
        const newToken = await refreshAccessToken()
        originalRequest.headers['Authorization'] = `Bearer ${newToken}`
        return api(originalRequest)
      } catch {
        // refreshAccessToken already redirects to /login
        return Promise.reject(error)
      }
    }

    // For non-401 errors, surface as toast (lazy-import to avoid circular dependency)
    if (error.response?.status !== 401) {
      try {
        const { useNotificationsStore } = await import('@/stores/notifications')
        const notifs = useNotificationsStore()
        const detail = error.response?.data?.detail || error.message || 'Request failed'
        notifs.error(String(detail))
      } catch {
        // pinia not ready yet (e.g. during app init) — silent
      }
    }

    return Promise.reject(error)
  }
)

export default api
