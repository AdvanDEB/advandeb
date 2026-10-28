<template>
  <teleport to="body">
    <!-- Two live regions, always in the DOM: a region inserted together with
         its first message is often not announced at all. Errors interrupt
         (assertive); everything else waits its turn (polite). -->
    <div class="toast-container">
      <div
        v-for="region in REGIONS"
        :key="region.politeness"
        class="toast-region"
        :role="region.role"
        :aria-live="region.politeness"
        aria-atomic="false"
      >
        <transition-group name="toast">
          <div
            v-for="toast in region.pick(notifs.toasts)"
            :key="toast.id"
            :class="['toast', toast.type]"
          >
            <span class="toast-icon" aria-hidden="true">{{ ICONS[toast.type] }}</span>
            <span class="toast-message">
              <span class="sr-only">{{ LABELS[toast.type] }}: </span>{{ toast.message }}
            </span>
            <button
              type="button"
              class="toast-close"
              aria-label="Dismiss notification"
              @click="notifs.remove(toast.id)"
            >✕</button>
          </div>
        </transition-group>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { useNotificationsStore, type Toast } from '@/stores/notifications'

const notifs = useNotificationsStore()

const ICONS: Record<string, string> = {
  success: '✓',
  error: '✕',
  warning: '⚠',
  info: 'ℹ',
}

const LABELS: Record<string, string> = {
  success: 'Success',
  error: 'Error',
  warning: 'Warning',
  info: 'Notice',
}

const REGIONS = [
  { politeness: 'assertive', role: 'alert', pick: (t: Toast[]) => t.filter(x => x.type === 'error') },
  { politeness: 'polite', role: 'status', pick: (t: Toast[]) => t.filter(x => x.type !== 'error') },
] as const
</script>

<style scoped>
.toast-container {
  position: fixed;
  bottom: 1.5rem;
  right: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  z-index: 9999;
  pointer-events: none;
}

.toast-region {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.toast {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.35rem 0.35rem 1rem;
  border-radius: var(--app-radius);
  font-size: 0.875rem;
  pointer-events: all;
  min-width: 240px;
  max-width: 400px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  animation: none;
}

.toast.success { background: var(--app-success-soft); color: var(--app-success-ink); border-left: 4px solid var(--app-success); }
.toast.error   { background: var(--app-danger-soft); color: #991b1b; border-left: 4px solid var(--app-danger); }
.toast.warning { background: var(--app-warning-soft); color: var(--app-warning-ink); border-left: 4px solid var(--app-warning); }
.toast.info    { background: var(--app-primary-soft-2); color: #1e40af; border-left: 4px solid var(--app-primary); }

.toast-icon { font-size: 1rem; flex-shrink: 0; }
.toast-message { flex: 1; min-width: 0; overflow-wrap: anywhere; }

/* The whole toast used to be the dismiss target, with no name and no keyboard
   path; this is a real button, sized for a thumb. */
.toast-close {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 0;
  border-radius: var(--app-radius-sm);
  color: inherit;
  opacity: 0.6;
  cursor: pointer;
  font-size: 0.8rem;
}
.toast-close:hover { opacity: 1; background: rgba(0, 0, 0, 0.06); }
.toast-close:focus-visible { opacity: 1; outline: 2px solid currentColor; outline-offset: -2px; }

@media (pointer: coarse) {
  .toast-close { width: var(--app-touch); height: var(--app-touch); }
}

@media (max-width: 480px) {
  .toast-container { left: 0.75rem; right: 0.75rem; bottom: 0.75rem; }
  .toast { min-width: 0; max-width: none; }
}

.toast-enter-active,
.toast-leave-active { transition: all 0.25s ease; }
.toast-enter-from   { opacity: 0; transform: translateX(20px); }
.toast-leave-to     { opacity: 0; transform: translateX(20px); }
</style>
