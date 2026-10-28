<template>
  <!-- Says the new page's title when there is no heading to move focus to. -->
  <div class="sr-only" aria-live="polite" aria-atomic="true">{{ announcement }}</div>
</template>

<script setup lang="ts">
/**
 * Focus after a client-side navigation. The browser does nothing on a
 * pushState navigation, so focus stayed on the link that was clicked, or fell
 * to <body> when that link went away with the old view, and a screen reader
 * said nothing at all (WCAG 2.4.3 / 4.1.3).
 *
 * After each navigation to a different path, focus moves to the new view's
 * <h1>, or to <main id="main-content"> when the view has none; in that case
 * the page title is also announced. Not on the first load (the browser has
 * just announced the document) and not when only the query or hash changed
 * (filters, tabs), which would yank focus out of the control being used.
 */
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { START_LOCATION, useRouter } from 'vue-router'

const router = useRouter()
const announcement = ref('')

const stop = router.afterEach(async (to, from, failure) => {
  if (failure || from === START_LOCATION || to.path === from.path) return
  await nextTick()

  const heading = document.querySelector<HTMLElement>('h1')
  const target = heading ?? document.getElementById('main-content')
  if (heading && !heading.hasAttribute('tabindex')) {
    // Focusable from script only; data-route-focus drops the ring (tokens.css),
    // since a heading is not a control.
    heading.setAttribute('tabindex', '-1')
    heading.setAttribute('data-route-focus', '')
  }
  target?.focus({ preventScroll: true })

  announcement.value = ''
  if (!heading) {
    await nextTick()
    announcement.value = document.title
  }
})

onBeforeUnmount(stop)
</script>
