/**
 * The judgment draft, its validation, and the payloads built from it — pure
 * functions, so what the client sends is testable rather than assembled
 * inline in a component.
 *
 * One judgment, in one combined mode (guidelines 2.0): label every passage by
 * what it says, judge the fact from the passages AND what you know, and say
 * whether that judgment goes beyond or against the passages. A rationale is
 * required only then — or when the overall scores contradict the expert's own
 * passage labels. The same rules decide a real item and a calibration case,
 * and the server applies them again; this copy exists so the expert hears
 * about a gap before submitting rather than after.
 *
 * The payload types are generated from the server's pydantic models.
 */
import type {
  CalibrationDecision, CalibrationItem, ElicitationDecision, EvidentialRole,
  PassageDirection, PassageJudgment, QueueItem, ScoreLabelConflict,
} from '@/types/elicitation.generated'

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
  /** "Does your judgment go beyond or against what these passages show?" */
  departs: boolean | null
}

export interface JudgmentCommon {
  confidence: number
  rationale: string
}

type WithPassages = Pick<QueueItem, 'passages'>

export function passageKey(p: { index: number }): string {
  return String(p.index)
}

export function emptyEvidenceDraft(item: WithPassages | null): EvidenceDraft {
  const passages: Record<string, PassageDraft> = {}
  for (const p of item?.passages ?? []) {
    passages[passageKey(p)] = { direction: null, evidential_role: null }
  }
  return { passages, evidence_strength: null, consensus_direction: null, departs: null }
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

export function labelledCount(item: WithPassages, draft: EvidenceDraft): number {
  return item.passages.filter((p) => draft.passages[passageKey(p)]?.direction).length
}

/**
 * Where the overall scores go beyond the expert's own passage labels — the
 * same three rules the server applies. Never the machine's labels: deciding
 * when a reason is owed from the machine assessment would anchor the
 * judgment being measured.
 */
export function scoreLabelConflicts(
  item: WithPassages, draft: EvidenceDraft,
): ScoreLabelConflict[] {
  const dirs = item.passages.map((p) => draft.passages[passageKey(p)]?.direction)
  const supports = dirs.filter((d) => d === 'supports').length
  const contradicts = dirs.filter((d) => d === 'contradicts').length
  const out: ScoreLabelConflict[] = []
  if (draft.consensus_direction === 3 && !supports) out.push('corroborated_without_support')
  if (draft.consensus_direction === 1 && !contradicts) out.push('against_without_contradiction')
  if ((draft.evidence_strength ?? 0) >= 2 && !supports) out.push('strength_without_support')
  return out
}

const CONFLICT_TEXT: Record<ScoreLabelConflict, string> = {
  corroborated_without_support: 'you chose “corroborated” but marked no passage as supporting',
  against_without_contradiction: 'you chose “against” but marked no passage as contradicting',
  strength_without_support: 'you gave moderate or strong evidence but marked no passage as supporting',
}

export function conflictText(conflicts: ScoreLabelConflict[]): string {
  return conflicts.map((c) => CONFLICT_TEXT[c]).join('; ')
}

export function rationaleRequired(item: WithPassages, draft: EvidenceDraft): boolean {
  return draft.departs === true || scoreLabelConflicts(item, draft).length > 0
}

/** 1-based positions as the expert sees them, for messages. */
function positions(item: WithPassages, keys: string[]): string {
  const at = new Map(item.passages.map((p, i) => [passageKey(p), i + 1]))
  return keys.map((k) => at.get(k) ?? k).join(', ')
}

/**
 * Why a judgment cannot be submitted yet, or null when it can. In the order
 * the form asks for things, so the message names the next thing to do.
 */
export function validateEvidence(
  item: WithPassages, draft: EvidenceDraft, common: JudgmentCommon,
): string | null {
  const n = item.passages.length
  if (!n) return 'This item has no passages — reload the page'
  const unlabelled = item.passages.map(passageKey).filter((k) => !draft.passages[k]?.direction)
  if (unlabelled.length) return `Label every passage (${n - unlabelled.length} of ${n} done)`
  const unroled = item.passages
    .map(passageKey)
    .filter((k) => draft.passages[k].direction !== 'neutral' && !draft.passages[k].evidential_role)
  if (unroled.length) return `Say what kind of evidence passage ${positions(item, unroled)} is`
  if (!draft.evidence_strength) return 'Give the evidence strength'
  if (!draft.consensus_direction) return 'Say which way the evidence points'
  if (draft.departs === null) return 'Say whether your judgment goes beyond the passages'
  if (!common.confidence || common.confidence < 1 || common.confidence > 5) {
    return 'Set your confidence'
  }
  if (rationaleRequired(item, draft) && !common.rationale.trim()) {
    return draft.departs
      ? 'Add a short reason — your judgment goes beyond the passages'
      : 'Add a short reason — your scores go beyond your passage labels'
  }
  return null
}

export function blockedReason(
  item: QueueItem | null, draft: EvidenceDraft, common: JudgmentCommon,
): string | null {
  if (!item) return 'No item'
  if (item.task !== 'evidence') return 'This item is of a task that is no longer asked'
  return validateEvidence(item, draft, common)
}

function passageJudgments(item: WithPassages, draft: EvidenceDraft): Record<string, PassageJudgment> {
  const out: Record<string, PassageJudgment> = {}
  for (const p of item.passages) {
    const d = draft.passages[passageKey(p)]
    if (!d?.direction) continue
    out[passageKey(p)] = {
      direction: d.direction,
      evidential_role: d.direction === 'neutral' ? null : d.evidential_role,
    }
  }
  return out
}

/**
 * The decision payload for an evidence item.
 *
 * Carries the item's own identifiers back unchanged — `corpus_id`,
 * `evidence_set_id`, `evidence_content_hash`, `statement_sha256` — because
 * those are what make the judgment attributable to the exact evidence and
 * statement text it was made on. `evidence_condition` is not sent: the server
 * decides it from the task.
 */
export function buildDecision(
  item: QueueItem,
  draft: EvidenceDraft,
  common: JudgmentCommon,
  extras: { time_spent_s: number; reference_ids?: string[] },
): ElicitationDecision {
  return {
    task: item.task,
    sf_number: item.sf_number,
    statement_sha256: item.statement_sha256,
    corpus_id: item.corpus_id,
    evidence_set_id: item.evidence_set_id,
    evidence_content_hash: item.evidence_content_hash,
    evidence_strength: draft.evidence_strength,
    consensus_direction: draft.consensus_direction,
    passage_judgments: passageJudgments(item, draft),
    departs_from_passages: draft.departs,
    reference_ids: extras.reference_ids ?? [],
    confidence: common.confidence,
    rationale: common.rationale.trim(),
    time_spent_s: extras.time_spent_s,
  }
}

export function buildCalibrationDecision(
  item: CalibrationItem,
  draft: EvidenceDraft,
  common: JudgmentCommon,
  time_spent_s: number,
): CalibrationDecision {
  return {
    calibration_id: item.calibration_id,
    evidence_strength: draft.evidence_strength,
    consensus_direction: draft.consensus_direction,
    passage_judgments: passageJudgments(item, draft),
    departs_from_passages: draft.departs,
    confidence: common.confidence,
    rationale: common.rationale.trim(),
    time_spent_s,
  }
}
