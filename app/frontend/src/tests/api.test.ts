import { describe, it, expect, vi, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios'
import { AxiosError } from 'axios'
import api, { apiErrorMessage, isToastSuppressed } from '@/utils/api'
import { useNotificationsStore } from '@/stores/notifications'

/**
 * The global error toast now has a per-request opt-out. Callers that report a
 * failure themselves (inline, or with a better-worded toast) pass
 * `skipErrorToast` so the user does not read the same failure twice.
 */

vi.mock('@/utils/authRefresh', () => ({ refreshAccessToken: vi.fn() }))

function failWith(status: number, detail: unknown): AxiosAdapter {
  return async (config: InternalAxiosRequestConfig) => {
    throw new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, null, {
      status, statusText: '', headers: {}, config, data: { detail },
    })
  }
}

const original = api.defaults.adapter
afterEach(() => { api.defaults.adapter = original })

async function errorToasts() {
  await flushPromises()
  return useNotificationsStore().toasts.filter(t => t.type === 'error').map(t => t.message)
}

describe('api error toast', () => {
  it('toasts a failure by default, with the server detail', async () => {
    api.defaults.adapter = failWith(500, 'Database unavailable')
    await api.get('/x').catch(() => {})
    expect(await errorToasts()).toEqual(['Database unavailable'])
  })

  it('stays silent when the request opts out', async () => {
    api.defaults.adapter = failWith(500, 'Database unavailable')
    await api.get('/x', { skipErrorToast: true }).catch(() => {})
    expect(await errorToasts()).toEqual([])
  })

  it('can opt out of specific statuses only', async () => {
    api.defaults.adapter = failWith(404, 'Not Found')
    await api.get('/lookup', { skipErrorToast: [404] }).catch(() => {})
    expect(await errorToasts()).toEqual([])

    api.defaults.adapter = failWith(500, 'Boom')
    await api.get('/lookup', { skipErrorToast: [404] }).catch(() => {})
    expect(await errorToasts()).toEqual(['Boom'])
  })

  it('still rejects, so the caller can handle the failure', async () => {
    api.defaults.adapter = failWith(409, 'Conflict')
    await expect(api.get('/x', { skipErrorToast: true })).rejects.toMatchObject({ response: { status: 409 } })
  })

  it('shows the first validation message rather than [object Object]', async () => {
    api.defaults.adapter = failWith(422, [{ loc: ['body', 'name'], msg: 'field required' }])
    await api.post('/x', {}).catch(() => {})
    expect(await errorToasts()).toEqual(['field required'])
  })
})

describe('isToastSuppressed / apiErrorMessage', () => {
  it('reads the request config', () => {
    expect(isToastSuppressed({ config: { skipErrorToast: true } as never, response: undefined })).toBe(true)
    expect(isToastSuppressed({ config: {} as never, response: undefined })).toBe(false)
    expect(isToastSuppressed({ config: { skipErrorToast: [403] } as never, response: { status: 403 } as never })).toBe(true)
  })

  it('falls back sensibly', () => {
    expect(apiErrorMessage({}, 'Fallback')).toBe('Fallback')
    expect(apiErrorMessage(new Error('Network Error'))).toBe('Network Error')
    expect(apiErrorMessage({ response: { data: { detail: 'Nope' } } })).toBe('Nope')
  })
})
