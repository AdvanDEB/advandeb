/**
 * Recovery for a tab that outlived a deploy.
 *
 * Every build renames its hashed chunks and the server forgets the old names,
 * so a tab opened before a deploy cannot load the next lazy route: the import
 * 404s, vue-router aborts the navigation, and the click does nothing (the
 * browser caches the failed import, so every later click fails the same way).
 *
 * The fix is a full page load of the address the user was going to, which
 * fetches the new index.html and its chunks. Guarded: a chunk that is broken
 * on the server, not merely stale, would otherwise reload the page forever.
 * At most one automatic reload per GUARD_MS; past that, or when the browser is
 * offline (a reload would only swap the app for the browser's error page), the
 * user is told what happened and offered the reload instead.
 */
import { useDialogStore } from '@/stores/dialog'

export const RELOAD_KEY = 'advandeb.staleChunkReloadAt'
export const GUARD_MS = 10_000

// Chromium, Firefox, Safari, and Vite's CSS preload for a lazy chunk.
const CHUNK_ERROR = new RegExp([
  'Failed to fetch dynamically imported module',
  'error loading dynamically imported module',
  'Importing a module script failed',
  'Unable to preload CSS',
].join('|'), 'i')

export function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? '')
  return CHUNK_ERROR.test(message)
}

/**
 * True when an automatic reload is allowed now, and records that one is being
 * made. False when one was made within GUARD_MS, or nothing can be recorded
 * (without the record the guard could not stop a loop).
 */
export function claimAutoReload(now = Date.now()): boolean {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_KEY)) || 0
    if (now - last < GUARD_MS) return false
    sessionStorage.setItem(RELOAD_KEY, String(now))
    return true
  } catch {
    return false
  }
}

/** Seam for tests: jsdom cannot navigate. */
export const browser = {
  assign: (href: string) => window.location.assign(href),
  online: () => navigator.onLine !== false,
}

/** Called by the router when a lazy route fails to load; href is where the user was going. */
export async function recoverFromChunkError(href: string): Promise<void> {
  if (browser.online() && claimAutoReload()) {
    browser.assign(href)
    return
  }
  const reload = await useDialogStore().confirm({
    title: 'This page could not be loaded',
    message: browser.online()
      ? 'AdvanDEB may have been updated since this tab was opened. Reload to get the current version.'
      : 'You appear to be offline. Reload once the connection is back.',
    confirmLabel: 'Reload',
    cancelLabel: 'Not now',
  })
  if (reload) browser.assign(href)
}
