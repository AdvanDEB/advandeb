/**
 * The aggregated expert verdict next to each stylized fact: the text helpers,
 * the compact badge, the detail block, and the Facts view's one batch call.
 *
 * The rules under test come from the method, not from taste: ordinal scores
 * are reported as distributions (never averaged), panel and contributor are
 * never merged, a group below the minimum n shows nothing at all, and a fact
 * the viewer may still judge shows no numbers.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import ExpertVerdictBadge from '@/components/kb/ExpertVerdictBadge.vue'
import ExpertVerdictDetail from '@/components/kb/ExpertVerdictDetail.vue'
import {
  ABOUT_TEXT, CONTRIBUTORS_LABEL, WITHHELD_TEXT, badgeText, consensusParts,
  corpusName, corpusSections, distributionText, groupLine, pickHeadline,
  qualifyingGroups, strengthMedianLabel, strengthParts, verdictLabel,
} from '@/components/kb/expertVerdict'
import type {
  ExpertVerdictGroup, ExpertVerdictSummary,
} from '@/types/expertVerdict.generated'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))

function group(over: Partial<ExpertVerdictGroup> = {}): ExpertVerdictGroup {
  return {
    corpus_id: 'deb',
    tier: 'panel',
    n: 5,
    n_experts: 5,
    majority_label: 'supported',
    majority_n: 4,
    consensus: { against: 0, inconclusive: 1, supported: 4 },
    strength: { weak: 1, moderate: 1, strong: 3 },
    strength_median: 3,
    ...over,
  }
}

function summary(groups: ExpertVerdictGroup[], over: Partial<ExpertVerdictSummary> = {}): ExpertVerdictSummary {
  return { sf_number: 12, withheld: null, groups, ...over }
}

const contributors = group({
  tier: 'contributor', n: 4, n_experts: 4, majority_label: 'supported', majority_n: 3,
  consensus: { against: 1, inconclusive: 0, supported: 3 },
})

// --------------------------------------------------------------------------- //
// Helpers                                                                     //
// --------------------------------------------------------------------------- //

describe('expert verdict text', () => {
  it('labels consensus 3/2/1 as supported/inconclusive/against, and a tie as split', () => {
    expect(verdictLabel(group())).toBe('Supported')
    expect(verdictLabel(group({ majority_label: 'inconclusive' }))).toBe('Inconclusive')
    expect(verdictLabel(group({ majority_label: 'against' }))).toBe('Against')
    expect(verdictLabel(group({ majority_label: null }))).toBe('Split')
  })

  it('writes the badge from the panel DEB group', () => {
    expect(badgeText(summary([group()]))).toBe('Supported · 4/5 panel')
    expect(badgeText(summary([group({ majority_label: null, majority_n: 2, n: 4 })])))
      .toBe('Split · 4 panel')
  })

  it('prefers the DEB panel group, else the panel group with the largest n', () => {
    const deb = group({ n: 3, majority_n: 2 })
    const repro = group({ corpus_id: 'reproduction', n: 6, majority_label: 'against', majority_n: 5 })
    const other = group({ corpus_id: 'other', n: 4, majority_n: 4 })
    expect(pickHeadline(summary([repro, deb]))?.group).toBe(deb)
    expect(pickHeadline(summary([other, repro]))?.group).toBe(repro)
    expect(badgeText(summary([other, repro]))).toBe('Against · 5/6 panel')
  })

  it('never lets contributors stand in for a qualifying panel group', () => {
    const big = group({ ...contributors, n: 9, majority_n: 9 })
    expect(pickHeadline(summary([big, group({ n: 3, majority_n: 2 })]))).toMatchObject({
      contributorsOnly: false,
    })
  })

  it('shows contributors, muted and labelled, only when no panel group qualifies', () => {
    const s = summary([contributors, group({ n: 2, majority_n: 2 })])
    expect(pickHeadline(s)).toEqual({ group: contributors, contributorsOnly: true })
    expect(badgeText(s)).toBe('Contributors: supported · 3/4')
  })

  it('shows nothing at all below the minimum n — not "1 of 1"', () => {
    const tiny = summary([group({ n: 1, n_experts: 1, majority_n: 1 }),
      group({ tier: 'contributor', n: 2, majority_n: 2 })])
    expect(qualifyingGroups(tiny)).toEqual([])
    expect(pickHeadline(tiny)).toBeNull()
    expect(badgeText(tiny)).toBeNull()
    expect(corpusSections(tiny)).toEqual([])
    // The minimum is the server's, when it says otherwise.
    expect(badgeText(tiny, 1)).toBe('Supported · 1/1 panel')
    expect(badgeText(summary([group()]), 6)).toBeNull()
  })

  it('shows nothing for a withheld or missing summary', () => {
    const withheld = summary([group()], { withheld: 'open_for_you' })
    expect(qualifyingGroups(withheld)).toEqual([])
    expect(badgeText(withheld)).toBeNull()
    expect(badgeText(null)).toBeNull()
    expect(badgeText(undefined)).toBeNull()
  })

  it('writes group lines and distributions without averaging', () => {
    expect(groupLine(group())).toBe('Supported — 4 of 5 panel experts')
    expect(groupLine(contributors)).toBe('Supported — 3 of 4 contributors')
    expect(groupLine(group({ majority_label: null }))).toBe('Split — no majority among 5 panel experts')
    expect(distributionText(consensusParts(group()))).toBe('0 against · 1 inconclusive · 4 supported')
    expect(distributionText(strengthParts(group()))).toBe('1 weak · 1 moderate · 3 strong')
    expect(strengthMedianLabel(group())).toBe('strong')
    expect(strengthMedianLabel(group({ strength_median: 2 }))).toBe('moderate')
    expect(strengthMedianLabel(group({ strength_median: null }))).toBeNull()
  })

  it('orders sections DEB, then reproduction; panel before contributors', () => {
    const repro = group({ corpus_id: 'reproduction', n: 3, majority_n: 3 })
    const sections = corpusSections(summary([repro, contributors, group()]))
    expect(sections.map((s) => s.name)).toEqual(['DEB literature', 'Reproduction abstracts'])
    expect(sections[0].groups.map((g) => g.tier)).toEqual(['panel', 'contributor'])
    expect(corpusName('some_corpus')).toBe('some corpus')
  })
})

// --------------------------------------------------------------------------- //
// Components                                                                  //
// --------------------------------------------------------------------------- //

describe('ExpertVerdictBadge', () => {
  it('renders the compact verdict', () => {
    const w = mount(ExpertVerdictBadge, { props: { summary: summary([group()]) } })
    expect(w.text()).toBe('Supported · 4/5 panel')
    expect(w.classes()).toContain('ev-badge--supported')
  })

  it('renders contributors muted', () => {
    const w = mount(ExpertVerdictBadge, { props: { summary: summary([contributors]) } })
    expect(w.text()).toBe('Contributors: supported · 3/4')
    expect(w.classes()).toContain('ev-badge--contributors')
  })

  it('renders a dash when nothing qualifies, or nothing was loaded', () => {
    for (const s of [summary([group({ n: 2, majority_n: 2 })]), null]) {
      const w = mount(ExpertVerdictBadge, { props: { summary: s } })
      expect(w.find('[aria-hidden="true"]').text()).toBe('—')
      expect(w.text()).not.toMatch(/\d/)
    }
  })

  it('says a withheld verdict is hidden, with no numbers', () => {
    const w = mount(ExpertVerdictBadge, {
      props: { summary: summary([], { withheld: 'open_for_you' }) },
    })
    expect(w.text()).toContain('Hidden')
    expect(w.attributes('title')).toBe(WITHHELD_TEXT)
    expect(w.text()).not.toMatch(/\d/)
  })
})

describe('ExpertVerdictDetail', () => {
  it('shows every qualifying group, panel and contributors apart', () => {
    const repro = group({
      corpus_id: 'reproduction', n: 3, majority_label: 'inconclusive', majority_n: 2,
      consensus: { against: 0, inconclusive: 2, supported: 1 },
    })
    const w = mount(ExpertVerdictDetail, {
      props: { summary: summary([group(), contributors, repro, group({ tier: 'contributor', corpus_id: 'reproduction', n: 1 })]) },
    })
    const text = w.text()
    expect(text).toContain(ABOUT_TEXT)
    expect(text).toContain('DEB literature')
    expect(text).toContain('Reproduction abstracts')
    expect(text).toContain('Supported — 4 of 5 panel experts')
    expect(text).toContain(`${CONTRIBUTORS_LABEL}:`)
    expect(text).toContain('Supported — 3 of 4 contributors')
    expect(text).toContain('Inconclusive — 2 of 3 panel experts')
    // Distributions as text, not colour alone.
    expect(text).toContain('0 against · 1 inconclusive · 4 supported')
    expect(text).toContain('1 weak · 1 moderate · 3 strong · median strong')
    // The sub-minimum reproduction contributor group is absent.
    expect(w.findAll('.ev-group')).toHaveLength(3)
    expect(w.findAll('.ev-group--contributor')).toHaveLength(1)
  })

  it('says why a withheld verdict is hidden', () => {
    const w = mount(ExpertVerdictDetail, {
      props: { summary: summary([], { withheld: 'open_for_you' }) },
    })
    expect(w.text()).toContain(WITHHELD_TEXT)
    expect(w.text()).not.toContain(ABOUT_TEXT)
  })

  it('shows a dash, not small numbers, when nothing qualifies', () => {
    const w = mount(ExpertVerdictDetail, {
      props: { summary: summary([group({ n: 1, n_experts: 1, majority_n: 1 })]) },
    })
    expect(w.findAll('.ev-group')).toHaveLength(0)
    expect(w.text()).not.toContain('1 of 1')
    expect(w.text()).toContain('—')
  })
})

// --------------------------------------------------------------------------- //
// The Facts view: one batch call per page; a failure never breaks the table   //
// --------------------------------------------------------------------------- //

describe('FactsView expert verdict column', () => {
  const items = [
    { id: 'a', sf_number: 12, statement: 'Fact twelve', category: 'reproductive_strategy', status: 'published' },
    { id: 'b', sf_number: 13, statement: 'Fact thirteen', category: 'reproductive_strategy', status: 'published' },
  ]

  beforeEach(() => {
    api.get.mockReset()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  async function mountView() {
    const { default: FactsView } = await import('@/views/FactsView.vue')
    const w = mount(FactsView, { attachTo: document.body })
    await flushPromises()
    return w
  }

  it('fetches verdicts for the page in one call and shows them', async () => {
    api.get.mockImplementation((url: string) => {
      if (url.startsWith('/kb/stylized-facts/?')) return Promise.resolve({ data: { items, total: 2 } })
      if (url === '/kb/stylized-facts/expert-verdicts') {
        return Promise.resolve({
          data: {
            min_n: 3,
            verdicts: {
              12: summary([group()]),
              13: summary([], { sf_number: 13, withheld: 'open_for_you' }),
            },
          },
        })
      }
      return Promise.reject(new Error(`unexpected ${url}`))
    })
    const w = await mountView()

    const verdictCalls = api.get.mock.calls.filter(([u]) => u === '/kb/stylized-facts/expert-verdicts')
    expect(verdictCalls).toHaveLength(1)
    expect(verdictCalls[0][1]).toMatchObject({ params: { sf_numbers: '12,13' }, skipErrorToast: true })

    const cells = w.findAll('td.col-verdict')
    expect(cells[0].text()).toBe('Supported · 4/5 panel')
    expect(cells[1].text()).toContain('Hidden')

    // Expanding the row shows the detail.
    await w.findAll('button.row-toggle')[0].trigger('click')
    expect(w.find('.expanded-row').text()).toContain('Supported — 4 of 5 panel experts')
    w.unmount()
  })

  it('keeps the table when the verdict call fails', async () => {
    api.get.mockImplementation((url: string) => {
      if (url.startsWith('/kb/stylized-facts/?')) return Promise.resolve({ data: { items, total: 2 } })
      return Promise.reject(Object.assign(new Error('boom'), { response: { status: 500 } }))
    })
    const w = await mountView()
    expect(w.findAll('tr.fact-row')).toHaveLength(2)
    for (const cell of w.findAll('td.col-verdict')) {
      expect(cell.find('[aria-hidden="true"]').text()).toBe('—')
    }
    w.unmount()
  })
})
