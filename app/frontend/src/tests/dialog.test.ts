import { describe, it, expect } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import AppDialogHost from '@/components/common/AppDialogHost.vue'
import { useDialogStore } from '@/stores/dialog'

/**
 * The in-app replacement for window.confirm()/alert(). What matters: every
 * caller's promise resolves exactly once, Escape and the backdrop mean "no",
 * a dangerous action starts focused on Cancel, and focus comes back.
 */

function mountHost() {
  return mount(AppDialogHost, { attachTo: document.body })
}

const panel = () => document.body.querySelector<HTMLElement>('[aria-modal="true"]')
const buttons = () => Array.from(document.body.querySelectorAll<HTMLButtonElement>('.dialog-btn'))

describe('dialog store', () => {
  it('resolves true on confirm and false on cancel', async () => {
    const dialog = useDialogStore()
    const yes = dialog.confirm({ title: 'A?' })
    dialog.settle(true)
    expect(await yes).toBe(true)

    const no = dialog.confirm({ title: 'B?' })
    dialog.settle(false)
    expect(await no).toBe(false)
  })

  it('queues a second request instead of replacing the first', async () => {
    const dialog = useDialogStore()
    const first = dialog.confirm({ title: 'First' })
    const second = dialog.confirm({ title: 'Second' })
    expect(dialog.current?.title).toBe('First')

    dialog.settle(true)
    expect(await first).toBe(true)
    expect(dialog.current?.title).toBe('Second')

    dialog.settle(false)
    expect(await second).toBe(false)
    expect(dialog.current).toBeNull()
  })
})

describe('AppDialogHost', () => {
  it('renders an accessible alertdialog with title and message', async () => {
    const w = mountHost()
    const dialog = useDialogStore()
    void dialog.confirm({ title: 'Delete batch?', message: 'All jobs go too.' })
    await flushPromises()

    const el = panel()!
    expect(el.getAttribute('role')).toBe('alertdialog')
    expect(document.getElementById(el.getAttribute('aria-labelledby')!)?.textContent).toBe('Delete batch?')
    expect(document.getElementById(el.getAttribute('aria-describedby')!)?.textContent).toBe('All jobs go too.')
    w.unmount()
  })

  it('focuses Cancel first for a dangerous action, the confirm button otherwise', async () => {
    const w = mountHost()
    const dialog = useDialogStore()

    void dialog.confirm({ title: 'Delete?', tone: 'danger', confirmLabel: 'Delete' })
    await flushPromises(); await nextTick()
    expect(document.activeElement?.textContent).toBe('Cancel')
    dialog.settle(false)
    await flushPromises()

    void dialog.confirm({ title: 'Publish?', confirmLabel: 'Publish' })
    await flushPromises(); await nextTick()
    expect(document.activeElement?.textContent).toBe('Publish')
    w.unmount()
  })

  it('treats Escape as cancel', async () => {
    const w = mountHost()
    const dialog = useDialogStore()
    const answer = dialog.confirm({ title: 'Sure?' })
    await flushPromises()

    panel()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(await answer).toBe(false)
    w.unmount()
  })

  it('does not let a keystroke reach page shortcuts behind it', async () => {
    const w = mountHost()
    const dialog = useDialogStore()
    void dialog.confirm({ title: 'Sure?' })
    await flushPromises()

    const seen: string[] = []
    const listener = (e: KeyboardEvent) => seen.push(e.key)
    window.addEventListener('keydown', listener)
    panel()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
    window.removeEventListener('keydown', listener)

    expect(seen).toEqual([])
    dialog.settle(false)
    w.unmount()
  })

  it('confirms through the button and returns focus to the opener', async () => {
    const opener = document.createElement('button')
    opener.textContent = 'Open'
    document.body.appendChild(opener)
    opener.focus()

    const w = mountHost()
    const dialog = useDialogStore()
    const answer = dialog.confirm({ title: 'Go?', confirmLabel: 'Go' })
    await flushPromises(); await nextTick()

    buttons().find(b => b.textContent === 'Go')!.click()
    expect(await answer).toBe(true)
    await flushPromises(); await nextTick()
    expect(document.activeElement).toBe(opener)

    w.unmount()
    opener.remove()
  })

  it('shows a single OK button for an alert', async () => {
    const w = mountHost()
    const dialog = useDialogStore()
    const done = dialog.alert({ title: 'Saved' })
    await flushPromises()

    expect(panel()!.getAttribute('role')).toBe('dialog')
    expect(buttons().map(b => b.textContent)).toEqual(['OK'])
    buttons()[0].click()
    await expect(done).resolves.toBeUndefined()
    w.unmount()
  })
})
