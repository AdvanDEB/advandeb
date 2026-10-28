// GENERATED from app/backend/app/models/enrolment.py by
// app/backend/scripts/gen_elicitation_types.py — do not edit by hand.
// Regenerate after changing a model; the backend suite fails while
// this file is stale (tests/test_elicitation_contract.py).
/* eslint-disable */

export type Tier = "panel" | "contributor"
export type RequestStatus = "pending" | "approved" | "declined"

// ---- responses: every field is present ----

/** The public endpoint's only answer — the same whether or not the email is already known, so it cannot be used to enumerate who is enrolled. */
export interface EnrolmentSubmitted {
  status: "pending"
}

/** A stored request, as an administrator sees it. */
export interface EnrolmentRequestRecord {
  id: string
  name: string
  email: string
  affiliation: string | null
  orcid: string | null
  years_in_field: number | null
  deb_experience: string | null
  category_familiarity: Record<string, number>
  consent: boolean
  status: RequestStatus
  created_at: string
  decided_at: string | null
  decided_by: string | null
  assigned_tier: Tier | null
  matched_authored_sf_numbers: number[]
  matched_author_slugs: string[]
  user_id: string | null
  note: string | null
}

export interface EnrolmentRequestList {
  requests: EnrolmentRequestRecord[]
}

/** What a decision returns to the administrator. */
export interface EnrolmentDecisionResult {
  status: "approved" | "declined"
  tier: Tier | null
  user_id: string | null
  matched_authored_sf_numbers: number[]
  author_slugs: string[]
  temp_password: string | null
}

/** One category of the collection, as offered for self-rating. */
export interface StylizedFactCategory {
  key: string
  label: string
  n_facts: number
  currently_assessed: boolean
}

export interface CategoryList {
  categories: StylizedFactCategory[]
}

// ---- requests: fields with a server default may be omitted ----

/** What a prospective participant submits. Public endpoint. */
export interface EnrolmentRequest {
  name: string
  email: string
  affiliation?: string | null
  orcid?: string | null
  years_in_field?: number | null
  deb_experience?: string | null
  category_familiarity?: Record<string, number>
  consent?: boolean
}

/** An administrator's ruling on one request. */
export interface EnrolmentDecision {
  approve: boolean
  tier?: Tier | null
  note?: string | null
}
