import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useDialogStore } from '@/stores/dialog'
import {
  GUARD_MS, RELOAD_KEY, browser, claimAutoReload, isChunkLoadError, recoverFromChunkError,
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
  it('allows one reload per guard window', () => {
    expect(claimAutoReload(1_000_000)).toBe(true)
    expect(claimAutoReload(1_000_000 + GUARD_MS - 1)).toBe(false)
    expect(claimAutoReload(1_000_000 + GUARD_MS)).toBe(true)
  })

  it('refuses when sessionStorage cannot record the attempt', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    expect(claimAutoReload()).toBe(false)
  })
})

describe('recoverFromChunkError', () => {
  it('loads the destination afresh the first time', async () => {
    await recoverFromChunkError('/login?redirect=%2Fkb')
    expect(browser.assign).toHaveBeenCalledWith('/login?redirect=%2Fkb')
    expect(sessionStorage.getItem(RELOAD_KEY)).not.toBeNull()
  })

  it('asks instead of reloading again when the reload did not help', async () => {
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
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
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
    const dialog = useDialogStore()
    const done = recoverFromChunkError('/login')
    await Promise.resolve()
    dialog.settle(false)
    await done
    expect(browser.assign).not.toHaveBeenCalled()
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
