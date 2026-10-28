/**
 * The signup payload, built from the form in one place and typed by the
 * generated `EnrolmentRequest` — so the next renamed field fails `vue-tsc`
 * instead of every signup. The form used to post `full_name` and
 * `consent_acknowledgement` to a model that requires `name` and `consent`.
 */
import type { EnrolmentRequest } from '@/types/enrolment.generated'

export interface EnrolmentForm {
  name: string
  email: string
  affiliation: string
  orcid: string
  years_in_field: number | null
  deb_experience: string
  category_familiarity: Record<string, number>
  consent: boolean
}

export function emptyEnrolmentForm(): EnrolmentForm {
  return {
    name: '', email: '', affiliation: '', orcid: '', years_in_field: null,
    deb_experience: '', category_familiarity: {}, consent: false,
  }
}

/**
 * @param categoryKeys the categories the collection offers (from
 *   loadCategories); a rating for anything else is not sent, since the server
 *   refuses a category it does not hold.
 */
export function enrolmentPayload(
  form: EnrolmentForm, categoryKeys: readonly string[],
): EnrolmentRequest {
  // Only categories actually rated: a picked-but-unrated area is not a claim
  // of expertise.
  const rated: Record<string, number> = {}
  for (const key of categoryKeys) {
    const v = form.category_familiarity[key]
    if (typeof v === 'number' && v > 0) rated[key] = v
  }
  const opt = (s: string) => s.trim() || null
  return {
    name: form.name.trim(),
    email: form.email.trim(),
    affiliation: opt(form.affiliation),
    orcid: opt(form.orcid),
    years_in_field: form.years_in_field,
    deb_experience: opt(form.deb_experience),
    category_familiarity: rated,
    consent: form.consent,
  }
}
