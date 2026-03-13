<template>
  <teleport to="body">
    <div class="toast-container">
      <transition-group name="toast">
        <div
          v-for="toast in notifs.toasts"
          :key="toast.id"
          :class="['toast', toast.type]"
          @click="notifs.remove(toast.id)"
        >
          <span class="toast-icon">{{ ICONS[toast.type] }}</span>
          <span class="toast-message">{{ toast.message }}</span>
        </div>
      </transition-group>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { useNotificationsStore } from '@/stores/notifications'

const notifs = useNotificationsStore()

const ICONS: Record<string, string> = {
  success: '✓',
  error: '✕',
  warning: '⚠',
  info: 'ℹ',
}
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

.toast {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
  border-radius: 6px;
  font-size: 0.875rem;
  pointer-events: all;
  cursor: pointer;
  min-width: 240px;
  max-width: 400px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  animation: none;
}

.toast.success { background: #dcfce7; color: #166534; border-left: 4px solid #16a34a; }
.toast.error   { background: #fee2e2; color: #991b1b; border-left: 4px solid #dc2626; }
.toast.warning { background: #fef9c3; color: #713f12; border-left: 4px solid #ca8a04; }
.toast.info    { background: #dbeafe; color: #1e40af; border-left: 4px solid #3b82f6; }

.toast-icon { font-size: 1rem; flex-shrink: 0; }

.toast-enter-active,
.toast-leave-active { transition: all 0.25s ease; }
.toast-enter-from   { opacity: 0; transform: translateX(20px); }
.toast-leave-to     { opacity: 0; transform: translateX(20px); }
</style>
