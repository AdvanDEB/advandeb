/**
 * The collection's categories, for self-rated familiarity — served by the
 * backend from the stylized facts themselves, the source the queue's strata
 * are built from.
 *
 * Per-category familiarity is the operationally useful part of the expertise
 * profile (advandeb_methods/docs/10 §6): it lets reliability be reported
 * against *stated* expertise, which answers "do people who say they know this
 * area agree more?" — a question the paper asks of both strata.
 *
 * This used to be a hand-written list of the twelve backbone categories. It
 * stopped there, so nobody could rate core DEB rules, hypoxia or the
 * phytoplankton sets — facts 1201–1262, the entire evidence block experts are
 * judged on now. Fetched, the list cannot fall behind the collection again.
 */
import { ref } from 'vue'
import api from '@/utils/api'
import type { CategoryList, StylizedFactCategory } from '@/types/enrolment.generated'

export type { StylizedFactCategory }

const cache = ref<StylizedFactCategory[] | null>(null)
let inflight: Promise<StylizedFactCategory[]> | null = null

/** Load once per page; concurrent callers share one request, and a failure
 *  is not cached, so a retry asks again. */
export function loadCategories(): Promise<StylizedFactCategory[]> {
  if (cache.value) return Promise.resolve(cache.value)
  if (!inflight) {
    inflight = api.get<CategoryList>('/enrolment/categories')
      .then(({ data }) => (cache.value = data.categories))
      .finally(() => { inflight = null })
  }
  return inflight
}

/** For tests: forget what was loaded. */
export function clearCategoryCache(): void {
  cache.value = null
  inflight = null
}

/** Familiarity scale labels — 1–5, anchored so the ends mean something. */
export const FAMILIARITY_LABELS: Record<number, string> = {
  1: 'Not my area',
  2: 'Passing familiarity',
  3: 'Comfortable',
  4: 'Work in this area',
  5: 'Specialist',
}

/** The served label once categories are loaded; the slug, readable, before. */
export function prettyCategory(key: string): string {
  return cache.value?.find(c => c.key === key)?.label
    || (key || '').replace(/_/g, ' ')
}
