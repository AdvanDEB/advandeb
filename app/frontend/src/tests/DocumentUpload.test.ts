import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'
import { useNotificationsStore } from '@/stores/notifications'

/**
 * Pins the upload path on the Corpus page.
 *
 * The regression: DocumentUpload POSTed to /api/documents/upload with a raw
 * XHR, then to /api/documents/{id}/embed with fetch — a route that never
 * existed — so every upload ended with "Upload succeeded but embedding trigger
 * failed", and an expired token was never refreshed. It must go through the
 * shared client to the KB ingestion endpoint, and nothing else.
 */

const uploadPdf = vi.fn()
vi.mock('@/utils/kbApi', () => ({ uploadPdf: (...args: unknown[]) => uploadPdf(...args) }))

// Imported after the mock is registered.
const { default: DocumentUpload } = await import('@/components/documents/DocumentUpload.vue')

function pdf(name = 'paper.pdf', size = 2048): File {
  return new File([new Uint8Array(size)], name, { type: 'application/pdf' })
}

async function choose(wrapper: ReturnType<typeof mount>, files: File[]) {
  const input = wrapper.find('[data-testid="file-input"]')
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  await input.trigger('change')
}

function mountUpload() {
  return mount(DocumentUpload, { global: { stubs: { RouterLink: RouterLinkStub } } })
}

const spyOnXhrOpen = () => vi.spyOn(XMLHttpRequest.prototype, 'open')

describe('DocumentUpload', () => {
  let fetchSpy: ReturnType<typeof vi.fn>
  let xhrOpen: ReturnType<typeof spyOnXhrOpen>

  beforeEach(() => {
    uploadPdf.mockReset()
    fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    xhrOpen = spyOnXhrOpen()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    xhrOpen.mockRestore()
  })

  it('sends a PDF through the shared client to KB ingestion and reports it queued', async () => {
    uploadPdf.mockImplementation(async (_file: File, _domain: unknown, opts: { onProgress?: (n: number) => void }) => {
      opts.onProgress?.(40)
      return { batch_id: 'b1', job_id: 'j1', filename: 'paper.pdf', status: 'processing' }
    })
    const wrapper = mountUpload()

    await choose(wrapper, [pdf()])
    await flushPromises()

    expect(uploadPdf).toHaveBeenCalledTimes(1)
    const [file, domain, opts] = uploadPdf.mock.calls[0]
    expect((file as File).name).toBe('paper.pdf')
    expect(domain).toBeUndefined()
    // The component reports failures itself; the global toast must not double it.
    expect(opts.skipErrorToast).toBe(true)

    expect(wrapper.find('.upload-item').classes()).toContain('queued')
    expect(wrapper.find('.upload-status-text').text()).toBe('Queued for ingestion')
    expect(wrapper.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('100')
    expect(wrapper.emitted('uploaded')?.[0]).toEqual([{ filename: 'paper.pdf', batchId: 'b1', jobId: 'j1' }])
  })

  it('never calls the nonexistent /embed route or bypasses the client', async () => {
    uploadPdf.mockResolvedValue({ batch_id: 'b', job_id: 'j', filename: 'a.pdf', status: 'processing' })
    const wrapper = mountUpload()

    await choose(wrapper, [pdf('a.pdf')])
    await flushPromises()

    expect(fetchSpy).not.toHaveBeenCalled()
    expect(xhrOpen).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('embedding trigger failed')
  })

  it('updates progress while the body is being sent', async () => {
    let report!: (n: number) => void
    let finish!: () => void
    uploadPdf.mockImplementation((_f: File, _d: unknown, opts: { onProgress: (n: number) => void }) => {
      report = opts.onProgress
      return new Promise(resolve => { finish = () => resolve({ batch_id: 'b', job_id: 'j', filename: 'x.pdf', status: 'processing' }) })
    })
    const wrapper = mountUpload()

    await choose(wrapper, [pdf('x.pdf')])
    report(55)
    await flushPromises()
    expect(wrapper.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('55')
    expect(wrapper.find('.upload-status-text').text()).toBe('55%')

    finish()
    await flushPromises()
    expect(wrapper.find('.upload-status-text').text()).toBe('Queued for ingestion')
  })

  it('refuses a non-PDF before sending anything', async () => {
    const wrapper = mountUpload()

    await choose(wrapper, [new File(['hello'], 'notes.txt', { type: 'text/plain' })])
    await flushPromises()

    expect(uploadPdf).not.toHaveBeenCalled()
    expect(wrapper.find('.upload-item').classes()).toContain('error')
    expect(wrapper.find('.upload-error').text()).toContain('Only PDF files')
  })

  it('shows the server reason inline and toasts exactly once on failure', async () => {
    uploadPdf.mockRejectedValue({ response: { status: 400, data: { detail: 'Only PDF files are supported' } } })
    const notifs = useNotificationsStore()
    const wrapper = mountUpload()

    await choose(wrapper, [pdf('bad.pdf')])
    await flushPromises()

    expect(wrapper.find('.upload-error').text()).toBe('Only PDF files are supported')
    const errors = notifs.toasts.filter(t => t.type === 'error')
    expect(errors).toHaveLength(1)
    expect(errors[0].message).toContain('bad.pdf')
    expect(wrapper.emitted('uploaded')).toBeUndefined()
  })

  it('uploads several files independently', async () => {
    uploadPdf
      .mockResolvedValueOnce({ batch_id: 'b1', job_id: 'j1', filename: 'one.pdf', status: 'processing' })
      .mockRejectedValueOnce(new Error('Network Error'))
    const wrapper = mountUpload()

    await choose(wrapper, [pdf('one.pdf'), pdf('two.pdf')])
    await flushPromises()

    const items = wrapper.findAll('.upload-item')
    expect(items).toHaveLength(2)
    expect(items[0].classes()).toContain('queued')
    expect(items[1].classes()).toContain('error')
  })
})
