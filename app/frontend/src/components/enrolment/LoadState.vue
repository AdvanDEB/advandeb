<template>
  <!-- Loading, failed and empty are three different things, and conflating the
       last two is the bug this component exists to prevent: a fetch that 403s
       rendering as "No requests waiting." tells an administrator the queue is
       clear when it is actually unreadable. An error always says so and always
       offers a way out. -->
  <div v-if="loading" class="state" aria-live="polite">
    <span class="spinner" aria-hidden="true"></span>
    <span class="state-text">{{ loadingText }}</span>
  </div>

  <div v-else-if="error" class="state error" role="alert">
    <span class="state-text">{{ error }}</span>
    <button type="button" class="el-btn el-btn--ghost retry" @click="$emit('retry')">
      Try again
    </button>
  </div>

  <div v-else-if="empty" class="state empty">
    <span class="state-text">{{ emptyText }}</span>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  loading?: boolean
  error?: string
  empty?: boolean
  loadingText?: string
  emptyText?: string
}>(), {
  loading: false,
  error: '',
  empty: false,
  loadingText: 'Loading…',
  emptyText: 'Nothing here yet.',
})

defineEmits<{ (e: 'retry'): void }>()
</script>

<style scoped>
@import '@/styles/elicitation-tokens.css';

.state {
  display: flex; align-items: center; gap: var(--el-s3); flex-wrap: wrap;
  padding: var(--el-s4) 0;
  font-size: var(--el-fs-sm); color: var(--el-ink-3);
}
.state-text { line-height: var(--el-lh); }
.state.error { color: var(--el-danger); }
.state.empty { color: var(--el-ink-4); }

.retry { font-size: var(--el-fs-sm); font-weight: 600; padding: 0 var(--el-s3); }

.spinner {
  width: 14px; height: 14px; flex-shrink: 0;
  border: 2px solid var(--el-line-2);
  border-top-color: var(--el-ink-3);
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* The spinner is the one piece of motion here that carries meaning — reduced
   motion gets a static ring rather than a still frame that reads as broken. */
@media (prefers-reduced-motion: reduce) {
  .spinner { animation: none; border-top-color: var(--el-line-2); opacity: 0.6; }
}

@media (max-width: 720px) {
  .retry { width: 100%; }
}
</style>
