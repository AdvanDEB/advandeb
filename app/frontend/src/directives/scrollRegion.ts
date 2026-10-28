/**
 * v-scroll-region="'Users'" on a table's overflow-x wrapper.
 *
 * On a phone the wide tables (users, documents, facts, LLM keys, the privacy
 * log) scroll sideways inside their card with nothing to say so: the key
 * columns were simply off-screen (F-034). While the content overflows, this
 *  - fades the edge(s) that have more content (classes scroll-more-left /
 *    scroll-more-right, styled in styles/tokens.css), and
 *  - makes the wrapper a focusable, named region ("Users table, scrolls
 *    sideways") so a keyboard user can reach it and scroll it with the arrows.
 * When nothing overflows it is left a plain element: no stray Tab stop.
 */
import type { Directive } from 'vue'

type El = HTMLElement & { __scrollRegion?: { update: () => void, observer?: ResizeObserver } }

export const vScrollRegion: Directive<El, string> = {
  mounted(el, binding) {
    const update = () => {
      const max = el.scrollWidth - el.clientWidth
      const overflowing = max > 1
      el.classList.toggle('scroll-more-left', overflowing && el.scrollLeft > 1)
      el.classList.toggle('scroll-more-right', overflowing && el.scrollLeft < max - 1)
      if (overflowing) {
        el.tabIndex = 0
        el.setAttribute('role', 'region')
        el.setAttribute('aria-label', `${binding.value} table, scrolls sideways`)
      } else {
        el.removeAttribute('tabindex')
        el.removeAttribute('role')
        el.removeAttribute('aria-label')
      }
    }
    el.addEventListener('scroll', update, { passive: true })
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(update)
    observer?.observe(el)
    if (el.firstElementChild) observer?.observe(el.firstElementChild)
    el.__scrollRegion = { update, observer }
    update()
  },
  updated(el) {
    el.__scrollRegion?.update()
  },
  unmounted(el) {
    el.__scrollRegion?.observer?.disconnect()
  },
}
