/**
 * Fetching aggregated expert verdicts (/api/kb/stylized-facts/…).
 *
 * Both calls opt out of the global error toast: a verdict is an addition to
 * the page, and a failed one is shown as "—" where it would have been, not as
 * an error over a table that loaded fine.
 */
import api from '@/utils/api'
import type { ExpertVerdictBatch, ExpertVerdictSummary } from '@/types/expertVerdict.generated'

/** The server refuses more than this many numbers in one request. */
export const MAX_BATCH = 500

/** Verdicts for a page of facts in one request, keyed by sf_number. */
export async function fetchExpertVerdicts(sfNumbers: number[]): Promise<ExpertVerdictBatch> {
  const nums = [...new Set(sfNumbers.filter((n) => Number.isInteger(n)))].slice(0, MAX_BATCH)
  const { data } = await api.get<ExpertVerdictBatch>('/kb/stylized-facts/expert-verdicts', {
    params: { sf_numbers: nums.join(',') },
    skipErrorToast: true,
  })
  return data
}

/** The verdict on one fact. */
export async function fetchExpertVerdict(sfNumber: number): Promise<ExpertVerdictSummary> {
  const { data } = await api.get<ExpertVerdictSummary>(
    `/kb/stylized-facts/${sfNumber}/expert-verdict`,
    { skipErrorToast: true },
  )
  return data
}
