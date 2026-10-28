/**
 * The evidence task, end to end in the client: the draft, its validation, the
 * payload, the passage-labelling component, and the view that ties them
 * together.
 *
 * Before this, an evidence item fell back to the provenance form, the
 * passages were hidden behind a missing `evidence_condition`, and the submit
 * payload carried none of corpus, hash, scores or passage judgments — so the
 * server refused every evidence decision an expert could have made.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import EvidencePanel from '@/components/elicitation/EvidencePanel.vue'
import {
  buildDecision, emptyEvidenceDraft, labelledCount, validateEvidence,
  withDirection, withRole, type EvidenceDraft,
} from '@/components/elicitation/decision'
import { TASKS, taskSpec, validateDecision } from '@/components/elicitation/taskOptions'
import type { TaskType } from '@/types/elicitation.generated'
import { evidenceItem, guidelines, progress, provenanceItem, status } from './elicitationFixtures'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))

const common = { confidence: 3, rationale: 'because', choice: null, text: '' }

function labelAll(item = evidenceItem(), dir: 'neutral' | 'supports' = 'neutral'): EvidenceDraft {
  let d = emptyEvidenceDraft(item)
  for (const p of item.passages) {
    d = withDirection(d, String(p.index), dir)
    if (dir !== 'neutral') d = withRole(d, String(p.index), 'primary_evidence')
  }
  return { ...d, evidence_strength: 2, consensus_direction: 3 }
}

describe('task specs', () => {
  it('has a spec for every server task — evidence included', () => {
    const tasks: TaskType[] = ['provenance', 'scope', 'assessability', 'evidence']
    for (const t of tasks) expect(TASKS[t]).toBeDefined()
    expect(taskSpec('evidence').title).toMatch(/passages/)
  })

  it('never falls back to another task’s form', () => {
    // The fallback to provenance is what silently mis-rendered evidence items.
    const unknown = taskSpec('nonsense' as TaskType)
    expect(unknown.title).toBe('Unknown task')
    expect(unknown.options).toEqual([])
    expect(validateDecision('nonsense' as TaskType, { ...common, choice: 'published' }))
      .not.toBeNull()
  })
})

describe('evidence draft', () => {
  it('keys passages by canonical index, not position', () => {
    const item = evidenceItem(3)
    expect(Object.keys(emptyEvidenceDraft(item).passages)).toEqual(['1', '3', '5'])
  })

  it('clears the role when a passage is set to neutral', () => {
    let d = emptyEvidenceDraft(evidenceItem(1))
    d = withDirection(d, '1', 'supports')
    d = withRole(d, '1', 'restatement')
    expect(d.passages['1']).toEqual({ direction: 'supports', evidential_role: 'restatement' })
    d = withDirection(d, '1', 'neutral')
    expect(d.passages['1']).toEqual({ direction: 'neutral', evidential_role: null })
  })

  it('requires every passage to be labelled', () => {
    const item = evidenceItem(4)
    let d = labelAll(item)
    d = { ...d, passages: { ...d.passages, '5': { direction: null, evidential_role: null } } }
    expect(labelledCount(item, d)).toBe(3)
    expect(validateEvidence(item, d, common)).toBe('Label every passage (3 of 4 done)')
  })

  it('requires a role on every non-neutral passage, naming it by position', () => {
    const item = evidenceItem(4)
    const d = withDirection(labelAll(item), '5', 'contradicts')
    // canonical index 5 is the third passage shown
    expect(validateEvidence(item, d, common)).toBe('Give an evidential role for passage 3')
  })

  it('requires both scores, then confidence and rationale', () => {
    const item = evidenceItem(2)
    const d = labelAll(item)
    expect(validateEvidence(item, { ...d, evidence_strength: null }, common))
      .toMatch(/evidence strength/)
    expect(validateEvidence(item, { ...d, consensus_direction: null }, common))
      .toMatch(/consensus direction/)
    expect(validateEvidence(item, d, { ...common, confidence: 0 })).toBe('Set your confidence')
    expect(validateEvidence(item, d, { ...common, rationale: '  ' })).toMatch(/rationale/)
    expect(validateEvidence(item, d, common)).toBeNull()
  })

  it('refuses an evidence item with no passages', () => {
    expect(validateEvidence(evidenceItem(0), labelAll(evidenceItem(0)), common))
      .toMatch(/no passages/)
  })
})

describe('decision payload', () => {
  it('carries everything the server checks on an evidence decision', () => {
    const item = evidenceItem(3)
    let d = labelAll(item)
    d = withDirection(d, '3', 'supports')
    d = withRole(d, '3', 'derivation')
    const payload = buildDecision(item, { ...common, choice: null }, d,
      { time_spent_s: 41, machine_verdict_expanded: false })
    expect(payload).toEqual({
      task: 'evidence',
      sf_number: 1216,
      statement_sha256: item.statement_sha256,
      corpus_id: 'deb',
      evidence_set_id: 'growth_11:deb',
      evidence_content_hash: item.evidence_content_hash,
      evidence_strength: 2,
      consensus_direction: 3,
      passage_judgments: {
        1: { direction: 'neutral', evidential_role: null },
        3: { direction: 'supports', evidential_role: 'derivation' },
        5: { direction: 'neutral', evidential_role: null },
      },
      confidence: 3,
      rationale: 'because',
      time_spent_s: 41,
      machine_verdict_expanded: false,
    })
    // The server decides the arm from the task; the client never claims one.
    expect(payload).not.toHaveProperty('evidence_condition')
    expect(payload).not.toHaveProperty('provenance_type')
  })

  it('sends only the task’s own field on a fact-level decision', () => {
    const payload = buildDecision(provenanceItem(),
      { choice: 'published', text: ' Kooijman 2010 ', confidence: 4, rationale: 'r' },
      emptyEvidenceDraft(null), { time_spent_s: 5, machine_verdict_expanded: true })
    expect(payload).toEqual({
      task: 'provenance', sf_number: 565,
      statement_sha256: provenanceItem().statement_sha256,
      provenance_type: 'published', source_citation: 'Kooijman 2010',
      confidence: 4, rationale: 'r', time_spent_s: 5,
      machine_verdict_expanded: true,
    })
  })
})

describe('EvidencePanel', () => {
  it('labels a passage and asks for a role only when it is not neutral', async () => {
    const item = evidenceItem(2)
    const w = mount(EvidencePanel, {
      props: { passages: item.passages, modelValue: emptyEvidenceDraft(item) },
    })
    expect(w.text()).toContain('0 / 2 labelled')
    expect(w.findAll('.roles')).toHaveLength(0)

    await w.find('input[name="dir-3"][value="contradicts"]').setValue(true)
    const emitted = w.emitted('update:modelValue')!.at(-1)![0] as EvidenceDraft
    expect(emitted.passages['3']).toEqual({ direction: 'contradicts', evidential_role: null })

    await w.setProps({ modelValue: emitted })
    expect(w.findAll('.roles')).toHaveLength(1)
    await w.find('input[name="role-3"][value="review"]').setValue(true)
    const withRoleSet = w.emitted('update:modelValue')!.at(-1)![0] as EvidenceDraft
    expect(withRoleSet.passages['3'].evidential_role).toBe('review')
  })

  it('says when fewer passages are shown than the set holds', () => {
    const item = evidenceItem(2)
    const w = mount(EvidencePanel, {
      props: { passages: item.passages, modelValue: emptyEvidenceDraft(item), total: 18 },
    })
    expect(w.text()).toContain('2 of the 18 passages')
  })
})

describe('ElicitationView — evidence item', () => {
  beforeEach(() => {
    api.get.mockReset()
    api.post.mockReset()
  })

  function serve(item = evidenceItem(2)) {
    api.get.mockImplementation((url: string) => {
      if (url.endsWith('/calibration/status')) return Promise.resolve({ data: status({ done: true, completed: 2 }) })
      if (url.endsWith('/next')) return Promise.resolve({ data: item })
      if (url.endsWith('/progress')) return Promise.resolve({ data: progress })
      if (url.endsWith('/guidelines')) return Promise.resolve({ data: guidelines })
      if (url.endsWith('/references')) return Promise.resolve({ data: { references: [], asserted_evidence: {} } })
      if (url.endsWith('/history')) return Promise.resolve({ data: { items: [] } })
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    api.post.mockResolvedValue({ data: { status: 'recorded', id: 'x', round: 'primary' } })
    return item
  }

  async function mountView() {
    const { default: ElicitationView } = await import('@/views/ElicitationView.vue')
    const w = mount(ElicitationView)
    await flushPromises()
    return w
  }

  it('shows the passages and the matched condition, not the provenance form', async () => {
    serve()
    const w = await mountView()
    expect(w.find('[data-test="condition"]').text()).toBe('judging the evidence set')
    expect(w.findAll('.passage')).toHaveLength(2)
    expect(w.text()).toContain('How well do these passages support the fact?')
    expect(w.text()).not.toContain('Where does this fact come from?')
    expect(w.find('input[name="evidence_strength"]').exists()).toBe(true)
  })

  it('submits only once every passage, both scores, confidence and rationale are given', async () => {
    const item = serve()
    const w = await mountView()
    const submit = () => w.find('button.primary')
    expect(submit().attributes('disabled')).toBeDefined()

    await w.find('input[name="dir-1"][value="supports"]').setValue(true)
    await w.find('input[name="role-1"][value="primary_evidence"]').setValue(true)
    await w.find('input[name="dir-3"][value="neutral"]').setValue(true)
    await w.find('input[name="evidence_strength"][value="2"]').setValue(true)
    expect(w.find('[data-test="blocked"]').text()).toMatch(/consensus direction/)
    await w.find('input[name="consensus_direction"][value="3"]').setValue(true)
    await w.findAll('button.conf')[3].trigger('click')
    await w.find('textarea.rationale').setValue('one clear measurement')
    expect(submit().attributes('disabled')).toBeUndefined()

    await submit().trigger('click')
    await flushPromises()
    const [url, body] = api.post.mock.calls.find(([u]) => u === '/elicitation/decide')!
    expect(url).toBe('/elicitation/decide')
    expect(body).toMatchObject({
      task: 'evidence', sf_number: item.sf_number, corpus_id: 'deb',
      evidence_set_id: item.evidence_set_id,
      evidence_content_hash: item.evidence_content_hash,
      evidence_strength: 2, consensus_direction: 3, confidence: 4,
      rationale: 'one clear measurement',
      passage_judgments: {
        1: { direction: 'supports', evidential_role: 'primary_evidence' },
        3: { direction: 'neutral', evidential_role: null },
      },
    })
  })

  it('offers the next item when the queue has moved on (409)', async () => {
    serve(evidenceItem(1))
    const w = await mountView()
    await w.find('input[name="dir-1"][value="neutral"]').setValue(true)
    await w.find('input[name="evidence_strength"][value="1"]').setValue(true)
    await w.find('input[name="consensus_direction"][value="2"]').setValue(true)
    await w.findAll('button.conf')[2].trigger('click')
    await w.find('textarea.rationale').setValue('r')
    api.post.mockRejectedValueOnce({ response: { status: 409, data: {
      detail: "this item's panel requirement is already met; the queue has moved on" } } })
    await w.find('button.primary').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="error"]').text()).toMatch(/already met/)
    expect(w.text()).toContain('Load the next item')
  })

  it('logs opening the machine assessment, with whether the expert had answered', async () => {
    serve(provenanceItem({ legacy_assessment: { score_1_100: 78, confidence: 'high',
      n_supporting_refs: 3, source: 'legacy' } }))
    const w = await mountView()
    await w.find('[data-test="machine-toggle"]').trigger('click')
    await w.find('[data-test="machine-toggle"]').trigger('click')
    const events = api.post.mock.calls.filter(([u]) => u === '/elicitation/events')
      .map(([, b]) => b)
    expect(events).toEqual([
      { event: 'machine_verdict_opened', sf_number: 565, task: 'provenance',
        corpus_id: null, answered: false },
      { event: 'machine_verdict_closed', sf_number: 565, task: 'provenance',
        corpus_id: null, answered: false },
    ])
  })
})
