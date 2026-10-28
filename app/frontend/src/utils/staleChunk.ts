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
 * At most one automatic reload per destination within GUARD_MS, forgotten
 * once a navigation there succeeds; past that, or when the browser is offline
 * (a reload would only swap the app for the browser's error page), the user is
 * told what happened and offered the reload instead.
 *
 * The guard is per destination, not "time since the last reload": a reload
 * that took longer than the window to reach the failing import (a slow phone
 * link) passed a 10 s time check every time, and the tab reloaded forever.
 */
import { useDialogStore } from '@/stores/dialog'

export const RELOAD_KEY = 'advandeb.staleChunkReloads'
/** How long an automatic reload to a destination is remembered. */
export const GUARD_MS = 5 * 60_000

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

type Reloads = Record<string, number>

function readReloads(now: number): Reloads {
  const raw = JSON.parse(sessionStorage.getItem(RELOAD_KEY) || '{}') as unknown
  const out: Reloads = {}
  if (raw && typeof raw === 'object') {
    for (const [href, at] of Object.entries(raw)) {
      if (typeof at === 'number' && now - at < GUARD_MS) out[href] = at
    }
  }
  return out
}

/**
 * True when an automatic reload to ``href`` is allowed, and records it. False
 * when this tab already auto-reloaded to ``href`` within GUARD_MS (the reload
 * did not help), or nothing can be recorded (without the record the guard
 * could not stop a loop).
 */
export function claimAutoReload(href: string, now = Date.now()): boolean {
  try {
    const reloads = readReloads(now)
    if (href in reloads) return false
    reloads[href] = now
    sessionStorage.setItem(RELOAD_KEY, JSON.stringify(reloads))
    return true
  } catch {
    return false
  }
}

/** A navigation to ``href`` worked: a later stale chunk there may reload again. */
export function forgetAutoReload(href: string): void {
  try {
    const raw = sessionStorage.getItem(RELOAD_KEY)
    if (!raw) return
    const reloads = readReloads(Date.now())
    delete reloads[href]
    sessionStorage.setItem(RELOAD_KEY, JSON.stringify(reloads))
  } catch { /* nothing recorded, nothing to forget */ }
}

/** Seam for tests: jsdom cannot navigate. */
export const browser = {
  assign: (href: string) => window.location.assign(href),
  online: () => navigator.onLine !== false,
}

/** Called by the router when a lazy route fails to load; href is where the user was going. */
export async function recoverFromChunkError(href: string): Promise<void> {
  if (browser.online() && claimAutoReload(href)) {
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
