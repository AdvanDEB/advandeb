/**
 * Task definitions for elicitation — the single source of truth for what an
 * expert can choose, what each choice means, and which key selects it.
 *
 * Kept out of the view so the guidelines panel, the calibration flow and the
 * history list all render the same labels. A label that reads one way in the
 * form and another way in the guidelines is a silent source of disagreement.
 */

import type {
  EvidentialRole, PassageDirection, TaskType,
} from '@/types/elicitation.generated'

// The task list comes from the server's models, generated — never restated
// here. A hand-written copy of it once lacked `evidence`, so evidence items
// fell through to the provenance form and the passages were never shown.
export type { TaskType }

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
  /** Which field on the decision payload this task fills. Null for the
   *  evidence task, whose answer is per-passage labels plus two scores. */
  field: 'provenance_type' | 'scope_verdict' | 'assessability' | null
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
  evidence: {
    title: 'How well is this fact supported?',
    help:
      'Label every passage by what it says. Then judge the fact as an expert — from the passages and from what you know.',
    field: null,
    options: [],
  },
}

/** Shown in place of a form when the server sends a task this client does
 *  not know. Never another task's form: falling back to provenance is
 *  exactly how evidence items were silently mis-rendered. */
const UNKNOWN_TASK: TaskSpec = {
  title: 'Unknown task',
  help: 'This item is of a task this page does not know how to show. Reload the page; if it persists, the client is out of date.',
  field: null,
  options: [],
}

export function taskSpec(task: TaskType | undefined | null): TaskSpec {
  return (task && TASKS[task]) || UNKNOWN_TASK
}

// ---- the evidence task: per-passage labels and two fact-level scores ----
// The passage labels keep the axes and wording the agents were given
// (docs/01 4.2a), so passage-level agreement stays comparable. The two
// fact-level scores are the expert's own judgment of the fact (H-EK): from
// the passages and from what they know.

export interface LabelOption<T extends string | number> {
  value: T
  label: string
  hint: string
}

export const DIRECTION_OPTIONS: LabelOption<PassageDirection>[] = [
  { value: 'supports', label: 'Supports', hint: 'consistent with the fact' },
  { value: 'contradicts', label: 'Contradicts', hint: 'inconsistent with it' },
  { value: 'neutral', label: 'Neutral', hint: 'another topic, or no bearing either way' },
]

/** Asked of every passage not called neutral. */
export const ROLE_OPTIONS: LabelOption<EvidentialRole>[] = [
  { value: 'primary_evidence', label: 'Primary evidence', hint: 'reports a measurement or observation' },
  { value: 'restatement', label: 'Restatement', hint: 'asserts the fact, citing rather than testing it' },
  { value: 'derivation', label: 'Derivation', hint: 'follows from theory or a model, not data' },
  { value: 'review', label: 'Review', hint: "summarises others' findings" },
]

export const STRENGTH_OPTIONS: LabelOption<number>[] = [
  { value: 1, label: 'Weak or sparse', hint: 'little or no real support' },
  { value: 2, label: 'Moderate', hint: 'some support' },
  { value: 3, label: 'Strong', hint: 'several clear, independent supporting studies' },
]

export const CONSENSUS_OPTIONS: LabelOption<number>[] = [
  { value: 1, label: 'Against', hint: 'mostly contradicted' },
  { value: 2, label: 'Inconclusive', hint: 'too little evidence, or it is balanced' },
  { value: 3, label: 'Corroborated', hint: 'supported, with little conflict' },
]

export const DEPARTURE_QUESTION =
  'Does your judgment go beyond or against what these passages show?'

export const DEPARTURE_OPTIONS: LabelOption<'yes' | 'no'>[] = [
  { value: 'yes', label: 'Yes', hint: 'I relied on something the passages do not contain' },
  { value: 'no', label: 'No', hint: 'the passages alone lead me to the same judgment' },
]

export function corpusName(corpus: string | null | undefined): string {
  if (corpus === 'deb') return 'DEB literature'
  if (corpus === 'reproduction') return 'Reproduction abstracts'
  return corpus || ''
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
  if (!spec.field) return 'This task is not answered with a single option'
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
