// GENERATED from app/backend/app/models/elicitation.py by
// app/backend/scripts/gen_elicitation_types.py — do not edit by hand.
// Regenerate after changing a model; the backend suite fails while
// this file is stale (tests/test_elicitation_contract.py).
/* eslint-disable */

export type TaskType = "provenance" | "scope" | "assessability" | "evidence"
export type PassageDirection = "supports" | "contradicts" | "neutral"
export type EvidentialRole = "primary_evidence" | "restatement" | "derivation" | "review"
export type ProvenanceType = "published" | "new" | "adapted" | "unknown"
export type ScopeVerdict = "stated" | "implicit" | "absent" | "not_applicable"
export type AssessabilityVerdict = "assessable" | "too_vague" | "compound" | "not_empirical" | "unclear_terms"
export type EvidenceCondition = "matched" | "expertise"
export type ElicitationEventType = "machine_verdict_opened" | "machine_verdict_closed"
export type GuidelineSection = "provenance" | "scope" | "assessability" | "evidence" | "evidence_role" | "evidence_strength" | "consensus_direction"

// ---- responses: every field is present ----

/** One frozen passage, as shown to an expert. */
export interface EvidencePassage {
  index: number
  text: string
  similarity: number
  doi: string | null
  title: string | null
  year: unknown
  document_id: string | null
}

/** One unit of work, as handed to an expert. */
export interface QueueItem {
  queue_position: number
  task: TaskType
  sf_number: number
  statement: string
  statement_sha256: string
  category: string
  collection_version: string
  existing_provenance: ProvenanceType | null
  existing_source_citation: string | null
  legacy_assessment: Record<string, unknown> | null
  repeated_judgment: boolean
  n_required: number
  comparison_item: boolean
  stratum: string
  corpus_id: string | null
  evidence_set_id: string | null
  evidence_content_hash: string | null
  passages: EvidencePassage[]
  n_passages_total: number | null
  evidence_condition: EvidenceCondition
}

/** What /decide returns when a decision is recorded. */
export interface DecisionReceipt {
  status: "recorded"
  id: string
  round: "primary" | "secondary" | "adjudication"
}

export interface EventReceipt {
  status: "logged"
}

/** Where the effort has actually gone — per expert and overall. */
export interface ElicitationProgress {
  calibration_required: boolean
  calibration_completed: number
  calibration_total: number
  total_queue: number
  completed: number
  completed_by_me: number
  median_seconds_per_item: number | null
  by_task: Record<string, number>
  by_stratum: Record<string, number>
  repeated_judgments: number
  ladder_count: number
  ladder_basis: string
  rung: string
  rung_note: string
  next_rung_at: number | null
}

/** One selectable answer for a task, with the hint shown beside it. */
export interface TaskOption {
  value: string
  label: string
  hint: string
}

export interface TaskGuideline {
  task: GuidelineSection
  title: string
  help: string
  options: TaskOption[]
}

/** Served rather than duplicated in the client. */
export interface Guidelines {
  tasks: TaskGuideline[]
  version: string
}

/** One of the expert's own past judgments. */
export interface HistoryItem {
  sf_number: number
  statement: string
  task: TaskType
  provenance_type: ProvenanceType | null
  source_citation: string | null
  scope_verdict: ScopeVerdict | null
  proposed_scope: string | null
  assessability: AssessabilityVerdict | null
  corpus_id: string | null
  evidence_strength: number | null
  consensus_direction: number | null
  confidence: number
  rationale: string
  time_spent_s: number | null
  tier: string | null
  created_at: string
}

export interface HistoryResponse {
  items: HistoryItem[]
}

/** A calibration case, shaped like a queue item so the UI can reuse it. */
export interface CalibrationItem {
  calibration_id: string
  queue_position: number
  task: TaskType
  sf_number: number
  statement: string
  statement_sha256: string
  category: string
  collection_version: string
  existing_provenance: ProvenanceType | null
  existing_source_citation: string | null
  legacy_assessment: Record<string, unknown> | null
  repeated_judgment: boolean
  n_required: number
  comparison_item: boolean
  stratum: string
  completed: number
  total: number
}

/** Immediate feedback — calibration teaches, so it does not withhold. */
export interface CalibrationFeedback {
  correct: boolean
  reference: Record<string, string | null>
  explanation: string
  completed: number
  total: number
}

/** How far through the calibration set an expert is. */
export interface CalibrationStatus {
  total: number
  completed: number
  correct: number
  done: boolean
  available: boolean
}

// ---- requests: fields with a server default may be omitted ----

/** An expert's two labels for one passage. */
export interface PassageJudgment {
  direction: PassageDirection
  evidential_role?: EvidentialRole | null
}

/** What an expert submits. One per (task, fact, expert). */
export interface ElicitationDecision {
  task: TaskType
  sf_number: number
  statement_sha256: string
  provenance_type?: ProvenanceType | null
  source_citation?: string | null
  scope_verdict?: ScopeVerdict | null
  proposed_scope?: string | null
  proposed_taxon_ids?: number[]
  assessability?: AssessabilityVerdict | null
  corpus_id?: string | null
  evidence_set_id?: string | null
  evidence_content_hash?: string | null
  evidence_strength?: number | null
  consensus_direction?: number | null
  passage_judgments?: Record<string, PassageJudgment>
  confidence: number
  rationale: string
  evidence_condition?: EvidenceCondition | null
  time_spent_s?: number | null
  machine_verdict_expanded?: boolean | null
}

/** An answer to one calibration case. */
export interface CalibrationDecision {
  calibration_id: string
  task: TaskType
  provenance_type?: ProvenanceType | null
  scope_verdict?: ScopeVerdict | null
  assessability?: AssessabilityVerdict | null
  confidence: number
  rationale: string
  time_spent_s?: number | null
}

/** A client-logged interface event on one queue item. */
export interface ElicitationEvent {
  event: ElicitationEventType
  sf_number: number
  task: TaskType
  corpus_id?: string | null
  answered?: boolean
}
