// GENERATED from app/backend/app/models/expert_verdict.py by
// app/backend/scripts/gen_elicitation_types.py — do not edit by hand.
// Regenerate after changing a model; the backend suite fails while
// this file is stale (tests/test_elicitation_contract.py).
/* eslint-disable */

export type VerdictTier = "panel" | "contributor"
export type VerdictLabel = "supported" | "inconclusive" | "against"
export type WithheldReason = "open_for_you"

// ---- responses: every field is present ----

/** How many judgments gave each consensus direction. */
export interface ConsensusDistribution {
  against: number
  inconclusive: number
  supported: number
}

/** How many judgments gave each evidence strength. */
export interface StrengthDistribution {
  weak: number
  moderate: number
  strong: number
}

/** One (fact, corpus, tier) group with at least the minimum n judgments. */
export interface ExpertVerdictGroup {
  corpus_id: string
  tier: VerdictTier
  n: number
  n_experts: number
  majority_label: VerdictLabel | null
  majority_n: number
  consensus: ConsensusDistribution
  strength: StrengthDistribution
  strength_median: number | null
}

/** The verdict on one stylized fact, as this user may see it. */
export interface ExpertVerdictSummary {
  sf_number: number
  withheld: "open_for_you" | null
  groups: ExpertVerdictGroup[]
}

/** Verdicts for several facts, keyed by sf_number as a string. */
export interface ExpertVerdictBatch {
  min_n: number
  verdicts: Record<string, ExpertVerdictSummary>
}

// ---- requests: fields with a server default may be omitted ----
