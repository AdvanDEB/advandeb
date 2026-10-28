<template>
  <teleport to="body">
    <Transition name="dialog">
      <div
        v-if="req"
        :key="req.id"
        class="dialog-backdrop"
        @mousedown.self="dismiss"
      >
        <div
          ref="panel"
          class="dialog-panel"
          :role="req.kind === 'confirm' ? 'alertdialog' : 'dialog'"
          aria-modal="true"
          :aria-labelledby="`dlg-title-${req.id}`"
          :aria-describedby="req.message ? `dlg-msg-${req.id}` : undefined"
          @keydown="onKeydown"
        >
          <h2 :id="`dlg-title-${req.id}`" class="dialog-title">{{ req.title }}</h2>
          <p v-if="req.message" :id="`dlg-msg-${req.id}`" class="dialog-message">{{ req.message }}</p>
          <div class="dialog-actions">
            <button
              v-if="req.kind === 'confirm'"
              ref="cancelBtn"
              type="button"
              class="dialog-btn ghost"
              @click="dialog.settle(false)"
            >{{ req.cancelLabel }}</button>
            <button
              ref="confirmBtn"
              type="button"
              :class="['dialog-btn', req.tone === 'danger' ? 'danger' : 'primary']"
              @click="dialog.settle(true)"
            >{{ req.confirmLabel }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useDialogStore } from '@/stores/dialog'

const dialog = useDialogStore()
const req = computed(() => dialog.current)

const panel = ref<HTMLElement | null>(null)
const cancelBtn = ref<HTMLButtonElement | null>(null)
const confirmBtn = ref<HTMLButtonElement | null>(null)

// Where focus was before the dialog opened; it goes back there on close so a
// keyboard user is not dropped at the top of the page.
let returnFocus: HTMLElement | null = null

watch(() => req.value?.id, async (id, prevId) => {
  if (id && !prevId) {
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  }
  if (id) {
    await nextTick()
    // The least destructive choice gets focus: Cancel when the action is
    // dangerous, so a reflexive Enter does not delete anything.
    const target = req.value?.tone === 'danger' && cancelBtn.value ? cancelBtn.value : confirmBtn.value
    target?.focus()
  } else if (prevId) {
    const el = returnFocus
    returnFocus = null
    if (el && document.contains(el)) el.focus()
  }
})

function dismiss() {
  dialog.settle(false)
}

function onKeydown(e: KeyboardEvent) {
  // Page-level shortcuts (the KB review keys, the elicitation keys) listen on
  // window; a keystroke meant for the dialog must not also act behind it.
  e.stopPropagation()
  if (e.key === 'Escape') {
    e.preventDefault()
    dismiss()
    return
  }
  if (e.key !== 'Tab' || !panel.value) return
  // Keep Tab inside the dialog: aria-modal tells assistive tech the rest of
  // the page is inert, so focus must not wander there either.
  const focusables = Array.from(panel.value.querySelectorAll<HTMLElement>('button:not([disabled])'))
  if (!focusables.length) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}
</script>

<style scoped>
.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 10001;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: rgba(17, 24, 39, 0.45);
}

.dialog-panel {
  width: 100%;
  max-width: 28rem;
  max-height: calc(100dvh - 2rem);
  overflow-y: auto;
  background: var(--app-bg);
  border-radius: var(--app-radius-xl);
  box-shadow: var(--app-shadow-pop);
  padding: 1.25rem 1.5rem;
}

.dialog-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--app-ink);
  margin-bottom: 0.5rem;
}

.dialog-message {
  font-size: 0.9rem;
  line-height: 1.5;
  color: var(--app-ink-2);
  white-space: pre-line;
  overflow-wrap: anywhere;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 1.25rem;
}

.dialog-btn {
  min-height: var(--app-touch);
  min-width: 6rem;
  padding: 0 1rem;
  border-radius: var(--app-radius);
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
}
.dialog-btn:focus-visible { outline: var(--app-focus); outline-offset: 2px; }
.dialog-btn.ghost { background: var(--app-bg); border-color: var(--app-line-2); color: var(--app-ink-2); }
.dialog-btn.ghost:hover { background: var(--app-bg-3); }
.dialog-btn.primary { background: var(--app-primary-strong); color: #fff; }
.dialog-btn.primary:hover { background: var(--app-primary-ink); }
.dialog-btn.danger { background: var(--app-danger); color: #fff; }
.dialog-btn.danger:hover { background: var(--app-danger-strong); }

.dialog-enter-active, .dialog-leave-active { transition: opacity 0.15s ease; }
.dialog-enter-from, .dialog-leave-to { opacity: 0; }

@media (max-width: 480px) {
  .dialog-backdrop { align-items: flex-end; padding: 0; }
  .dialog-panel { max-width: none; border-radius: var(--app-radius-xl) var(--app-radius-xl) 0 0; }
  .dialog-actions { flex-direction: column-reverse; }
  .dialog-btn { width: 100%; }
}
</style>
