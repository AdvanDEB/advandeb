/**
 * The enrolment form to assistive technology, the keyboard and a thumb.
 *
 * From the live review: required fields were not exposed as required, and the
 * error and hint sat inside the <label>, so they became the control's name
 * ("Full name Please give your name.") — F-010. The familiarity scale was five
 * tab stops that ignored the arrow keys — F-011. On a phone, an error line
 * inserted on blur moved the next control between press and release and the
 * tap was lost — F-012.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'

import EnrolmentView from '@/views/EnrolmentView.vue'
import CategoryFamiliarity from '@/components/enrolment/CategoryFamiliarity.vue'
import { clearCategoryCache } from '@/components/enrolment/categories'
import type { CategoryList } from '@/types/enrolment.generated'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))

const categories: CategoryList = {
  categories: [
    { key: 'core_deb_rules', label: 'Core DEB rules', n_facts: 36, currently_assessed: true },
    { key: 'hypoxia_dissolved_oxygen', label: 'Hypoxia and dissolved oxygen', n_facts: 14, currently_assessed: true },
    { key: 'reproductive_strategy', label: 'Reproductive strategy', n_facts: 100, currently_assessed: false },
  ],
}

const REQUIRED = ['name', 'email', 'affiliation', 'years_in_field', 'deb_experience']

let wrappers: VueWrapper[] = []
beforeEach(() => {
  api.get.mockReset()
  api.post.mockReset()
  api.get.mockResolvedValue({ data: categories })
  clearCategoryCache()
})
afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  wrappers = []
})

async function mountForm(opts: { attach?: boolean } = {}) {
  const w = mount(EnrolmentView, {
    global: { stubs: { RouterLink: true } },
    ...(opts.attach ? { attachTo: document.body } : {}),
  })
  wrappers.push(w)
  await flushPromises()
  return w
}

describe('enrolment fields (F-010)', () => {
  it('exposes the required controls as required, and only those', async () => {
    const w = await mountForm()
    for (const k of REQUIRED) {
      const control = w.find(`#enrol-${k}`)
      expect(control.exists(), k).toBe(true)
      expect(control.attributes('required'), k).toBeDefined()
      expect(control.attributes('aria-required'), k).toBe('true')
      // The visible * stays decorative; the label says "required" in words.
      const label = w.find(`label[for="enrol-${k}"]`)
      expect(label.find('em[aria-hidden="true"]').text()).toBe('*')
      expect(label.find('.sr-only').text()).toBe('(required)')
    }
    const orcid = w.find('#enrol-orcid')
    expect(orcid.attributes('required')).toBeUndefined()
    expect(orcid.attributes('aria-required')).toBeUndefined()
  })

  it('names each control by its label alone: no error or hint inside a label', async () => {
    const w = await mountForm()
    await w.find('form').trigger('submit')
    await flushPromises()
    const labels = w.findAll('.field > label')
    expect(labels).toHaveLength(REQUIRED.length + 1)
    for (const label of labels) {
      const control = w.find(`#${label.attributes('for')}`)
      expect(control.exists()).toBe(true)
      expect(label.find('input, select').exists()).toBe(false)
      expect(label.find('.err, .hint').exists()).toBe(false)
    }
    expect(w.find('label[for="enrol-name"]').text()).not.toContain('Please give your name')
  })

  it('links a shown error with aria-describedby and marks the field invalid', async () => {
    const w = await mountForm()
    const name = w.find('#enrol-name')
    expect(name.attributes('aria-invalid')).toBe('false')
    expect(name.attributes('aria-describedby')).toBeUndefined()

    await name.trigger('blur')
    expect(name.attributes('aria-invalid')).toBe('true')
    expect(name.attributes('aria-describedby')).toBe('enrol-name-err')
    const err = w.find('#enrol-name-err')
    expect(err.text()).toBe('Please give your name.')
    expect(err.element.closest('label')).toBeNull()

    // Fixed, it is valid again and the message is no longer referenced.
    await name.setValue('Ines Haberle')
    expect(name.attributes('aria-invalid')).toBe('false')
    expect(name.attributes('aria-describedby')).toBeUndefined()
    expect(w.find('#enrol-name-err').text()).toBe('')
  })

  it('describes ORCID by its hint always, and by its error when malformed', async () => {
    const w = await mountForm()
    const orcid = w.find('#enrol-orcid')
    expect(orcid.attributes('aria-describedby')).toBe('enrol-orcid-hint')
    expect(w.find('#enrol-orcid-hint').text()).toContain('authored any of the facts')
    expect(w.find('#enrol-orcid-hint').element.closest('label')).toBeNull()

    await orcid.setValue('1234')
    await orcid.trigger('blur')
    expect(orcid.attributes('aria-invalid')).toBe('true')
    expect(orcid.attributes('aria-describedby')!.split(' '))
      .toEqual(['enrol-orcid-err', 'enrol-orcid-hint'])
    expect(w.find('#enrol-orcid-err').text()).toContain('0000-0002-1825-0097')
  })

  it('says what is still needed in a polite live region that is there from the start', async () => {
    const w = await mountForm()
    const status = w.find('[role="status"]')
    expect(status.exists()).toBe(true)
    expect(status.attributes('aria-live')).toBe('polite')
    expect(status.text()).toBe('')

    await w.find('#enrol-name').setValue('Ines Haberle')
    await w.find('#enrol-name').trigger('blur')
    // The same element, now with text: a region inserted along with its text
    // is not announced.
    expect(w.find('[role="status"]').element).toBe(status.element)
    expect(status.text()).toBe(
      'Still needed: your email, your affiliation, years in the field and DEB experience.')
  })

  it('moves focus to the first invalid field when sending an untouched form', async () => {
    const w = await mountForm({ attach: true })
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(document.activeElement).toBe(w.find('#enrol-name').element)
    expect(api.post).not.toHaveBeenCalled()
  })
})

describe('error line (F-012)', () => {
  it('holds each error slot in place before and after the error, so nothing below moves', async () => {
    const w = await mountForm()
    const before = new Map<string, { slot: Element, children: number }>()
    for (const k of [...REQUIRED, 'orcid']) {
      const slot = w.find(`#enrol-${k}-err`)
      expect(slot.exists(), k).toBe(true)
      expect(slot.text(), k).toBe('')
      before.set(k, { slot: slot.element, children: slot.element.parentElement!.childElementCount })
    }

    // Blur every field the way a tap elsewhere does, and show every error.
    for (const k of REQUIRED) await w.find(`#enrol-${k}`).trigger('blur')
    await w.find('#enrol-orcid').setValue('nope')
    await w.find('#enrol-orcid').trigger('blur')

    for (const [k, { slot, children }] of before) {
      const after = w.find(`#enrol-${k}-err`)
      // The same node, filled in place; no element was added to the field.
      expect(after.element, k).toBe(slot)
      expect(after.text(), k).not.toBe('')
      expect(after.element.parentElement!.childElementCount, k).toBe(children)
    }
  })

  it('leaves the familiarity chips where they were when a field above shows its error', async () => {
    const w = await mountForm()
    const chip = w.find('[data-category="core_deb_rules"]').element
    const fieldsBefore = w.findAll('.field').map((f) => f.element.childElementCount)
    await w.find('#enrol-deb_experience').trigger('blur')
    expect(w.findAll('.field').map((f) => f.element.childElementCount)).toEqual(fieldsBefore)
    // The tap that caused the blur still lands.
    await w.find('[data-category="core_deb_rules"]').trigger('click')
    expect(w.find('[data-category="core_deb_rules"]').element).toBe(chip)
    expect(chip.getAttribute('aria-pressed')).toBe('true')
  })
})

describe('familiarity scale keyboard (F-011)', () => {
  function mountScale(modelValue: Record<string, number> = {}) {
    const w: VueWrapper = mount(CategoryFamiliarity, {
      props: {
        categories: categories.categories,
        modelValue,
        'onUpdate:modelValue': (v: Record<string, number>) => w.setProps({ modelValue: v }),
      },
      attachTo: document.body,
    })
    wrappers.push(w)
    return w
  }

  const group = (w: VueWrapper, label: string) =>
    w.find(`[role="radiogroup"][aria-label="Familiarity with ${label}"]`)
  const radio = (w: VueWrapper, label: string, n: number) =>
    group(w, label).find(`[role="radio"][data-value="${n}"]`)
  const tabStops = (w: VueWrapper, label: string) =>
    group(w, label).findAll('[role="radio"]')
      .filter((r) => r.attributes('tabindex') === '0')
      .map((r) => Number(r.attributes('data-value')))
  const checked = (w: VueWrapper, label: string) =>
    group(w, label).findAll('[role="radio"][aria-checked="true"]')
      .map((r) => Number(r.attributes('data-value')))

  async function press(w: VueWrapper, label: string, n: number, key: string) {
    const el = radio(w, label, n)
    ;(el.element as HTMLElement).focus()
    await el.trigger('keydown', { key })
    await nextTick()
  }

  it('is one tab stop per scale: the checked step, or the first before any is', async () => {
    const w = mountScale({ core_deb_rules: 3 })
    await w.find('[data-category="reproductive_strategy"]').trigger('click')
    expect(tabStops(w, 'Core DEB rules')).toEqual([3])
    expect(tabStops(w, 'Reproductive strategy')).toEqual([1])
    // Each picked area adds its remove button and one step, not six stops.
    for (const row of w.findAll('.rate-row')) {
      const stops = row.findAll('button').filter((b) => b.attributes('tabindex') !== '-1')
      expect(stops).toHaveLength(2)
    }
  })

  it('keeps a stray off-scale value from taking the scale out of the tab order', () => {
    const w = mountScale({ core_deb_rules: 0 })
    expect(tabStops(w, 'Core DEB rules')).toEqual([1])
  })

  it('moves focus and the checked value with the arrow keys, wrapping at the ends', async () => {
    const w = mountScale({ core_deb_rules: 3 })
    const label = 'Core DEB rules'

    await press(w, label, 3, 'ArrowRight')
    expect(checked(w, label)).toEqual([4])
    expect(document.activeElement).toBe(radio(w, label, 4).element)
    expect(tabStops(w, label)).toEqual([4])

    await press(w, label, 4, 'ArrowDown')
    expect(checked(w, label)).toEqual([5])
    await press(w, label, 5, 'ArrowRight')
    expect(checked(w, label)).toEqual([1])
    expect(document.activeElement).toBe(radio(w, label, 1).element)

    await press(w, label, 1, 'ArrowLeft')
    expect(checked(w, label)).toEqual([5])
    expect(document.activeElement).toBe(radio(w, label, 5).element)
    await press(w, label, 5, 'ArrowUp')
    expect(checked(w, label)).toEqual([4])

    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([{ core_deb_rules: 4 }])
  })

  it('jumps to the first and last step with Home and End', async () => {
    const w = mountScale({ core_deb_rules: 3 })
    const label = 'Core DEB rules'
    await press(w, label, 3, 'End')
    expect(checked(w, label)).toEqual([5])
    expect(document.activeElement).toBe(radio(w, label, 5).element)
    await press(w, label, 5, 'Home')
    expect(checked(w, label)).toEqual([1])
    expect(document.activeElement).toBe(radio(w, label, 1).element)
  })

  it('checks the focused step with Space, and Space never clears it', async () => {
    const w = mountScale({})
    await w.find('[data-category="core_deb_rules"]').trigger('click')
    const label = 'Core DEB rules'
    expect(checked(w, label)).toEqual([])

    const first = radio(w, label, 1).element as HTMLElement
    first.focus()
    const space = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })
    first.dispatchEvent(space)
    await nextTick()
    // Cancelled, so the button's own click cannot follow and toggle it off.
    expect(space.defaultPrevented).toBe(true)
    expect(checked(w, label)).toEqual([1])

    await press(w, label, 1, ' ')
    expect(checked(w, label)).toEqual([1])
  })

  it('leaves keys with a modifier to the browser', async () => {
    const w = mountScale({ core_deb_rules: 3 })
    const el = radio(w, 'Core DEB rules', 3).element
    const back = new KeyboardEvent('keydown', { key: 'ArrowLeft', altKey: true, bubbles: true, cancelable: true })
    el.dispatchEvent(back)
    await nextTick()
    expect(back.defaultPrevented).toBe(false)
    expect(w.emitted('update:modelValue')).toBeUndefined()
  })

  it('keeps the tap contract: a tap checks, and a tap on the checked step clears it', async () => {
    const w = mountScale({ core_deb_rules: 3 })
    await radio(w, 'Core DEB rules', 2).trigger('click')
    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([{ core_deb_rules: 2 }])
    await radio(w, 'Core DEB rules', 2).trigger('click')
    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([{}])
    expect(tabStops(w, 'Core DEB rules')).toEqual([1])
  })
})
