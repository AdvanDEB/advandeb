/**
 * The judgment, end to end in the client: the draft, its validation and the
 * rationale rule, the payload, the passage panel with its citations, and the
 * view that ties them together.
 *
 * One combined mode since guidelines 2.0: every passage labelled by what it
 * says, the fact judged from the passages and what the expert knows, and a
 * reason asked for only where that judgment departs from the passages.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

import EvidencePanel from '@/components/elicitation/EvidencePanel.vue'
import {
  buildDecision, conflictText, emptyEvidenceDraft, labelledCount,
  rationaleRequired, scoreLabelConflicts, validateEvidence, withDirection,
  withRole, type EvidenceDraft,
} from '@/components/elicitation/decision'
import { citationText, citationView } from '@/components/elicitation/citation'
import { TASKS, taskSpec, validateDecision } from '@/components/elicitation/taskOptions'
import type { TaskType } from '@/types/elicitation.generated'
import {
  citation, evidenceItem, guidelines, noCalibration, progress, unresolvedCitation,
} from './elicitationFixtures'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))

const common = { confidence: 3, rationale: '' }

function labelAll(item = evidenceItem(), dir: 'neutral' | 'supports' = 'neutral'): EvidenceDraft {
  let d = emptyEvidenceDraft(item)
  for (const p of item.passages) {
    d = withDirection(d, String(p.index), dir)
    if (dir !== 'neutral') d = withRole(d, String(p.index), 'primary_evidence')
  }
  return { ...d, evidence_strength: 1, consensus_direction: 2, departs: false }
}

describe('task specs', () => {
  it('has a spec for every server task — evidence included', () => {
    const tasks: TaskType[] = ['provenance', 'scope', 'assessability', 'evidence']
    for (const t of tasks) expect(TASKS[t]).toBeDefined()
    expect(taskSpec('evidence').help).toMatch(/what you know/)
  })

  it('never falls back to another task’s form', () => {
    const unknown = taskSpec('nonsense' as TaskType)
    expect(unknown.title).toBe('Unknown task')
    expect(validateDecision('nonsense' as TaskType,
      { confidence: 3, rationale: 'r', choice: 'published', text: '' })).not.toBeNull()
  })
})

describe('citations', () => {
  it('shows a full citation: authors, year, title, journal and a DOI link', () => {
    const v = citationView(citation())
    expect(v.lead).toBe('Caroline Tolla, Sebastiaan A.L.M. Kooijman & Jean-Christophe Poggiale (2007)')
    expect(v.title).toBe('A kinetic inhibition mechanism for maintenance')
    expect(v.venue).toBe('Journal of Theoretical Biology')
    expect(v.doiUrl).toBe('https://doi.org/10.1016/j.jtbi.2006.09.001')
    expect(v.unresolved).toBeNull()
  })

  it('says plainly when a source is not identified, naming the file', () => {
    const v = citationView(unresolvedCitation)
    expect(v.unresolved).toBe('Source not yet identified — file Kooy93.pdf (DEB library #2801)')
    expect(v.title).toBeNull()
    expect(citationText(null)).toBe('Source not yet identified')
  })

  it('abbreviates a long author list and adds pages when known', () => {
    const v = citationView(citation({
      authors: ['A', 'B', 'C', 'D', 'E', 'F', 'G'], pages: '12-19', year: null }))
    expect(v.lead).toBe('A, B, C, D, E, F et al. (n.d.)')
    expect(v.venue).toBe('Journal of Theoretical Biology, pp. 12-19')
  })
})

describe('evidence draft', () => {
  it('keys passages by canonical index, not position', () => {
    expect(Object.keys(emptyEvidenceDraft(evidenceItem(3)).passages)).toEqual(['1', '3', '5'])
  })

  it('clears the role when a passage is set to neutral', () => {
    let d = emptyEvidenceDraft(evidenceItem(1))
    d = withDirection(d, '1', 'supports')
    d = withRole(d, '1', 'restatement')
    d = withDirection(d, '1', 'neutral')
    expect(d.passages['1']).toEqual({ direction: 'neutral', evidential_role: null })
  })

  it('treats “cannot judge” as a label that asks no role', () => {
    const item = evidenceItem(2)
    let d = labelAll(item)
    d = withDirection(d, '1', 'supports')
    d = withRole(d, '1', 'restatement')
    d = withDirection(d, '1', 'cannot_judge')
    expect(d.passages['1']).toEqual({ direction: 'cannot_judge', evidential_role: null })
    expect(validateEvidence(item, d, common)).toBeNull()
  })

  it('requires every passage to be labelled, then roles, named by position', () => {
    const item = evidenceItem(4)
    let d = labelAll(item)
    d = { ...d, passages: { ...d.passages, '5': { direction: null, evidential_role: null } } }
    expect(labelledCount(item, d)).toBe(3)
    expect(validateEvidence(item, d, common)).toBe('Label every passage (3 of 4 done)')
    d = withDirection(labelAll(item), '5', 'contradicts')
    expect(validateEvidence(item, d, common)).toBe('Say what kind of evidence passage 3 is')
  })

  it('asks for both scores, the departure answer and confidence', () => {
    const item = evidenceItem(2)
    const d = labelAll(item)
    expect(validateEvidence(item, { ...d, evidence_strength: null }, common)).toMatch(/strength/)
    expect(validateEvidence(item, { ...d, consensus_direction: null }, common)).toMatch(/which way/)
    expect(validateEvidence(item, { ...d, departs: null }, common)).toMatch(/goes beyond/)
    expect(validateEvidence(item, d, { ...common, confidence: 0 })).toBe('Set your confidence')
  })

  it('needs no reason when the judgment follows the passages', () => {
    const item = evidenceItem(2)
    expect(rationaleRequired(item, labelAll(item))).toBe(false)
    expect(validateEvidence(item, labelAll(item), common)).toBeNull()
  })

  it('needs a reason when the expert says the judgment goes beyond the passages', () => {
    const item = evidenceItem(2)
    const d = { ...labelAll(item), departs: true }
    expect(validateEvidence(item, d, common)).toMatch(/goes beyond the passages/)
    expect(validateEvidence(item, d, { ...common, rationale: 'Kooijman 2010, ch. 2' })).toBeNull()
  })

  it('needs a reason when the scores go beyond the expert’s own labels', () => {
    const item = evidenceItem(2)
    const corroborated = { ...labelAll(item), consensus_direction: 3, evidence_strength: 3 }
    expect(scoreLabelConflicts(item, corroborated)).toEqual([
      'corroborated_without_support', 'strength_without_support'])
    expect(conflictText(['against_without_contradiction'])).toMatch(/no passage as disputing/)
    expect(validateEvidence(item, corroborated, common)).toMatch(/your passage labels/)
    // A supporting passage resolves both.
    const supported = withRole(withDirection(corroborated, '1', 'supports'), '1', 'primary_evidence')
    expect(scoreLabelConflicts(item, supported)).toEqual([])
    expect(scoreLabelConflicts(item, { ...labelAll(item), consensus_direction: 1 }))
      .toEqual(['against_without_contradiction'])
  })

  it('refuses an item with no passages', () => {
    expect(validateEvidence(evidenceItem(0), labelAll(evidenceItem(0)), common)).toMatch(/no passages/)
  })
})

describe('decision payload', () => {
  it('carries everything the server checks, and no arm', () => {
    const item = evidenceItem(3)
    let d = labelAll(item)
    d = withRole(withDirection(d, '3', 'supports'), '3', 'derivation')
    const payload = buildDecision(item, { ...d, departs: true },
      { confidence: 4, rationale: ' I know of a counter-example ' },
      { time_spent_s: 41, reference_ids: ['r1'] })
    expect(payload).toEqual({
      task: 'evidence',
      sf_number: 1216,
      statement_sha256: item.statement_sha256,
      corpus_id: 'deb',
      evidence_set_id: 'growth_11:deb',
      evidence_content_hash: item.evidence_content_hash,
      evidence_strength: 1,
      consensus_direction: 2,
      passage_judgments: {
        1: { direction: 'neutral', evidential_role: null },
        3: { direction: 'supports', evidential_role: 'derivation' },
        5: { direction: 'neutral', evidential_role: null },
      },
      departs_from_passages: true,
      reference_ids: ['r1'],
      confidence: 4,
      rationale: 'I know of a counter-example',
      time_spent_s: 41,
    })
    expect(payload).not.toHaveProperty('evidence_condition')
    expect(payload).not.toHaveProperty('machine_verdict_expanded')
  })
})

describe('EvidencePanel', () => {
  it('shows every passage with its citation, and an unresolved one plainly', () => {
    const item = evidenceItem(2)
    const w = mount(EvidencePanel, {
      props: { passages: item.passages, modelValue: emptyEvidenceDraft(item) },
    })
    const cites = w.findAll('[data-test="citation"]')
    expect(cites[0].text()).toContain('(2007)')
    expect(cites[0].find('a').attributes('href')).toBe('https://doi.org/10.1016/j.jtbi.2006.09.001')
    expect(cites[1].text()).toContain('Source not yet identified — file Kooy93.pdf')
    expect(cites[1].find('a').exists()).toBe(false)
  })

  it('labels a passage and asks for a role only when it is not neutral', async () => {
    const item = evidenceItem(2)
    const w = mount(EvidencePanel, {
      props: { passages: item.passages, modelValue: emptyEvidenceDraft(item) },
    })
    expect(w.text()).toContain('0 of 2 labelled')
    expect(w.findAll('.roles')).toHaveLength(0)
    await w.find('[data-passage="3"] input[value="contradicts"]').setValue(true)
    const emitted = w.emitted('update:modelValue')!.at(-1)![0] as EvidenceDraft
    expect(emitted.passages['3']).toEqual({ direction: 'contradicts', evidential_role: null })
    await w.setProps({ modelValue: emitted })
    expect(w.findAll('.roles')).toHaveLength(1)
    await w.find('[data-passage="3"] input[value="review"]').setValue(true)
    const withRoleSet = w.emitted('update:modelValue')!.at(-1)![0] as EvidenceDraft
    expect(withRoleSet.passages['3'].evidential_role).toBe('review')
  })

  it('says when fewer passages are shown than were found', () => {
    const item = evidenceItem(2)
    const w = mount(EvidencePanel, {
      props: { passages: item.passages, modelValue: emptyEvidenceDraft(item), total: 18 },
    })
    expect(w.text()).toContain('2 of the 18 passages')
  })
})

describe('ElicitationView', () => {
  beforeEach(() => {
    api.get.mockReset()
    api.post.mockReset()
    try { localStorage.clear() } catch { /* jsdom always has it */ }
  })

  function serve(item = evidenceItem(2)) {
    api.get.mockImplementation((url: string) => {
      if (url.endsWith('/calibration/status')) return Promise.resolve({ data: noCalibration })
      if (url.endsWith('/next')) return Promise.resolve({ data: item })
      if (url.endsWith('/progress')) return Promise.resolve({ data: progress })
      if (url.endsWith('/guidelines')) return Promise.resolve({ data: guidelines })
      if (url.endsWith('/references')) return Promise.resolve({ data: { references: [], asserted_evidence: null } })
      if (url.endsWith('/history')) return Promise.resolve({ data: { items: [] } })
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    api.post.mockResolvedValue({ data: { status: 'recorded', id: 'x', round: 'primary' } })
    return item
  }

  async function mountView() {
    const { default: ElicitationView } = await import('@/views/ElicitationView.vue')
    const w = mount(ElicitationView, { attachTo: document.body })
    await flushPromises()
    return w
  }

  async function judge(w: VueWrapper, { departs = false } = {}) {
    await w.find('[data-passage="1"] input[value="supports"]').setValue(true)
    await w.find('[data-passage="1"] input[value="primary_evidence"]').setValue(true)
    await w.find('[data-passage="3"] input[value="neutral"]').setValue(true)
    await w.find('input[name^="strength-"][value="2"]').setValue(true)
    await w.find('input[name^="consensus-"][value="3"]').setValue(true)
    await w.find(`input[name^="departs-"][value="${departs ? 'yes' : 'no'}"]`).setValue(true)
    await w.findAll('button.conf')[3].trigger('click')
  }

  it('shows one combined mode: no arm badge, no machine score, the intro on first visit', async () => {
    serve()
    const w = await mountView()
    expect(w.find('[data-test="how-it-works"]').exists()).toBe(true)
    expect(w.text()).toContain('Label each passage')
    expect(w.text()).toContain('Does your judgment go beyond or against what these passages show?')
    expect(w.text()).not.toMatch(/judging from expertise|judging the evidence set/)
    expect(w.find('[data-test="machine-toggle"]').exists()).toBe(false)
    // The corpus of origin stays hidden (docs/02 §5); citations do not.
    expect(w.find('[data-test="corpus"]').exists()).toBe(false)
    expect(w.findAll('.passage')).toHaveLength(2)
    w.unmount()
  })

  it('submits without a reason when the judgment follows the passages', async () => {
    const item = serve()
    const w = await mountView()
    const submit = () => w.find('[data-test="submit"]')
    expect(submit().attributes('disabled')).toBeDefined()
    await judge(w)
    expect(w.find('textarea.rationale').attributes('required')).toBeUndefined()
    expect(submit().attributes('disabled')).toBeUndefined()
    await submit().trigger('click')
    await flushPromises()
    const [, body] = api.post.mock.calls.find(([u]) => u === '/elicitation/decide')!
    expect(body).toMatchObject({
      task: 'evidence', sf_number: item.sf_number, corpus_id: 'deb',
      evidence_strength: 2, consensus_direction: 3, confidence: 4,
      departs_from_passages: false, rationale: '', reference_ids: [],
      passage_judgments: {
        1: { direction: 'supports', evidential_role: 'primary_evidence' },
        3: { direction: 'neutral', evidential_role: null },
      },
    })
    w.unmount()
  })

  it('requires a reason and opens the reference form when the expert departs', async () => {
    serve()
    const w = await mountView()
    await judge(w, { departs: true })
    expect(w.find('textarea.rationale').attributes('required')).toBeDefined()
    expect(w.find('[data-test="submit"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="blocked"]').text()).toMatch(/goes beyond the passages/)
    expect(w.text()).toContain('Add the reference you are relying on')
    expect(w.find('input.doi').exists()).toBe(true)
    await w.find('textarea.rationale').setValue('A 2015 field study contradicts this.')
    expect(w.find('[data-test="submit"]').attributes('disabled')).toBeUndefined()
    w.unmount()
  })

  it('explains a conflict between the scores and the expert’s own labels', async () => {
    serve()
    const w = await mountView()
    await w.find('[data-passage="1"] input[value="neutral"]').setValue(true)
    await w.find('[data-passage="3"] input[value="neutral"]').setValue(true)
    await w.find('input[name^="strength-"][value="1"]').setValue(true)
    await w.find('input[name^="consensus-"][value="3"]').setValue(true)
    await w.find('input[name^="departs-"][value="no"]').setValue(true)
    expect(w.find('[data-test="conflict"]').text()).toMatch(/no passage as supporting/)
    expect(w.find('textarea.rationale').attributes('required')).toBeDefined()
    w.unmount()
  })

  it('offers the next fact when the queue has moved on (409)', async () => {
    serve()
    const w = await mountView()
    await judge(w)
    api.post.mockRejectedValueOnce({ response: { status: 409, data: {
      detail: "this item's panel requirement is already met; the queue has moved on" } } })
    await w.find('[data-test="submit"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="error"]').text()).toMatch(/already met/)
    expect(w.text()).toContain('Load the next fact')
    w.unmount()
  })

  it('keeps the introduction closed once dismissed', async () => {
    serve()
    let w = await mountView()
    await w.find('[data-test="how-it-works"] button').trigger('click')
    expect(w.find('[data-test="how-it-works"]').exists()).toBe(false)
    w.unmount()
    w = await mountView()
    expect(w.find('[data-test="how-it-works"]').exists()).toBe(false)
    w.unmount()
  })
})
