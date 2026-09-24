import { describe, expect, it } from 'vitest'

import {
  OPTION_KEYS,
  TASKS,
  optionFor,
  taskSpec,
  validateDecision,
  type DraftDecision,
  type TaskType,
} from '@/components/elicitation/taskOptions'

const complete = (over: Partial<DraftDecision> = {}): DraftDecision => ({
  choice: 'unknown', text: '', confidence: 3, rationale: 'because', ...over,
})

describe('elicitation decision validation', () => {
  it('accepts a complete draft', () => {
    expect(validateDecision('provenance', complete())).toBeNull()
  })

  it.each(['provenance', 'scope', 'assessability'] as TaskType[])(
    'blocks %s with no option chosen', (task) => {
      expect(validateDecision(task, complete({ choice: null }))).toBe('Pick an option')
    })

  it('blocks a confidence outside 1-5', () => {
    expect(validateDecision('provenance', complete({ confidence: 0 })))
      .toBe('Set your confidence')
    expect(validateDecision('provenance', complete({ confidence: 6 })))
      .toBe('Set your confidence')
  })

  it('blocks an empty or whitespace rationale', () => {
    expect(validateDecision('provenance', complete({ rationale: '' })))
      .toMatch(/rationale/)
    expect(validateDecision('provenance', complete({ rationale: '   ' })))
      .toMatch(/rationale/)
  })

  // The case this function exists for: an option whose meaning depends on a
  // companion field. "Published" with no citation is not a provenance.
  it('blocks every option that requires a companion field when it is empty', () => {
    for (const [task, spec] of Object.entries(TASKS)) {
      for (const option of spec.options.filter((o) => o.requiresText)) {
        const why = validateDecision(task as TaskType,
          complete({ choice: option.value, text: '' }))
        expect(why, `${task}/${option.value} should be blocked`).not.toBeNull()
        expect(why).toContain(spec.textLabel!)
      }
    }
  })

  it('accepts those same options once the companion field is filled', () => {
    for (const [task, spec] of Object.entries(TASKS)) {
      for (const option of spec.options.filter((o) => o.requiresText)) {
        expect(validateDecision(task as TaskType,
          complete({ choice: option.value, text: 'Kooijman 2010, ch. 3' })),
        `${task}/${option.value} should pass`).toBeNull()
      }
    }
  })

  it('does not demand a companion field for options that have none', () => {
    for (const [task, spec] of Object.entries(TASKS)) {
      for (const option of spec.options.filter((o) => !o.requiresText)) {
        expect(validateDecision(task as TaskType,
          complete({ choice: option.value, text: '' }))).toBeNull()
      }
    }
  })

  it('rejects an option value that belongs to a different task', () => {
    expect(validateDecision('scope', complete({ choice: 'published' })))
      .toBe('Pick an option')
  })
})

describe('task specs', () => {
  it('has enough option keys for every task', () => {
    for (const spec of Object.values(TASKS)) {
      expect(spec.options.length).toBeLessThanOrEqual(OPTION_KEYS.length)
    }
  })

  it('gives every option a unique value within its task', () => {
    for (const spec of Object.values(TASKS)) {
      const values = spec.options.map((o) => o.value)
      expect(new Set(values).size).toBe(values.length)
    }
  })

  it('declares a text field wherever an option requires one', () => {
    for (const spec of Object.values(TASKS)) {
      if (spec.options.some((o) => o.requiresText)) {
        expect(spec.textField).toBeTruthy()
        expect(spec.textLabel).toBeTruthy()
      }
    }
  })

  it('falls back to a usable spec for an unknown task', () => {
    expect(taskSpec(undefined).options.length).toBeGreaterThan(0)
    expect(taskSpec(null).title).toBeTruthy()
  })

  it('resolves option labels for the history list', () => {
    expect(optionFor('provenance', 'published')?.label).toBe('Published')
    expect(optionFor('provenance', null)).toBeUndefined()
  })
})
