/**
 * The aggregated expert verdict on a stylized fact, as text.
 *
 * Pure functions over the server's `ExpertVerdictSummary`. The server already
 * applies the rules — ordinal scores never averaged, panel and contributor
 * never pooled, nothing below the minimum n, nothing for someone who may
 * still judge the fact — and these helpers keep to them: a group below the
 * minimum n yields nothing at all here either, and contributor groups are
 * only ever the headline when no panel group qualifies, labelled as such.
 */
import type {
  ExpertVerdictGroup, ExpertVerdictSummary, VerdictLabel,
} from '@/types/expertVerdict.generated'

export type { ExpertVerdictGroup, ExpertVerdictSummary }

/** Mirrors the server's default `EXPERT_VERDICT_MIN_N`; the batch response
 *  carries the value actually in force. */
export const DEFAULT_MIN_N = 3

/** The corpus the full human panel judges; its panel group leads. */
export const HEADLINE_CORPUS = 'deb'

export const WITHHELD_TEXT = 'Hidden while you may still judge this fact.'
export const ABOUT_TEXT = 'Experts judged this fact from retrieved passages and their own knowledge.'
export const CONTRIBUTORS_LABEL = 'Contributors (not panel)'

export const VERDICT_LABELS: Record<VerdictLabel, string> = {
  supported: 'Supported',
  inconclusive: 'Inconclusive',
  against: 'Against',
}
/** No single most common label: two tied for the top count. */
export const SPLIT_LABEL = 'Split'

const CORPUS_NAMES: Record<string, string> = {
  deb: 'DEB literature',
  reproduction: 'Reproduction abstracts',
}
const CORPUS_ORDER = ['deb', 'reproduction']

export function corpusName(id: string): string {
  return CORPUS_NAMES[id] ?? (id || 'Unknown corpus').replace(/_/g, ' ')
}

/** Groups that may be shown: none when withheld, none below the minimum n. */
export function qualifyingGroups(
  summary: ExpertVerdictSummary | null | undefined,
  minN: number = DEFAULT_MIN_N,
): ExpertVerdictGroup[] {
  if (!summary || summary.withheld) return []
  return (summary.groups ?? []).filter(
    (g) => (g.tier === 'panel' || g.tier === 'contributor') && g.n >= minN,
  )
}

/** 'Supported', 'Inconclusive', 'Against', or 'Split' on a tie. */
export function verdictLabel(group: ExpertVerdictGroup): string {
  return group.majority_label ? VERDICT_LABELS[group.majority_label] : SPLIT_LABEL
}

/** For styling: the label key, or 'split'. */
export function verdictKey(group: ExpertVerdictGroup): VerdictLabel | 'split' {
  return group.majority_label ?? 'split'
}

function pickFrom(groups: ExpertVerdictGroup[]): ExpertVerdictGroup | null {
  if (!groups.length) return null
  const lead = groups.find((g) => g.corpus_id === HEADLINE_CORPUS)
  if (lead) return lead
  return groups.reduce((best, g) => (g.n > best.n ? g : best))
}

export interface Headline {
  group: ExpertVerdictGroup
  /** True when no panel group qualifies and a contributor group stands in. */
  contributorsOnly: boolean
}

/** The group the compact badge shows: the panel's DEB group, else the panel
 *  group with the largest n; contributors only when no panel group qualifies. */
export function pickHeadline(
  summary: ExpertVerdictSummary | null | undefined,
  minN: number = DEFAULT_MIN_N,
): Headline | null {
  const groups = qualifyingGroups(summary, minN)
  const panel = pickFrom(groups.filter((g) => g.tier === 'panel'))
  if (panel) return { group: panel, contributorsOnly: false }
  const contrib = pickFrom(groups.filter((g) => g.tier === 'contributor'))
  return contrib ? { group: contrib, contributorsOnly: true } : null
}

