/**
 * In-app replacement for window.confirm() / window.alert().
 *
 * The native dialogs cannot be styled, block the whole tab (including the chat
 * socket's timers), are suppressed outright by some embedded browsers, and give
 * a screen reader nothing to say beyond the raw text. These are rendered by
 * components/common/AppDialogHost.vue, mounted once in App.vue.
 *
 *   if (!(await dialog.confirm({ title: 'Delete batch?', tone: 'danger' }))) return
 *
 * Requests queue: a second confirm() while one is open waits its turn rather
 * than replacing it, so no caller's promise is ever left unresolved.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type DialogTone = 'default' | 'danger'

export interface DialogOptions {
  title: string
  /** Body text. Newlines are preserved. */
  message?: string
  confirmLabel?: string
  cancelLabel?: string
  /** 'danger' styles the confirm button red and focuses Cancel first. */
  tone?: DialogTone
}

export interface DialogRequest extends Required<Omit<DialogOptions, 'message'>> {
  id: number
  kind: 'confirm' | 'alert'
  message: string
  resolve: (ok: boolean) => void
}

let nextId = 1

export const useDialogStore = defineStore('dialog', () => {
  const queue = ref<DialogRequest[]>([])
  const current = computed<DialogRequest | null>(() => queue.value[0] ?? null)

  function open(kind: DialogRequest['kind'], opts: DialogOptions): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      queue.value.push({
        id: nextId++,
        kind,
        title: opts.title,
        message: opts.message ?? '',
        confirmLabel: opts.confirmLabel ?? (kind === 'alert' ? 'OK' : 'Confirm'),
        cancelLabel: opts.cancelLabel ?? 'Cancel',
        tone: opts.tone ?? 'default',
        resolve,
      })
    })
  }

  /** Resolves true on confirm; false on cancel, Escape or a backdrop click. */
  function confirm(opts: DialogOptions): Promise<boolean> {
    return open('confirm', opts)
  }

  /** Resolves once dismissed. */
  async function alert(opts: DialogOptions): Promise<void> {
    await open('alert', opts)
  }

  /** Close the current dialog with the given answer. */
  function settle(ok: boolean) {
    const req = queue.value.shift()
    req?.resolve(ok)
  }

  return { queue, current, confirm, alert, settle }
})
