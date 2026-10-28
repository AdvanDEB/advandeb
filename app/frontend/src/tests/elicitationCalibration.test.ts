/**
 * The calibration gate and flow, against the typed contract.
 *
 * Calibration is the team's handful of real evidence items with agreed
 * answers. The gate shuts only while a PUBLISHED set waits for an expert;
 * with none published, experts work the queue. An earlier client gated on
 * fields the server never sent and waved everyone through to a queue the
 * server refused — so the gate here reads `required`, and nothing else.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

import CalibrationFlow from '@/components/elicitation/CalibrationFlow.vue'
import type { CalibrationStatus } from '@/types/elicitation.generated'
import {
  calibrationCase, evidenceItem, feedback, guidelines, noCalibration, progress, status,
} from './elicitationFixtures'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))

beforeEach(() => {
  api.get.mockReset()
  api.post.mockReset()
})

describe('ElicitationView calibration gate', () => {
  function serve(cal: CalibrationStatus) {
    api.get.mockImplementation((url: string) => {
      if (url.endsWith('/calibration/status')) return Promise.resolve({ data: cal })
      if (url.endsWith('/calibration/next')) return Promise.resolve({ data: calibrationCase(0) })
      // The server returns null from /next while a set waits; the view must
      // not take that for an exhausted queue.
      if (url.endsWith('/next')) return Promise.resolve({ data: cal.required ? null : evidenceItem(1) })
      if (url.endsWith('/progress')) return Promise.resolve({ data: progress })
      if (url.endsWith('/guidelines')) return Promise.resolve({ data: guidelines })
      if (url.endsWith('/references')) return Promise.resolve({ data: { references: [], asserted_evidence: null } })
      if (url.endsWith('/history')) return Promise.resolve({ data: { items: [] } })
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
  }

  async function mountView() {
    const { default: ElicitationView } = await import('@/views/ElicitationView.vue')
    const w = mount(ElicitationView)
    await flushPromises()
    return w
  }

  it('sends an expert to a published set they have not worked', async () => {
    serve(status())
    const w = await mountView()
    expect(w.findComponent(CalibrationFlow).exists()).toBe(true)
    expect(w.text()).not.toContain('Nothing to assess')
    expect(api.get).not.toHaveBeenCalledWith('/elicitation/next')
  })

  it('never blocks while no set is published', async () => {
    serve(noCalibration)
    const w = await mountView()
    expect(w.findComponent(CalibrationFlow).exists()).toBe(false)
    expect(w.findAll('.passage')).toHaveLength(1)
    expect(w.text()).not.toMatch(/not set up|ask an administrator/i)
  })

  it('opens the queue once the set is worked', async () => {
    serve(status({ done: true, required: false, completed: 2, correct: 1 }))
    const w = await mountView()
    expect(w.findComponent(CalibrationFlow).exists()).toBe(false)
    expect(w.findAll('.passage')).toHaveLength(1)
  })

  it('does not wave the expert through when the status call fails', async () => {
    api.get.mockRejectedValue({ response: { data: { detail: 'boom' } } })
    const w = await mountView()
    expect(w.text()).toContain('Could not load the next fact')
    expect(w.text()).not.toContain('Nothing to assess')
  })
})

describe('CalibrationFlow', () => {
  function serveCases(cases = [calibrationCase(0), calibrationCase(1)]) {
    const queue = [...cases]
    api.get.mockImplementation((url: string) => {
      if (url === '/elicitation/calibration/next') return Promise.resolve({ data: queue[0] ?? null })
      if (url === '/elicitation/calibration/status') {
        return Promise.resolve({ data: status({ completed: 2 - queue.length, correct: 1 }) })
      }
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    api.post.mockImplementation((url: string) => {
      if (url !== '/elicitation/calibration/decide') return Promise.reject(new Error(url))
      queue.shift()
      return Promise.resolve({ data: feedback({ completed: 2 - queue.length,
        correct: queue.length === 0, consensus_matches: queue.length === 0 }) })
    })
  }

  async function judge(w: VueWrapper) {
    await w.find('[data-passage="1"] input[value="supports"]').setValue(true)
    await w.find('[data-passage="1"] input[value="primary_evidence"]').setValue(true)
    await w.find('[data-passage="3"] input[value="neutral"]').setValue(true)
    await w.find('input[name^="strength-"][value="2"]').setValue(true)
    await w.find('input[name^="consensus-"][value="2"]').setValue(true)
    await w.find('input[name^="departs-"][value="no"]').setValue(true)
    await w.findAll('button.conf')[2].trigger('click')
  }
  const button = (w: VueWrapper, text: string) =>
    w.findAll('button').find((b) => b.text().includes(text))!

  it('works a real evidence item and posts the server’s CalibrationDecision', async () => {
    serveCases()
    const w = mount(CalibrationFlow)
    await flushPromises()
    expect(w.text()).toContain('Calibration statement 0')
    expect(w.findAll('.passage')).toHaveLength(2)
    // A reference added here would be a real one; calibration offers none.
    expect(w.find('input.doi').exists()).toBe(false)

    expect(button(w, 'Check').attributes('disabled')).toBeDefined()
    await judge(w)
    expect(button(w, 'Check').attributes('disabled')).toBeUndefined()
    await button(w, 'Check').trigger('click')
    await flushPromises()

    const [url, body] = api.post.mock.calls[0]
    expect(url).toBe('/elicitation/calibration/decide')
    expect(body).toMatchObject({
      calibration_id: 'v1:1201:deb', evidence_strength: 2, consensus_direction: 2,
      departs_from_passages: false, confidence: 3, rationale: '',
      passage_judgments: { 1: { direction: 'supports', evidential_role: 'primary_evidence' } },
    })
  })

  it('shows the team’s answer and explanation, then finishes and emits done', async () => {
    serveCases()
    const w = mount(CalibrationFlow)
    await flushPromises()

    await judge(w)
    await button(w, 'Check').trigger('click')
    await flushPromises()
    const reveal = w.find('[data-test="reveal"]')
    expect(reveal.text()).toContain('differs from the team')
    expect(reveal.text()).toContain('Team: Corroborated')
    expect(reveal.text()).toContain('you: Inconclusive')
    expect(reveal.text()).toContain('You agreed on 1 of the 1 passages the team labelled')
    expect(reveal.text()).toContain('Passage 1 reports the measurement')

    await button(w, 'Next example').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Calibration statement 1')

    await judge(w)
    await button(w, 'Check').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="reveal"]').text()).toContain('matches the team')
    await button(w, 'Finish').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Examples done')
    await button(w, 'Start assessing').trigger('click')
    expect(w.emitted('done')).toHaveLength(1)
  })

  it('has no skip', async () => {
    api.get.mockRejectedValue({ response: { data: { detail: 'down' } } })
    const w = mount(CalibrationFlow)
    await flushPromises()
    expect(w.text()).toContain('could not be loaded')
    expect(w.text()).not.toMatch(/continue to the queue|skip/i)
    expect(w.emitted('skip')).toBeUndefined()
  })
})
