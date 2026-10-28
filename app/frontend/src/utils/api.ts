import axios, { type AxiosError } from 'axios'
import { refreshAccessToken } from '@/utils/authRefresh'

declare module 'axios' {
  interface AxiosRequestConfig {
    /**
     * Opt out of the global error toast for this request.
     *
     * `true` silences every failure; an array silences only those HTTP
     * statuses (e.g. `[404]` for a lookup where "not found" is an answer, not
     * an error). Use it when the caller shows the failure itself — inline, or
     * with its own, better-worded toast — otherwise the user sees it twice.
     */
    skipErrorToast?: boolean | number[]
  }
}

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

/** True when the request asked not to toast this particular failure. */
export function isToastSuppressed(error: Pick<AxiosError, 'config' | 'response'>): boolean {
  const opt = error.config?.skipErrorToast
  if (opt === true) return true
  if (Array.isArray(opt)) {
    const status = error.response?.status
    return status !== undefined && opt.includes(status)
  }
  return false
}

/**
 * The message worth showing a person for a failed request: the server's
 * `detail` when it is a sentence, else `fallback`. FastAPI validation errors
 * arrive as an array of `{ msg }`; the first one is used.
 */
export function apiErrorMessage(err: unknown, fallback = 'Request failed'): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') return detail[0].msg
  if (err instanceof Error && err.message) return err.message
  return fallback
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // On 401: attempt silent token refresh + retry once
    if (error.response?.status === 401 && originalRequest && !originalRequest._retried) {
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

    // A cancelled request is the caller's own doing, never news to the user.
    if (axios.isCancel(error)) return Promise.reject(error)

    // For non-401 errors, surface as toast (lazy-import to avoid circular dependency)
    if (error.response?.status !== 401 && !isToastSuppressed(error)) {
      try {
        const { useNotificationsStore } = await import('@/stores/notifications')
        const notifs = useNotificationsStore()
        notifs.error(apiErrorMessage(error))
      } catch {
        // pinia not ready yet (e.g. during app init) — silent
      }
    }

    return Promise.reject(error)
  }
)

export default api
