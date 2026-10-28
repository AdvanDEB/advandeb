import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { useKnowledgeBuilderStore } from '@/stores/knowledgeBuilder'
import { isPlainShortcut, targetsAControl } from '@/utils/hotkeys'

/**
 * KG Builder review keys: y confirms, n rejects the relation under the cursor
 * (a PUT, no undo). They fired from a focused button or tab and with
 * Ctrl/Cmd/Alt held — the Critic's run sent "rejected" for n on the focused
 * "KG Builder" tab and "confirmed" for Ctrl+Y on a button (F-027).
 */

const updateKgRelation = vi.fn(async () => ({}))
const rel = (key: string) => ({
  _key: key, document_id: `d-${key}`, document_title: `Doc ${key}`, document_domain_relevant: true,
  tax_id: 1, taxon_name: 'Daphnia magna', taxon_rank: 'species', relation_type: 'studies',
  confidence: 0.9, evidence: 'mentions', status: 'suggested', created_by: 'pipeline',
  created_at: '', updated_at: '',
})

vi.mock('@/utils/kbApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/kbApi')>()),
  fetchKgRelations: vi.fn(async () => ({ relations: [rel('r1'), rel('r2'), rel('r3')], total: 3 })),
  fetchKgStats: vi.fn(async () => null),
  updateKgRelation: (...args: unknown[]) => updateKgRelation(...(args as [])),
}))

const { default: KgBuilderTab } = await import('@/components/kb/tabs/KgBuilderTab.vue')

let wrapper: VueWrapper | null = null

async function loaded() {
  useKnowledgeBuilderStore().activeTab = 'kg'
  wrapper = mount(KgBuilderTab, { attachTo: document.body })
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Load top by confidence')!.trigger('click')
  await flushPromises()
  expect(wrapper.findAll('tbody tr')).toHaveLength(3)
  return wrapper
}

function press(target: EventTarget, key: string, init: KeyboardEventInit = {}) {
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }))
  return flushPromises()
}

// jsdom has no layout; the cursor scrolls its row into view.
Element.prototype.scrollIntoView ??= function () {}

beforeEach(() => updateKgRelation.mockClear())
afterEach(() => { wrapper?.unmount(); wrapper = null; (document.activeElement as HTMLElement | null)?.blur?.() })

describe('KG Builder review keys', () => {
  it('decide the row under the cursor when nothing in particular has focus', async () => {
    await loaded()
    await press(document.body, 'n')
    expect(updateKgRelation).toHaveBeenCalledWith('r1', 'rejected')
  })

  it('do nothing from a focused button: the key belongs to the button', async () => {
    const w = await loaded()
    const load = w.findAll('button').find(b => b.text() === 'Load top by confidence')!.element
    load.focus()
    await press(load, 'n')
    await press(load, 'y')
    expect(updateKgRelation).not.toHaveBeenCalled()
  })

  it('do nothing with Ctrl, Cmd or Alt held', async () => {
    await loaded()
    await press(document.body, 'y', { ctrlKey: true })
    await press(document.body, 'y', { metaKey: true })
    await press(document.body, 'n', { altKey: true })
    expect(updateKgRelation).not.toHaveBeenCalled()
  })

  it('do not repeat a decision while the key is held; moving may repeat', async () => {
    const w = await loaded()
    await press(document.body, 'y', { repeat: true })
    expect(updateKgRelation).not.toHaveBeenCalled()
    await press(document.body, 'j', { repeat: true })
    expect(w.findAll('tbody tr')[1].attributes('aria-current')).toBe('true')
  })
})

describe('targetsAControl', () => {
  it('knows controls, text fields and ARIA widgets', () => {
    const el = (html: string) => {
      const d = document.createElement('div'); d.innerHTML = html
      return d.firstElementChild as HTMLElement
    }
    expect(targetsAControl(el('<button>x</button>'))).toBe(true)
    expect(targetsAControl(el('<a href="#">x</a>'))).toBe(true)
    expect(targetsAControl(el('<textarea></textarea>'))).toBe(true)
    expect(targetsAControl(el('<div role="tab"></div>'))).toBe(true)
    expect(targetsAControl(el('<span>row text</span>'))).toBe(false)
    expect(targetsAControl(document.body)).toBe(false)
  })

  it('isPlainShortcut accepts a bare key on the page', () => {
    expect(isPlainShortcut(new KeyboardEvent('keydown', { key: 'y' }))).toBe(true)
  })
})
