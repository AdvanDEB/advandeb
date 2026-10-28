import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { useKnowledgeBuilderStore } from '@/stores/knowledgeBuilder'

/**
 * Document suggestions in the Knowledge Builder's Suggestions tab.
 *
 * The regression: Approve looked like it worked — the row disappeared — while
 * the backend queued an ingestion job for a file nobody had stored, and the job
 * died at once. The backend now refuses with 409 and a reason. The curator must
 * see that reason on the row, keep the row, and be able to reject it after.
 */

const approveDocument = vi.fn()
const patch = vi.fn()

vi.mock('@/utils/kbApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/kbApi')>()),
  fetchReviewQueues: vi.fn(async () => null),
  fetchDocumentSuggestions: vi.fn(async () => [
    { _id: 'sugg-1', title: 'Kooijman 2010', source_type: 'text', status: 'suggestion', created_at: '2026-10-01T00:00:00Z' },
  ]),
  approveDocument: (...args: unknown[]) => approveDocument(...args),
  fetchFactSuggestions: vi.fn(async () => []),
  reviewFact: vi.fn(),
  fetchStylizedFactSuggestions: vi.fn(async () => []),
  reviewStylizedFact: vi.fn(),
}))

// The real approveDocument, over a stubbed axios instance, for the request shape.
vi.mock('@/utils/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/api')>()),
  default: { patch: (...args: unknown[]) => patch(...args) },
}))

const { default: SuggestionsTab } = await import('@/components/kb/tabs/SuggestionsTab.vue')
const realKbApi = await vi.importActual<typeof import('@/utils/kbApi')>('@/utils/kbApi')

const REASON =
  'This suggestion has metadata only (title, DOI or URL), with no PDF to ingest. ' +
  'Upload the PDF under Knowledge Builder → Ingestion, then reject this suggestion.'

const httpError = (status: number, detail: string) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: { detail } },
  })

let wrapper: VueWrapper | null = null

async function mountTab() {
  useKnowledgeBuilderStore().activeTab = 'suggestions'   // the tab loads when shown
  wrapper = mount(SuggestionsTab, { attachTo: document.body })
  await flushPromises()
  return wrapper
}

const docRows = (w: VueWrapper) => w.findAll('tbody tr').filter(r => r.text().includes('Kooijman 2010'))
const button = (w: VueWrapper, label: string) => w.findAll('button').find(b => b.text() === label)!

beforeEach(() => { approveDocument.mockReset(); patch.mockReset() })
afterEach(() => { wrapper?.unmount(); wrapper = null })

describe('SuggestionsTab — document suggestions', () => {
  it('shows a refused approval on the row and keeps the row', async () => {
    approveDocument.mockRejectedValueOnce(httpError(409, REASON))
    const w = await mountTab()

    await button(w, 'Approve').trigger('click')
    await flushPromises()

    expect(approveDocument).toHaveBeenCalledWith('sugg-1', 'approve')
    expect(docRows(w)).toHaveLength(1)
    const alert = w.find('[role="alert"]')
    expect(alert.text()).toBe(REASON)
    // Shown on the row, not as the tab-wide error banner.
    expect(useKnowledgeBuilderStore().error).toBeFalsy()
  })

  it('offers the way forward, then lets the curator reject', async () => {
    approveDocument.mockRejectedValueOnce(httpError(409, REASON))
    approveDocument.mockResolvedValueOnce({ updated: true, status: 'rejected' })
    const w = await mountTab()
    const kb = useKnowledgeBuilderStore()

    await button(w, 'Approve').trigger('click')
    await flushPromises()
    await button(w, 'Open Ingestion').trigger('click')
    expect(kb.activeTab).toBe('ingestion')

    await button(w, 'Reject').trigger('click')
    await flushPromises()
    expect(approveDocument).toHaveBeenLastCalledWith('sugg-1', 'reject')
    expect(docRows(w)).toHaveLength(0)
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  it('reports any other failure through the tab error, not on the row', async () => {
    approveDocument.mockRejectedValueOnce(httpError(500, 'boom'))
    const w = await mountTab()

    await button(w, 'Approve').trigger('click')
    await flushPromises()

    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(useKnowledgeBuilderStore().error).toBeTruthy()
    expect(docRows(w)).toHaveLength(1)
  })
})

describe('approveDocument', () => {
  it('leaves the 409 to the caller instead of toasting it', async () => {
    patch.mockResolvedValueOnce({ data: { updated: true, status: 'rejected' } })
    await realKbApi.approveDocument('sugg-1', 'reject', 'dup')
    expect(patch).toHaveBeenCalledWith(
      '/documents/sugg-1/approve',
      { action: 'reject', comment: 'dup' },
      { skipErrorToast: [409] },
    )
  })
})
