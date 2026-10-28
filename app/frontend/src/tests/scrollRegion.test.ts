import { describe, it, expect } from 'vitest'
import { defineComponent, h, withDirectives } from 'vue'
import { mount } from '@vue/test-utils'
import { vScrollRegion } from '@/directives/scrollRegion'

/**
 * F-034: on a phone, wide tables scroll sideways inside their card with no
 * sign of it. The directive fades the edge that has more and, while the table
 * overflows, makes the wrapper a named, focusable region.
 */

function mountWrapper(scrollWidth: number, clientWidth: number) {
  const Comp = defineComponent(() => () =>
    withDirectives(h('div', { class: 'wrap' }, [h('table')]), [[vScrollRegion, 'Users']]))
  const proto = HTMLElement.prototype
  const sw = Object.getOwnPropertyDescriptor(proto, 'scrollWidth')
  const cw = Object.getOwnPropertyDescriptor(proto, 'clientWidth')
  Object.defineProperty(proto, 'scrollWidth', { configurable: true, get: () => scrollWidth })
  Object.defineProperty(proto, 'clientWidth', { configurable: true, get: () => clientWidth })
  const w = mount(Comp, { attachTo: document.body })
  const restore = () => {
    if (sw) Object.defineProperty(proto, 'scrollWidth', sw); else delete (proto as unknown as Record<string, unknown>).scrollWidth
    if (cw) Object.defineProperty(proto, 'clientWidth', cw); else delete (proto as unknown as Record<string, unknown>).clientWidth
  }
  return { w, el: w.find('.wrap').element as HTMLElement, restore }
}

describe('v-scroll-region', () => {
  it('marks an overflowing table: fade on the side with more, named focusable region', () => {
    const { w, el, restore } = mountWrapper(800, 390)
    try {
      expect(el.classList.contains('scroll-more-right')).toBe(true)
      expect(el.classList.contains('scroll-more-left')).toBe(false)
      expect(el.getAttribute('role')).toBe('region')
      expect(el.getAttribute('aria-label')).toBe('Users table, scrolls sideways')
      expect(el.tabIndex).toBe(0)

      el.scrollLeft = 410                       // scrolled to the end
      el.dispatchEvent(new Event('scroll'))
      expect(el.classList.contains('scroll-more-right')).toBe(false)
      expect(el.classList.contains('scroll-more-left')).toBe(true)
    } finally { restore(); w.unmount() }
  })

  it('leaves a table that fits alone: no fade, no extra Tab stop', () => {
    const { w, el, restore } = mountWrapper(600, 600)
    try {
      expect(el.className).toBe('wrap')
      expect(el.hasAttribute('tabindex')).toBe(false)
      expect(el.hasAttribute('role')).toBe(false)
    } finally { restore(); w.unmount() }
  })
})
