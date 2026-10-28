/**
 * Enrolment against the generated contract.
 *
 * Signup posted `full_name` / `consent_acknowledgement` where the server
 * requires `name` / `consent` — every request a 422. The admin view posted
 * `{decision: 'approve'}` where the server requires `{approve: true}`, read
 * request ids from a field the list did not serve, discarded the one-time
 * password of every new account, and read dashboard fields the server never
 * sent. Fixtures here are typed with the generated types, so the next drift
 * fails to compile before it fails a user.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import { emptyEnrolmentForm, enrolmentPayload } from '@/components/enrolment/request'
import { clearCategoryCache } from '@/components/enrolment/categories'
import type {
  AdminStats, CalibrationStatus, ExpertList,
} from '@/types/elicitation.generated'
import type {
  CategoryList, EnrolmentDecisionResult, EnrolmentRequestList,
  EnrolmentRequestRecord,
} from '@/types/enrolment.generated'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))

beforeEach(() => {
  api.get.mockReset()
  api.post.mockReset()
  clearCategoryCache()
})

// As /enrolment/categories serves them: the evidence block first.
const categories: CategoryList = {
  categories: [
    { key: 'core_deb_rules', label: 'Core DEB rules', n_facts: 36, currently_assessed: true },
    { key: 'hypoxia_dissolved_oxygen', label: 'Hypoxia and dissolved oxygen', n_facts: 14, currently_assessed: true },
    { key: 'phytoplankton_chlorophyll', label: 'Phytoplankton chlorophyll', n_facts: 5, currently_assessed: true },
    { key: 'phytoplankton_eps', label: 'Phytoplankton EPS', n_facts: 3, currently_assessed: true },
    { key: 'phytoplankton_nc_ratio', label: 'Phytoplankton N:C ratio', n_facts: 4, currently_assessed: true },
    { key: 'reproductive_strategy', label: 'Reproductive strategy', n_facts: 100, currently_assessed: false },
    { key: 'toxicology_and_ecotoxicology', label: 'Toxicology and ecotoxicology', n_facts: 100, currently_assessed: false },
  ],
}
const categoryKeys = categories.categories.map((c) => c.key)

describe('signup payload', () => {
  it('sends the fields EnrolmentRequest requires — name and consent', () => {
    const form = {
      ...emptyEnrolmentForm(),
      name: ' Tin Klanjšček ', email: 'tin@irb.hr ', affiliation: 'IRB',
      years_in_field: 20, deb_experience: 'developer', consent: true,
      category_familiarity: { reproductive_strategy: 5, toxicology_and_ecotoxicology: 0 },
    }
    expect(enrolmentPayload(form, categoryKeys)).toEqual({
      name: 'Tin Klanjšček', email: 'tin@irb.hr', affiliation: 'IRB',
      orcid: null, years_in_field: 20, deb_experience: 'developer',
      // a picked-but-unrated area is not a claim of expertise
      category_familiarity: { reproductive_strategy: 5 },
      consent: true,
    })
  })

  it('drops a rating for a category the collection does not offer', () => {
    const form = { ...emptyEnrolmentForm(), name: 'n', email: 'e@x.org',
      category_familiarity: { core_deb_rules: 4, gone_category: 5 } }
    expect(enrolmentPayload(form, categoryKeys).category_familiarity)
      .toEqual({ core_deb_rules: 4 })
  })

  it('posts that payload from the form', async () => {
    api.get.mockResolvedValue({ data: categories })
    api.post.mockResolvedValue({ data: { status: 'pending' } })
    const { default: EnrolmentView } = await import('@/views/EnrolmentView.vue')
    const w = mount(EnrolmentView, { global: { stubs: { RouterLink: true } } })
    const inputs = w.findAll('input')
    await w.find('input[autocomplete="name"]').setValue('Ines Haberle')
    await w.find('input[type="email"], input[autocomplete="email"]').setValue('ines@irb.hr')
    await w.find('input[autocomplete="organization"]').setValue('IRB')
    await w.find('input[type="number"]').setValue('12')
    await w.find('select').setValue('applied')
    await w.find('input[type="checkbox"]').setValue(true)
    await flushPromises()
    // Rate one evidence-block area: pick it, then give it a 4.
    await w.find('[data-category="core_deb_rules"]').trigger('click')
    await w.findAll('.rate-row .step')[3].trigger('click')
    expect(inputs.length).toBeGreaterThan(3)
    await w.find('form').trigger('submit')
    await flushPromises()

    expect(api.post).toHaveBeenCalledTimes(1)
    const [url, body] = api.post.mock.calls[0]
    expect(url).toBe('/enrolment/request')
    expect(body).toMatchObject({
      name: 'Ines Haberle', email: 'ines@irb.hr', consent: true,
      deb_experience: 'applied', years_in_field: 12,
      category_familiarity: { core_deb_rules: 4 },
    })
    expect(body).not.toHaveProperty('full_name')
    expect(body).not.toHaveProperty('consent_acknowledgement')
  })
})

describe('familiarity areas', () => {
  it('offers the evidence block, from the server, ahead of the rest', async () => {
    api.get.mockResolvedValue({ data: categories })
    const { default: EnrolmentView } = await import('@/views/EnrolmentView.vue')
    const w = mount(EnrolmentView, { global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(api.get).toHaveBeenCalledWith('/enrolment/categories')
    const chips = w.findAll('[data-category]').map((c) => c.attributes('data-category'))
    expect(chips).toEqual(categoryKeys)
    expect(w.find('[data-group="assessed"]').text()).toBe('Being assessed now')
    for (const label of ['Core DEB rules', 'Hypoxia and dissolved oxygen',
      'Phytoplankton chlorophyll', 'Phytoplankton EPS', 'Phytoplankton N:C ratio']) {
      expect(w.text()).toContain(label)
    }
  })

  it('lets the request go without ratings when the areas cannot load', async () => {
    api.get.mockRejectedValue(new Error('down'))
    const { default: EnrolmentView } = await import('@/views/EnrolmentView.vue')
    const w = mount(EnrolmentView, { global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(w.text()).toContain('could not be loaded')
    api.get.mockResolvedValue({ data: categories })
    await w.find('.cat-error .retry').trigger('click')
    await flushPromises()
    expect(w.findAll('[data-category]')).toHaveLength(categoryKeys.length)
  })
})

const pending: EnrolmentRequestRecord = {
  id: 'req1', name: 'Tin Klanjšček', email: 'tin.new@example.org',
  affiliation: 'IRB', orcid: null, years_in_field: 20,
  deb_experience: 'developer', category_familiarity: { core_deb_rules: 5 },
  consent: true, status: 'pending', created_at: '2026-10-28T09:00:00Z',
  decided_at: null, decided_by: null, assigned_tier: null,
  matched_authored_sf_numbers: [1201, 1202], matched_author_slugs: ['tin_klanjscek'],
  user_id: null, note: null,
}

const cal: CalibrationStatus = { total: 15, completed: 15, correct: 12, done: true, available: true }

const stats: AdminStats = {
  total_queue: 3910, completed: 7, repeated_judgments: 2,
  median_seconds_per_item: 95, comparison_total: 214, comparison_complete: 3,
  panel_coverage: { n_required_met: 5, n_required_pending: 3905 },
  by_stratum: { 'growth|deb': 7 }, by_task: { evidence: 7 },
  by_tier: { panel: 7 }, by_record_tier: { panel: 7 },
  by_expert: [{ name: 'Jasminka', current_tier: 'panel', tier: 'panel',
    n_by_record_tier: { panel: 7 }, n: 7, median_s: 95, calibration: cal }],
  awaiting_calibration: [], ladder_count: 7,
  ladder_basis: 'panel-tier judgments on the evidence task',
  rung: 'pre-R0', rung_note: 'Below the pilot volume', next_rung_at: 60,
  expert_references: null,
}

const experts: ExpertList = {
  eligible: 1,
  users: [{ id: 'u1', name: 'Tin', roles: ['knowledge_explorator'], tier: 'panel',
    can_elicit: true, has_capability: true, n_elicitations: 4,
    author_slugs: ['tin_klanjscek'] }],
}

describe('AdminExpertsView', () => {
  function serve(requests: EnrolmentRequestRecord[] = [pending]) {
    api.get.mockImplementation((url: string, cfg?: any) => {
      if (url === '/enrolment/requests') {
        const list: EnrolmentRequestList = {
          requests: cfg?.params?.status_filter === 'pending'
            ? requests.filter((r) => r.status === 'pending') : requests,
        }
        return Promise.resolve({ data: list })
      }
      if (url === '/elicitation/experts') return Promise.resolve({ data: experts })
      if (url === '/enrolment/categories') return Promise.resolve({ data: categories })
      if (url === '/elicitation/stats/admin') return Promise.resolve({ data: stats })
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
  }

  async function mountView() {
    const { default: AdminExpertsView } = await import('@/views/AdminExpertsView.vue')
    const w = mount(AdminExpertsView)
    await flushPromises()
    return w
  }

  it('asks only for pending requests and shows the served profile', async () => {
    serve([pending, { ...pending, id: 'old', status: 'approved', name: 'Decided' }])
    const w = await mountView()
    expect(api.get).toHaveBeenCalledWith('/enrolment/requests',
      { params: { status_filter: 'pending' } })
    expect(w.text()).toContain('Tin Klanjšček')
    expect(w.text()).not.toContain('Decided')
    // consent and the conflict come from the request's own fields
    expect(w.text()).toContain('Given')
    expect(w.text()).toContain('2 authored stylized facts')
    expect(w.text()).toContain('tin_klanjscek')
    // the rated area under its served label, not its slug
    expect(w.text()).toContain('Core DEB rules')
  })

  it('posts {approve, tier, note} to the request’s id and shows the one-time password', async () => {
    serve()
    const result: EnrolmentDecisionResult = {
      status: 'approved', tier: 'contributor', user_id: 'u9',
      matched_authored_sf_numbers: [1201, 1202], author_slugs: ['tin_klanjscek'],
      temp_password: 'Xy7-one-time',
    }
    api.post.mockResolvedValue({ data: result })
    const w = await mountView()
    await w.find('.note-input').setValue('workshop speaker')
    const approve = w.findAll('button').find((b) => b.text().includes('Approve → contributor'))!
    await approve.trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/enrolment/requests/req1/decide',
      { approve: true, tier: 'contributor', note: 'workshop speaker' })
    const issued = w.find('[data-test="issued"]')
    expect(issued.exists()).toBe(true)
    expect(issued.text()).toContain('Xy7-one-time')
    expect(issued.text()).toContain('tin.new@example.org')
  })

  it('declines with approve: false and no tier', async () => {
    serve()
    api.post.mockResolvedValue({ data: { status: 'declined', tier: null, user_id: null,
      matched_authored_sf_numbers: [], author_slugs: [], temp_password: null } })
    const w = await mountView()
    await w.findAll('button').find((b) => b.text() === 'Decline')!.trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/enrolment/requests/req1/decide',
      { approve: false, tier: null, note: null })
    expect(w.find('[data-test="issued"]').exists()).toBe(false)
  })

  it('renders the dashboard from the fields the server sends', async () => {
    serve([])
    const w = await mountView()
    const text = w.text()
    expect(text).toContain('3 of 214 comparison items have their full panel')
    expect(text).toContain('3910 queue items')
    expect(text).toContain('95s')
    // by_expert is a list of rows: names, not array indices
    expect(text).toContain('Jasminka')
    expect(text).toContain('53 to go')
    // experts table: tier, count and the author link
    expect(text).toContain('panel')
    expect(text).toContain('author: tin_klanjscek')
  })
})
