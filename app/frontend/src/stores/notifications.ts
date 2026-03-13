import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: string
  type: ToastType
  message: string
  duration: number
}

export const useNotificationsStore = defineStore('notifications', () => {
  const toasts = ref<Toast[]>([])

  function add(message: string, type: ToastType = 'info', duration = 4000) {
    const id = crypto.randomUUID()
    toasts.value.push({ id, type, message, duration })
    if (duration > 0) {
      setTimeout(() => remove(id), duration)
    }
  }

  function remove(id: string) {
    const idx = toasts.value.findIndex((t) => t.id === id)
    if (idx !== -1) toasts.value.splice(idx, 1)
  }

  const success = (msg: string) => add(msg, 'success')
  const error = (msg: string) => add(msg, 'error', 6000)
  const warning = (msg: string) => add(msg, 'warning')
  const info = (msg: string) => add(msg, 'info')

  return { toasts, add, remove, success, error, warning, info }
})
