import axios from 'axios'

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
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      window.location.href = '/login'
      return Promise.reject(error)
    }

    // Surface API errors as toasts (lazy-import to avoid circular dependency)
    try {
      const { useNotificationsStore } = await import('@/stores/notifications')
      const notifs = useNotificationsStore()
      const detail = error.response?.data?.detail || error.message || 'Request failed'
      notifs.error(String(detail))
    } catch {
      // pinia not ready yet (e.g. during app init) — silent
    }

    return Promise.reject(error)
  }
)

export default api
