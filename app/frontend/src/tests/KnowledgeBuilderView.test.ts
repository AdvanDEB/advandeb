import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import KnowledgeBuilderView from '@/views/KnowledgeBuilderView.vue'
import { useKnowledgeBuilderStore } from '@/stores/knowledgeBuilder'
import { useDialogStore } from '@/stores/dialog'
import * as kbApi from '@/utils/kbApi'

/**
 * The /kb shell after the split into per-tab components: tabs switch and load
 * lazily as before, cross-tab links go through the store, and leaving the view
 * resets it. No backend: every kbApi call is a mock.
 */

vi.mock('@/utils/kbApi', () => ({
  fetchSchemas: vi.fn(async () => []),
  fetchArtifactStatus: vi.fn(),
  fetchGraphArtifact: vi.fn(),
  resetKnowledgeBase: vi.fn(),
  fetchResetPreview: vi.fn(),
  fetchBatches: vi.fn(async () => [
    { _id: 'batch-0000000001', status: 'completed', created_at: '2026-10-01T00:00:00Z', num_files: 2 },
  ]),
  fetchJobs: vi.fn(async () => []),
  runBatch: vi.fn(),
  deleteBatch: vi.fn(async () => ({})),
  stopBatch: vi.fn(),
  fetchSources: vi.fn(async () => ({ entries: [] })),
  scanFolders: vi.fn(),
  fetchFolderFiles: vi.fn(),
  uploadPdf: vi.fn(),
  fetchCollections: vi.fn(async () => [{ name: 'documents', count: 1200 }]),
  fetchCollectionDocs: vi.fn(async () => []),
  fetchKgStats: vi.fn(async () => ({ total_relations: 10, suggested_relations: 6, confirmed_relations: 4 })),
  linkDocuments: vi.fn(),
  fetchKgRelations: vi.fn(),
  updateKgRelation: vi.fn(),
  bulkUpdateKgRelations: vi.fn(),
  autoResolveKgRelations: vi.fn(),
  fetchReviewQueues: vi.fn(async () => ({
    studies_suggested: 6003, studies_confirmed: 12,
    sf_support_suggested: 0, sf_support_total: 0,
    facts_pending: 0, facts_total: 0,
    documents_off_domain: 0, documents_gated: 0,
  })),
  fetchDocumentSuggestions: vi.fn(async () => []),
  approveDocument: vi.fn(),
  fetchFactSuggestions: vi.fn(async () => []),
  reviewFact: vi.fn(),
  fetchStylizedFactSuggestions: vi.fn(async () => []),
  reviewStylizedFact: vi.fn(),
}))

vi.mock('@/workers/graphArtifactWorker?worker', () => ({ default: class { postMessage() {} terminate() {} } }))

let wrapper: VueWrapper | null = null

async function mountView() {
  wrapper = mount(KnowledgeBuilderView, {
    attachTo: document.body,
    global: { stubs: { RouterLink: true, CosmographCanvas: true } },
  })
  await flushPromises()
  return wrapper
}

const panel = (w: VueWrapper, label: string) => w.find(`[role="tabpanel"][aria-label="${label}"]`)
const isShown = (w: VueWrapper, label: string) => (panel(w, label).element as HTMLElement).style.display !== 'none'

async function openTab(w: VueWrapper, label: string) {
  const tab = w.findAll('[role="tab"]').find(t => t.text() === label)!
  await tab.trigger('click')
  await flushPromises()
}

beforeEach(() => { vi.clearAllMocks() })
afterEach(() => { wrapper?.unmount(); wrapper = null })

describe('KnowledgeBuilderView shell', () => {
  it('starts on the Graph tab with a skip link to the tab content', async () => {
    const w = await mountView()
    expect(w.element.firstElementChild?.matches('a.skip-link[href="#main-content"]')).toBe(true)
    const main = w.find('#main-content')
    expect(main.attributes('tabindex')).toBe('-1')
    expect(main.findAll('[role="tabpanel"]')).toHaveLength(5)

    expect(isShown(w, 'Graph')).toBe(true)
    expect(isShown(w, 'Ingestion')).toBe(false)
    expect(kbApi.fetchSchemas).toHaveBeenCalledTimes(1)
    // Lazy tabs have not loaded anything yet.
    expect(kbApi.fetchBatches).not.toHaveBeenCalled()
    expect(kbApi.fetchCollections).not.toHaveBeenCalled()
  })

  it('loads each tab when it is first shown, as before', async () => {
    const w = await mountView()

    await openTab(w, 'Database')
    expect(isShown(w, 'Database')).toBe(true)
    expect(isShown(w, 'Graph')).toBe(false)
    expect(kbApi.fetchCollections).toHaveBeenCalledTimes(1)
    expect(w.find('.coll-count').text()).toBe('1.2k')

    await openTab(w, 'Ingestion')
    expect(kbApi.fetchBatches).toHaveBeenCalledTimes(1)
    await openTab(w, 'Database')
    await openTab(w, 'Ingestion')
    // Collections load once; batches reload on every visit.
    expect(kbApi.fetchCollections).toHaveBeenCalledTimes(1)
    expect(kbApi.fetchBatches).toHaveBeenCalledTimes(2)
  })

  it('the Suggestions queue card switches to KG Builder through the store', async () => {
    const w = await mountView()
    await openTab(w, 'Suggestions')
    expect(kbApi.fetchReviewQueues).toHaveBeenCalled()

    await w.find('button.queue-card').trigger('click')
    await flushPromises()
    expect(useKnowledgeBuilderStore().activeTab).toBe('kg')
    expect(isShown(w, 'KG Builder')).toBe(true)
    expect(kbApi.fetchKgStats).toHaveBeenCalledTimes(1)
    const kgTab = w.findAll('[role="tab"]').find(t => t.text() === 'KG Builder')!
    expect(kgTab.attributes('aria-selected')).toBe('true')
  })

  it('announces errors and dismisses them with a button', async () => {
    const w = await mountView()
    useKnowledgeBuilderStore().setError(new Error('Graph artifact failed'))
    await flushPromises()

    const alert = w.find('[role="alert"]')
    expect(alert.text()).toBe('Graph artifact failed')
    const chip = alert.find('button.error-chip')
    expect(chip.attributes('type')).toBe('button')
    await chip.trigger('click')
    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(useKnowledgeBuilderStore().error).toBe('')
  })

  it('asks the in-app dialog before deleting a batch', async () => {
    const w = await mountView()
    await openTab(w, 'Ingestion')
    const dialog = useDialogStore()

    const del = w.findAll('button').find(b => b.text() === 'Delete')!
    await del.trigger('click')
    expect(dialog.current?.tone).toBe('danger')
    dialog.settle(false)
    await flushPromises()
    expect(kbApi.deleteBatch).not.toHaveBeenCalled()

    await del.trigger('click')
    dialog.settle(true)
    await flushPromises()
    expect(kbApi.deleteBatch).toHaveBeenCalledWith('batch-0000000001')
  })

  it('leaving the view resets the shared state', async () => {
    const w = await mountView()
    await openTab(w, 'Database')
    const kb = useKnowledgeBuilderStore()
    kb.setError('stale')
    expect(kb.activeTab).toBe('database')

    w.unmount()
    wrapper = null
    expect(kb.activeTab).toBe('graph')
    expect(kb.error).toBe('')
    expect(kb.graphBundle).toBeNull()
  })
})
