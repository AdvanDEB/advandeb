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
export type GuidelineSection = "provenance" | "scope" | "assessability" | "evidence" | "evidence_role" | "evidence_strength" | "consensus_direction" | "departure"
export type ScoreLabelConflict = "corroborated_without_support" | "against_without_contradiction" | "strength_without_support"
export type CitationStatus = "resolved" | "partial" | "unresolved"
export type CalibrationSetStatus = "draft" | "published" | "retired"
export type CandidateStatus = "pending" | "accepted" | "rejected"
export type ReferenceDirection = "supports" | "opposes"
export type ResolutionStatus = "pending" | "unresolvable" | "not_in_corpus" | "in_corpus_not_retrieved" | "in_corpus_retrieved" | "in_corpus_retrieval_unknown"

// ---- responses: every field is present ----

/** Where a passage comes from, as a reader would cite it. */
export interface PassageCitation {
  status: CitationStatus
  authors: string[]
  year: number | null
  title: string | null
  journal: string | null
  doi: string | null
  pages: string | null
  file_name: string | null
  library_id: string | null
}

/** One frozen passage, as shown to an expert. */
export interface EvidencePassage {
  index: number
  text: string
  similarity: number
  doi: string | null
  title: string | null
  year: unknown
  document_id: string | null
  citation: PassageCitation
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
  calibration_version: number | null
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
  how_it_works: string[]
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
  departs_from_passages: boolean | null
  confidence: number
  rationale: string
  time_spent_s: number | null
  tier: string | null
  created_at: string
}

export interface HistoryResponse {
  items: HistoryItem[]
}

/** A calibration case, shaped like an evidence queue item so the expert works it in the same form as the real thing. */
export interface CalibrationItem {
  calibration_id: string
  version: number
  sf_number: number
  statement: string
  statement_sha256: string
  category: string
  corpus_id: string
  evidence_set_id: string
  evidence_content_hash: string | null
  passages: EvidencePassage[]
  n_passages_total: number | null
  completed: number
  total: number
}

/** Immediate feedback — calibration teaches, so it does not withhold. */
export interface CalibrationFeedback {
  correct: boolean
  strength_matches: boolean
  consensus_matches: boolean
  passages_compared: number
  passages_agreed: number
  reference: CalibrationReference
  completed: number
  total: number
}

/** Where an expert stands against the published calibration set. */
export interface CalibrationStatus {
  total: number
  completed: number
  correct: number
  done: boolean
  available: boolean
  required: boolean
  version: number | null
}

/** A stored calibration item, with what an administrator needs to recognise it. */
export interface CalibrationSetItem {
  evidence_set_id: string
  sf_number: number
  corpus_id: string
  category: string
  statement: string
  reference: CalibrationReference
}

export interface CalibrationSet {
  version: number
  status: CalibrationSetStatus
  note: string | null
  items: CalibrationSetItem[]
  created_by: string | null
  created_at: string
  published_at: string | null
  retired_at: string | null
}

export interface CalibrationSetList {
  sets: CalibrationSet[]
  published_version: number | null
}

/** An evidence set an administrator can pick for calibration. */
export interface EvidenceSetOption {
  evidence_set_id: string
  sf_number: number
  corpus_id: string
  category: string
  statement: string
  n_passages: number
  n_judgments: number
}

export interface EvidenceSetOptionList {
  sets: EvidenceSetOption[]
}

/** One evidence set with the passages an expert would be shown, so the team can enter reference labels against the passages themselves. */
export interface EvidenceSetDetail {
  evidence_set_id: string
  sf_number: number
  corpus_id: string
  category: string
  statement: string
  n_passages: number
  n_judgments: number
  passages: EvidencePassage[]
}

/** Expert-named references, by resolution status (docs/09 section 2.5a). */
export interface RecallSummary {
  by_status: Record<string, number>
  recall_misses: number
  checked_for_retrieval: number
  miss_rate: number | null
  undetermined: number
}

/** Queue positions whose `n_required` is met by panel-tier judgments. */
export interface PanelCoverage {
  n_required_met: number
  n_required_pending: number
}

export interface ExpertStats {
  name: string
  current_tier: string | null
  tier: string | null
  n_by_record_tier: Record<string, number>
  n: number
  median_s: number | null
  calibration: CalibrationStatus
}

export interface AwaitingCalibration {
  name: string | null
  tier: string | null
  calibration: CalibrationStatus
}

/** Where the effort has gone, and what the panel still owes. */
export interface AdminStats {
  total_queue: number
  completed: number
  repeated_judgments: number
  median_seconds_per_item: number | null
  comparison_total: number
  comparison_complete: number
  panel_coverage: PanelCoverage
  by_stratum: Record<string, number>
  by_task: Record<string, number>
  by_tier: Record<string, number>
  by_record_tier: Record<string, number>
  by_expert: ExpertStats[]
  awaiting_calibration: AwaitingCalibration[]
  ladder_count: number
  ladder_basis: string
  rung: string
  rung_note: string
  next_rung_at: number | null
  expert_references: RecallSummary | null
}

export interface ExpertListEntry {
  id: string
  name: string | null
  roles: string[]
  tier: string | null
  can_elicit: boolean
  has_capability: boolean
  n_elicitations: number
  author_slugs: string[]
}

export interface ExpertList {
  users: ExpertListEntry[]
  eligible: number
}

/** An expert-named paper awaiting (or past) curator review. */
export interface EvidenceCandidate {
  id: string
  sf_number: number
  statement: string
  doi: string
  direction: ReferenceDirection
  note: string | null
  tier: string | null
  resolved_title: string | null
  resolved_year: number | null
  resolution_status: ResolutionStatus | null
  status: CandidateStatus
  review_comment: string | null
  created_at: string
  reviewed_at: string | null
}

export interface EvidenceCandidateList {
  candidates: EvidenceCandidate[]
  counts: Record<string, number>
}

export interface CandidateReviewResult {
  id: string
  status: CandidateStatus
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
  departs_from_passages?: boolean | null
  reference_ids?: string[]
  confidence: number
  rationale?: string
  evidence_condition?: EvidenceCondition | null
  time_spent_s?: number | null
  machine_verdict_expanded?: boolean | null
}

/** An answer to one calibration case — the same fields as a real evidence decision. */
export interface CalibrationDecision {
  calibration_id: string
  evidence_strength?: number | null
  consensus_direction?: number | null
  passage_judgments?: Record<string, PassageJudgment>
  departs_from_passages?: boolean | null
  confidence: number
  rationale?: string
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

/** The team's agreed answer for one calibration item. */
export interface CalibrationReference {
  evidence_strength: number
  consensus_direction: number
  passage_directions?: Record<string, PassageDirection>
  explanation: string
}

/** One item of a calibration set, as an administrator enters it. */
export interface CalibrationItemSpec {
  evidence_set_id: string
  reference: CalibrationReference
}

/** A new or edited draft set. Three to five items is the intent; up to eight is accepted so a draft can hold alternatives while the team decides. */
export interface CalibrationSetDraft {
  items: CalibrationItemSpec[]
  note?: string | null
}

/** A curator's decision on one candidate. */
export interface CandidateReview {
  accept: boolean
  comment?: string | null
}
