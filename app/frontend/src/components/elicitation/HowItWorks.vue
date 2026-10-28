<template>
  <section class="el-card how" aria-labelledby="how-head" data-test="how-it-works">
    <header class="how-head">
      <h2 id="how-head">How this works</h2>
      <button type="button" class="el-btn el-btn--ghost" @click="emit('close')">
        {{ closeLabel }}
      </button>
    </header>
    <ol class="steps">
      <li v-for="(s, i) in steps" :key="i">{{ s }}</li>
    </ol>
    <p v-if="version" class="version">Guidelines v{{ version }}</p>
  </section>
</template>

<script setup lang="ts">
// The text is served with the guidelines and versioned with them: it is part
// of the instrument, so a wording change is recorded on every judgment made
// after it, and the client never keeps a second copy that could drift.
withDefaults(defineProps<{
  steps: string[]
  version?: string | null
  closeLabel?: string
}>(), { version: null, closeLabel: 'Got it' })
const emit = defineEmits<{ (e: 'close'): void }>()
</script>

<style scoped>
.how-head { display: flex; justify-content: space-between; align-items: center; gap: var(--el-s4); }
.how-head h2 { font-size: var(--el-fs-lg); font-weight: 600; color: var(--el-ink); }
.steps { margin: var(--el-s3) 0 0; padding-left: 1.3rem; display: flex; flex-direction: column; gap: var(--el-s2); font-size: var(--el-fs-base); line-height: var(--el-lh); color: var(--el-ink-2); max-width: 72ch; }
.version { margin-top: var(--el-s3); font-size: var(--el-fs-xs); color: var(--el-ink-3); }
</style>
