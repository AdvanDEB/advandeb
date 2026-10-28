/**
 * Expert-named papers reach the knowledge base as candidates: a curator sees
 * them in KB → Suggestions and accepts or rejects each one. Nothing an expert
 * names becomes evidence on their word alone.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ExpertEvidenceCandidates from '@/components/kb/ExpertEvidenceCandidates.vue'
import type { EvidenceCandidateList } from '@/types/elicitation.generated'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/api')>()),
  default: api,
}))

const pending: EvidenceCandidateList = {
  counts: { pending: 1, accepted: 0, rejected: 0 },
  candidates: [{
    id: 'r1', sf_number: 1216, statement: 'Embryos do not feed.',
    doi: '10.1016/j.jtbi.2006.09.001', direction: 'opposes', note: 'yolk uptake',
    tier: 'panel', resolved_title: 'A kinetic inhibition mechanism', resolved_year: 2007,
    resolution_status: 'not_in_corpus', status: 'pending', review_comment: null,
    created_at: '2026-10-28T10:00:00Z', reviewed_at: null,
  }],
}

beforeEach(() => { api.get.mockReset(); api.post.mockReset() })

describe('ExpertEvidenceCandidates', () => {
  it('lists pending candidates without naming the expert, and records a review', async () => {
    api.get.mockResolvedValue({ data: pending })
    api.post.mockResolvedValue({ data: { id: 'r1', status: 'rejected' } })
    const w = mount(ExpertEvidenceCandidates)
    await flushPromises()
    expect(api.get).toHaveBeenCalledWith('/elicitation/references/candidates',
      { params: { status_filter: 'pending' } })
    expect(w.text()).toContain('#1216')
    expect(w.text()).toContain('No — needs ingesting')
    expect(w.text()).toContain('panel tier')
    await w.find('input.comment').setValue('  not about embryos ')
    await w.findAll('button').find((b) => b.text() === 'Reject')!.trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/elicitation/references/r1/review',
      { accept: false, comment: 'not about embryos' })
  })

  it('says why when the list cannot load', async () => {
    api.get.mockRejectedValue({ response: { status: 403, data: { detail: 'Curator access required' } } })
    const w = mount(ExpertEvidenceCandidates)
    await flushPromises()
    expect(w.find('[data-test="cand-error"]').text()).toContain('Curator access required')
  })
})
