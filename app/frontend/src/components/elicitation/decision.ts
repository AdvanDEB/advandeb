/**
 * The evidence-task draft, its validation, and the decision payload for any
 * task — pure functions, so what the client sends is testable rather than
 * assembled inline in a component.
 *
 * The payload type is generated from the server's pydantic model. The
 * previous inline payload sent no corpus, no evidence-set hash, no scores and
 * no passage judgments for an evidence item, and the server refused every one.
 */
import type {
  ElicitationDecision, EvidentialRole, PassageDirection, PassageJudgment,
  QueueItem,
} from '@/types/elicitation.generated'
import { taskSpec, validateDecision, type DraftDecision } from './taskOptions'

export interface PassageDraft {
  direction: PassageDirection | null
  evidential_role: EvidentialRole | null
}

export interface EvidenceDraft {
  /** Keyed by the passage's canonical index, as a string — the join key
   *  against the machine panel's labels, whatever order either side saw. */
  passages: Record<string, PassageDraft>
  evidence_strength: number | null
  consensus_direction: number | null
}

export function passageKey(p: { index: number }): string {
  return String(p.index)
}

export function emptyEvidenceDraft(item: Pick<QueueItem, 'passages'> | null): EvidenceDraft {
  const passages: Record<string, PassageDraft> = {}
  for (const p of item?.passages ?? []) {
    passages[passageKey(p)] = { direction: null, evidential_role: null }
  }
  return { passages, evidence_strength: null, consensus_direction: null }
}

/** Set a passage's direction. Neutral clears the role: the role is asked only
 *  of passages that bear on the fact, and a stale role on a neutral passage
 *  would be stored as if it had been asked. */
export function withDirection(
  draft: EvidenceDraft, key: string, direction: PassageDirection,
): EvidenceDraft {
  const prev = draft.passages[key] ?? { direction: null, evidential_role: null }
  return {
    ...draft,
    passages: {
      ...draft.passages,
      [key]: {
        direction,
        evidential_role: direction === 'neutral' ? null : prev.evidential_role,
      },
    },
  }
}

export function withRole(
  draft: EvidenceDraft, key: string, role: EvidentialRole,
): EvidenceDraft {
  const prev = draft.passages[key] ?? { direction: null, evidential_role: null }
  return { ...draft, passages: { ...draft.passages, [key]: { ...prev, evidential_role: role } } }
}

export function labelledCount(item: Pick<QueueItem, 'passages'>, draft: EvidenceDraft): number {
  return item.passages.filter((p) => draft.passages[passageKey(p)]?.direction).length
}

/** 1-based positions as the expert sees them, for messages. */
function positions(item: Pick<QueueItem, 'passages'>, keys: string[]): string {
  const at = new Map(item.passages.map((p, i) => [passageKey(p), i + 1]))
  return keys.map((k) => at.get(k) ?? k).join(', ')
}

/**
 * Why an evidence draft cannot be submitted yet, or null when it can.
 *
 * Mirrors the server's checks so the expert hears about a gap before
 * submitting rather than after; the server stays authoritative.
 */
export function validateEvidence(
  item: Pick<QueueItem, 'passages'>,
  draft: EvidenceDraft,
  common: Pick<DraftDecision, 'confidence' | 'rationale'>,
): string | null {
  const n = item.passages.length
  if (!n) return 'This evidence item has no passages — reload the page'
  const unlabelled = item.passages
    .map(passageKey)
    .filter((k) => !draft.passages[k]?.direction)
  if (unlabelled.length) {
    return `Label every passage (${n - unlabelled.length} of ${n} done)`
  }
  const unroled = item.passages
    .map(passageKey)
    .filter((k) => draft.passages[k].direction !== 'neutral'
      && !draft.passages[k].evidential_role)
  if (unroled.length) {
    return `Give an evidential role for passage ${positions(item, unroled)}`
  }
  if (!draft.evidence_strength) return 'Give the evidence strength (1–3)'
  if (!draft.consensus_direction) return 'Give the consensus direction (1–3)'
  if (!common.confidence || common.confidence < 1 || common.confidence > 5) {
    return 'Set your confidence'
  }
  if (!common.rationale.trim()) return 'A short rationale is required'
  return null
}

/** The one validation entry point for the view. */
export function blockedReason(
  item: QueueItem | null, form: DraftDecision, evidence: EvidenceDraft,
): string | null {
  if (!item) return 'No item'
  if (item.task === 'evidence') return validateEvidence(item, evidence, form)
  return validateDecision(item.task, form)
}

/**
 * The decision payload for whatever item was served.
 *
 * Carries the item's own identifiers back unchanged — `corpus_id`,
 * `evidence_set_id`, `evidence_content_hash`, `statement_sha256` — because
 * those are what make the judgment attributable to the exact evidence and
 * statement text it was made on. `evidence_condition` is not sent: the server
 * decides it from the task.
 */
export function buildDecision(
  item: QueueItem,
  form: DraftDecision,
  evidence: EvidenceDraft,
  extras: { time_spent_s: number; machine_verdict_expanded: boolean },
): ElicitationDecision {
  const base: ElicitationDecision = {
    task: item.task,
    sf_number: item.sf_number,
    statement_sha256: item.statement_sha256,
    confidence: form.confidence,
    rationale: form.rationale.trim(),
    time_spent_s: extras.time_spent_s,
    machine_verdict_expanded: extras.machine_verdict_expanded,
  }
  if (item.task === 'evidence') {
    const passage_judgments: Record<string, PassageJudgment> = {}
    for (const p of item.passages) {
      const d = evidence.passages[passageKey(p)]
      if (!d?.direction) continue
      passage_judgments[passageKey(p)] = {
        direction: d.direction,
        evidential_role: d.direction === 'neutral' ? null : d.evidential_role,
      }
    }
    return {
      ...base,
      corpus_id: item.corpus_id,
      evidence_set_id: item.evidence_set_id,
      evidence_content_hash: item.evidence_content_hash,
      evidence_strength: evidence.evidence_strength,
      consensus_direction: evidence.consensus_direction,
      passage_judgments,
    }
  }
  const spec = taskSpec(item.task)
  const text = form.text.trim() || null
  return {
    ...base,
    ...(spec.field ? { [spec.field]: form.choice } : {}),
    ...(spec.textField ? { [spec.textField]: text } : {}),
  }
}
