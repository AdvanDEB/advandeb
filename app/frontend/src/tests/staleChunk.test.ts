import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useDialogStore } from '@/stores/dialog'
import {
  GUARD_MS, RELOAD_KEY, browser, claimAutoReload, forgetAutoReload, isChunkLoadError,
  recoverFromChunkError,
} from '@/utils/staleChunk'

/**
 * A tab opened before a deploy asks for chunks the server no longer has.
 * Before: the navigation was aborted silently and every later click failed
 * the same way. Now: one guarded full load of the destination, then a dialog.
 * tests/e2e/stale-chunk.spec.ts drives the same path through the router.
 */

beforeEach(() => {
  sessionStorage.clear()
  vi.spyOn(browser, 'assign').mockImplementation(() => {})
  vi.spyOn(browser, 'online').mockReturnValue(true)
})
afterEach(() => vi.restoreAllMocks())

describe('isChunkLoadError', () => {
  it.each([
    'Failed to fetch dynamically imported module: https://advandeb.com/assets/LoginView-abc.js',
    'error loading dynamically imported module: https://advandeb.com/assets/LoginView-abc.js',
    'Importing a module script failed.',
    'Unable to preload CSS for /assets/LoginView-abc.css',
  ])('recognises %s', msg => {
    expect(isChunkLoadError(new TypeError(msg))).toBe(true)
  })

  it('ignores other navigation errors', () => {
    expect(isChunkLoadError(new Error('Navigation cancelled'))).toBe(false)
    expect(isChunkLoadError(undefined)).toBe(false)
  })
})

describe('claimAutoReload', () => {
  const t0 = 1_000_000

  it('allows one automatic reload per destination', () => {
    expect(claimAutoReload('/login', t0)).toBe(true)
    expect(claimAutoReload('/login', t0 + 1)).toBe(false)
    expect(claimAutoReload('/kb', t0 + 1)).toBe(true)        // another destination
  })

  it('does not reset just because the reload was slow (the old 10 s window did)', () => {
    expect(claimAutoReload('/login', t0)).toBe(true)
    expect(claimAutoReload('/login', t0 + 11_000)).toBe(false)
    expect(claimAutoReload('/login', t0 + 60_000)).toBe(false)
  })

  it('forgets a destination after GUARD_MS, or once a navigation there worked', () => {
    expect(claimAutoReload('/login', t0)).toBe(true)
    expect(claimAutoReload('/login', t0 + GUARD_MS)).toBe(true)
    forgetAutoReload('/login')
    expect(claimAutoReload('/login')).toBe(true)
  })

  it('refuses when sessionStorage cannot record the attempt', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    expect(claimAutoReload('/login')).toBe(false)
  })

  it('survives a garbled record', () => {
    sessionStorage.setItem(RELOAD_KEY, '"nonsense"')
    expect(claimAutoReload('/login')).toBe(true)
  })
})

describe('recoverFromChunkError', () => {
  it('loads the destination afresh the first time', async () => {
    await recoverFromChunkError('/login?redirect=%2Fkb')
    expect(browser.assign).toHaveBeenCalledWith('/login?redirect=%2Fkb')
    expect(sessionStorage.getItem(RELOAD_KEY)).not.toBeNull()
  })

  it('asks instead of reloading again when the reload did not help', async () => {
    sessionStorage.setItem(RELOAD_KEY, JSON.stringify({ '/login': Date.now() }))
    const dialog = useDialogStore()
    const done = recoverFromChunkError('/login')
    await Promise.resolve()
    expect(browser.assign).not.toHaveBeenCalled()
    expect(dialog.current?.title).toBe('This page could not be loaded')
    expect(dialog.current?.confirmLabel).toBe('Reload')

    dialog.settle(true)
    await done
    expect(browser.assign).toHaveBeenCalledWith('/login')
  })

  it('stays put when the user declines', async () => {
    sessionStorage.setItem(RELOAD_KEY, JSON.stringify({ '/login': Date.now() }))
    const dialog = useDialogStore()
    const done = recoverFromChunkError('/login')
    await Promise.resolve()
    dialog.settle(false)
    await done
    expect(browser.assign).not.toHaveBeenCalled()
  })

  it('a broken chunk behind a slow reload ends on the dialog after one reload', async () => {
    // The Critic's case: every document load took 11 s and the chunk stayed
    // 404; the old guard reloaded four times in 40 s and never asked.
    vi.useFakeTimers({ toFake: ['Date'] })
    try {
      vi.setSystemTime(1_000_000)
      await recoverFromChunkError('/login')           // first failure: reload
      expect(browser.assign).toHaveBeenCalledTimes(1)

      vi.setSystemTime(1_000_000 + 11_000)            // the reloaded page fails again
      const dialog = useDialogStore()
      void recoverFromChunkError('/login')
      await Promise.resolve()
      expect(browser.assign).toHaveBeenCalledTimes(1)
      expect(dialog.current?.title).toBe('This page could not be loaded')
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not trade the app for the browser offline page', async () => {
    vi.mocked(browser.online).mockReturnValue(false)
    const dialog = useDialogStore()
    void recoverFromChunkError('/login')
    await Promise.resolve()
    expect(browser.assign).not.toHaveBeenCalled()
    expect(dialog.current?.message).toMatch(/offline/)
    expect(sessionStorage.getItem(RELOAD_KEY)).toBeNull()
  })
})
