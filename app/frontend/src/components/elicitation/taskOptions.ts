/**
 * Task definitions for elicitation — the single source of truth for what an
 * expert can choose, what each choice means, and which key selects it.
 *
 * Kept out of the view so the guidelines panel, the calibration flow and the
 * history list all render the same labels. A label that reads one way in the
 * form and another way in the guidelines is a silent source of disagreement.
 */

export type TaskType = 'provenance' | 'scope' | 'assessability'

export interface TaskOption {
  value: string
  label: string
  hint: string
  /** Requires the free-text field to be filled when chosen. */
  requiresText?: boolean
}

export interface TaskSpec {
  title: string
  help: string
  /** Which field on the decision payload this task fills. */
  field: 'provenance_type' | 'scope_verdict' | 'assessability'
  /** Free-text companion field, where the task has one. */
  textField?: 'source_citation' | 'proposed_scope'
  textPlaceholder?: string
  textLabel?: string
  options: TaskOption[]
}

/** Home-row keys select options; digits are reserved for confidence. */
export const OPTION_KEYS = ['a', 's', 'd', 'f', 'g'] as const

export const TASKS: Record<TaskType, TaskSpec> = {
  provenance: {
    title: 'Where does this fact come from?',
    help:
      'The collection is mixed provenance and largely untraced. Published facts must be cited to their source; new ones are published here for the first time. "Unknown" is a real answer — recording the gap is better than inventing a provenance.',
    field: 'provenance_type',
    textField: 'source_citation',
    textLabel: 'Source',
    textPlaceholder: 'DOI, or book + chapter (e.g. Kooijman 2010, ch. 3)',
    options: [
      { value: 'published', label: 'Published', hint: 'states a result already in the literature', requiresText: true },
      { value: 'new', label: 'New', hint: 'first stated here, not from a published source' },
      { value: 'adapted', label: 'Adapted', hint: 'a published result, materially restated', requiresText: true },
      { value: 'unknown', label: 'Unknown', hint: 'cannot establish — an acceptable answer' },
    ],
  },
  scope: {
    title: 'What does this fact range over?',
    help:
      'Most of the collection states no organismal scope. Without one, evidence cannot be checked against the claim it is supposed to support — a passage about one species is at most weak evidence for a claim about all animals.',
    field: 'scope_verdict',
    textField: 'proposed_scope',
    textLabel: 'Scope',
    textPlaceholder: 'What does this range over? e.g. ectotherms; isomorphic animals; phytoplankton',
    options: [
      { value: 'stated', label: 'Scope stated', hint: 'the statement says what it ranges over', requiresText: true },
      { value: 'implicit', label: 'Implicit', hint: 'not stated, but clear from context — give it below', requiresText: true },
      { value: 'absent', label: 'Absent', hint: 'no scope, and none can be inferred' },
      { value: 'not_applicable', label: 'Not applicable', hint: 'not a claim about organisms' },
    ],
  },
  assessability: {
    title: 'Can this be assessed as written?',
    help:
      'Some statements cannot be evaluated as written. Recording that is more useful than quietly excluding them — an unassessable fact is a finding about the collection, not a gap in the data.',
    field: 'assessability',
    options: [
      { value: 'assessable', label: 'Assessable', hint: 'could be checked against literature as written' },
      { value: 'too_vague', label: 'Too vague', hint: 'no determinate claim to check' },
      { value: 'compound', label: 'Compound', hint: 'several claims in one sentence' },
      { value: 'not_empirical', label: 'Not empirical', hint: 'a modelling convention or definition' },
      { value: 'unclear_terms', label: 'Unclear terms', hint: 'key terms undefined or ambiguous' },
    ],
  },
}

export function taskSpec(task: TaskType | undefined | null): TaskSpec {
  return TASKS[(task ?? 'provenance') as TaskType] ?? TASKS.provenance
}

export function optionFor(task: TaskType, value: string | null): TaskOption | undefined {
  if (!value) return undefined
  return taskSpec(task).options.find((o) => o.value === value)
}

export function prettyCategory(c: string): string {
  return (c || '').replace(/_/g, ' ')
}

export interface DraftDecision {
  choice: string | null
  text: string
  confidence: number
  rationale: string
}

/**
 * Why a draft cannot be submitted yet, or null when it can.
 *
 * Pure and exported so the guarantee is testable rather than asserted. The
 * case that matters: an option whose meaning depends on a companion field —
 * "Published" with no citation is not a provenance, and "Scope stated" with no
 * scope is not a scope. Those silently recorded as empty would look like data.
 */
export function validateDecision(
  task: TaskType | null | undefined,
  draft: DraftDecision,
): string | null {
  const spec = taskSpec(task)
  if (!draft.choice) return 'Pick an option'

  const option = spec.options.find((o) => o.value === draft.choice)
  if (!option) return 'Pick an option'

  if (option.requiresText && spec.textField && !draft.text.trim()) {
    return `${spec.textLabel} is required for “${option.label}”`
  }
  if (!draft.confidence || draft.confidence < 1 || draft.confidence > 5) {
    return 'Set your confidence'
  }
  if (!draft.rationale.trim()) return 'A short rationale is required'
  return null
}
