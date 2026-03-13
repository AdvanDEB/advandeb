import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useNotificationsStore } from '@/stores/notifications'

describe('useNotificationsStore', () => {
  it('adds a toast', () => {
    const store = useNotificationsStore()
    store.add('Hello', 'info', 0)
    expect(store.toasts).toHaveLength(1)
    expect(store.toasts[0].message).toBe('Hello')
    expect(store.toasts[0].type).toBe('info')
  })

  it('removes a toast by id', () => {
    const store = useNotificationsStore()
    store.add('Test', 'success', 0)
    const id = store.toasts[0].id
    store.remove(id)
    expect(store.toasts).toHaveLength(0)
  })

  it('auto-removes toast after duration', async () => {
    vi.useFakeTimers()
    const store = useNotificationsStore()
    store.add('Temp', 'warning', 100)
    expect(store.toasts).toHaveLength(1)
    vi.advanceTimersByTime(150)
    expect(store.toasts).toHaveLength(0)
    vi.useRealTimers()
  })

  it('shorthand helpers set correct type', () => {
    const store = useNotificationsStore()
    store.success('ok')
    store.error('bad')
    expect(store.toasts[0].type).toBe('success')
    expect(store.toasts[1].type).toBe('error')
  })
})
