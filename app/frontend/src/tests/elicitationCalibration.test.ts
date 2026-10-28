/**
 * The calibration gate and flow, against the typed contract.
 *
 * Two breaks, both silent. The view gated on `required` / `complete` /
 * `passed` — fields the server never sent — so it waved every expert
 * through, the server's own gate made /next return null, and the expert saw
 * "queue exhausted". And the flow posted `{case_id, answer}` to
 * /calibration/answer, an endpoint that does not exist, without the
 * confidence and rationale the server requires.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import CalibrationFlow from '@/components/elicitation/CalibrationFlow.vue'
import type { CalibrationStatus } from '@/types/elicitation.generated'
import {
  calibrationCase, evidenceItem, feedback, guidelines, progress, status,
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
      // The server returns null from /next before calibration; the view must
      // not take that for an exhausted queue.
      if (url.endsWith('/next')) return Promise.resolve({ data: cal.done ? evidenceItem(1) : null })
      if (url.endsWith('/progress')) return Promise.resolve({ data: progress })
      if (url.endsWith('/guidelines')) return Promise.resolve({ data: guidelines })
      if (url.endsWith('/references')) return Promise.resolve({ data: { references: [], asserted_evidence: {} } })
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

  it('sends an uncalibrated expert to calibration, not to "queue exhausted"', async () => {
    serve(status({ done: false, available: true, completed: 0 }))
    const w = await mountView()
    expect(w.findComponent(CalibrationFlow).exists()).toBe(true)
    expect(w.text()).not.toContain('Nothing queued for you')
    expect(api.get).not.toHaveBeenCalledWith('/elicitation/next')
  })

  it('says calibration is not set up when the set is empty — and offers no skip', async () => {
    serve(status({ total: 0, done: false, available: false }))
    const w = await mountView()
    expect(w.text()).toContain('Calibration is not set up yet')
    expect(w.findComponent(CalibrationFlow).exists()).toBe(false)
    expect(w.text()).not.toMatch(/continue to the queue|skip/i)
  })

  it('opens the queue once calibration is done', async () => {
    serve(status({ done: true, completed: 2, correct: 1 }))
    const w = await mountView()
    expect(w.findComponent(CalibrationFlow).exists()).toBe(false)
    expect(w.findAll('.passage')).toHaveLength(1)
  })

  it('does not wave the expert through when the status call fails', async () => {
    api.get.mockRejectedValue({ response: { data: { detail: 'boom' } } })
    const w = await mountView()
    expect(w.text()).toContain('Could not load the queue')
    expect(w.text()).not.toContain('Nothing queued for you')
  })
})

describe('CalibrationFlow', () => {
  function serveCases(cases = [calibrationCase(0), calibrationCase(1)]) {
    const queue = [...cases]
    api.get.mockImplementation((url: string) => {
      if (url === '/elicitation/calibration/next') return Promise.resolve({ data: queue[0] ?? null })
      if (url === '/elicitation/calibration/status') {
        return Promise.resolve({ data: status({ completed: 2, correct: 1, done: true }) })
      }
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    api.post.mockImplementation((url: string) => {
      if (url !== '/elicitation/calibration/decide') return Promise.reject(new Error(url))
      queue.shift()
      return Promise.resolve({ data: feedback({ completed: 2 - queue.length }) })
    })
  }

  async function answer(w: ReturnType<typeof mount>, value: string) {
    await w.find(`input[type="radio"][value="${value}"]`).setValue(true)
    await w.findAll('button.conf')[2].trigger('click')
    await w.find('textarea.rationale').setValue('stated in the collection')
  }

  it('posts the server’s CalibrationDecision to /calibration/decide', async () => {
    serveCases()
    const w = mount(CalibrationFlow)
    await flushPromises()
    expect(w.text()).toContain('Calibration statement 0')

    const check = () => w.findAll('button.primary').find((b) => b.text().includes('Check'))!
    await w.find('input[type="radio"][value="new"]').setValue(true)
    expect(check().attributes('disabled')).toBeDefined()   // no confidence yet
    await answer(w, 'new')
    expect(check().attributes('disabled')).toBeUndefined()
    await check().trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledTimes(1)
    const [url, body] = api.post.mock.calls[0]
    expect(url).toBe('/elicitation/calibration/decide')
    expect(body).toMatchObject({
      calibration_id: 'cal_provenance_1201', task: 'provenance',
      provenance_type: 'new', confidence: 3,
      rationale: 'stated in the collection',
    })
    expect(body).not.toHaveProperty('case_id')
    expect(body).not.toHaveProperty('answer')
  })

  it('shows the reference answer by its label, then finishes and emits done', async () => {
    serveCases()
    const w = mount(CalibrationFlow)
    await flushPromises()

    await answer(w, 'new')
    await w.findAll('button.primary').find((b) => b.text().includes('Check'))!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Differs from the reference')
    expect(w.text()).toContain('reference answer: Published')

    await w.findAll('button.primary').find((b) => b.text().includes('Next'))!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Calibration statement 1')

    await answer(w, 'published')
    await w.findAll('button.primary').find((b) => b.text().includes('Check'))!.trigger('click')
    await flushPromises()
    await w.findAll('button.primary').find((b) => b.text().includes('Finish'))!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Calibration complete')
    expect(w.text()).toContain('1 of')

    await w.findAll('button.primary').find((b) => b.text().includes('Start the queue'))!.trigger('click')
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