/** "Supported · 4/5 panel", "Split · 4 panel", or
 *  "Contributors: supported · 3/4". Null when there is nothing to show
 *  (including a withheld verdict — the badge words that itself). */
export function badgeText(
  summary: ExpertVerdictSummary | null | undefined,
  minN: number = DEFAULT_MIN_N,
): string | null {
  const head = pickHeadline(summary, minN)
  if (!head) return null
  const { group } = head
  const label = verdictLabel(group)
  if (head.contributorsOnly) {
    return group.majority_label
      ? `Contributors: ${label.toLowerCase()} · ${group.majority_n}/${group.n}`
      : `Contributors: ${label.toLowerCase()} · ${group.n}`
  }
  return group.majority_label
    ? `${label} · ${group.majority_n}/${group.n} panel`
    : `${label} · ${group.n} panel`
}

/** "Supported — 4 of 5 panel experts" / "Against — 2 of 3 contributors";
 *  a split reads "Split — no majority among 4 panel experts". */
export function groupLine(group: ExpertVerdictGroup): string {
  const who = group.tier === 'panel' ? 'panel experts' : 'contributors'
  if (!group.majority_label) return `${SPLIT_LABEL} — no majority among ${group.n} ${who}`
  return `${verdictLabel(group)} — ${group.majority_n} of ${group.n} ${who}`
}

export interface DistPart {
  key: string
  label: string
  n: number
}

/** Consensus counts, in scale order (1 against → 3 supported). */
export function consensusParts(group: ExpertVerdictGroup): DistPart[] {
  const c = group.consensus
  return [
    { key: 'against', label: 'against', n: c.against },
    { key: 'inconclusive', label: 'inconclusive', n: c.inconclusive },
    { key: 'supported', label: 'supported', n: c.supported },
  ]
}

/** Strength counts, in scale order (1 weak → 3 strong). */
export function strengthParts(group: ExpertVerdictGroup): DistPart[] {
  const s = group.strength
  return [
    { key: 'weak', label: 'weak', n: s.weak },
    { key: 'moderate', label: 'moderate', n: s.moderate },
    { key: 'strong', label: 'strong', n: s.strong },
  ]
}

/** "0 against · 1 inconclusive · 3 supported" — the accessible form of a bar. */
export function distributionText(parts: DistPart[]): string {
  return parts.map((p) => `${p.n} ${p.label}`).join(' · ')
}

const STRENGTH_NAMES: Record<number, string> = { 1: 'weak', 2: 'moderate', 3: 'strong' }

/** The (lower) median strength as a word, or null. Never a mean. */
export function strengthMedianLabel(group: ExpertVerdictGroup): string | null {
  return group.strength_median != null ? (STRENGTH_NAMES[group.strength_median] ?? null) : null
}

export interface CorpusSection {
  corpusId: string
  name: string
  /** Panel first, then contributors; only groups that qualify. */
  groups: ExpertVerdictGroup[]
}

/** Qualifying groups by corpus — DEB, then reproduction, then any other —
 *  panel before contributors within each. */
export function corpusSections(
  summary: ExpertVerdictSummary | null | undefined,
  minN: number = DEFAULT_MIN_N,
): CorpusSection[] {
  const byCorpus = new Map<string, ExpertVerdictGroup[]>()
  for (const g of qualifyingGroups(summary, minN)) {
    const list = byCorpus.get(g.corpus_id) ?? []
    list.push(g)
    byCorpus.set(g.corpus_id, list)
  }
  const rank = (id: string) => {
    const i = CORPUS_ORDER.indexOf(id)
    return i === -1 ? CORPUS_ORDER.length : i
  }
  return [...byCorpus.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([corpusId, groups]) => ({
      corpusId,
      name: corpusName(corpusId),
      groups: [...groups].sort((a, b) => (a.tier === b.tier ? 0 : a.tier === 'panel' ? -1 : 1)),
    }))
}
