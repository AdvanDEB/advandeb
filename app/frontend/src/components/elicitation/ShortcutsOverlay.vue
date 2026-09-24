<template>
  <div class="backdrop" @click.self="emit('close')">
    <div class="sheet" role="dialog" aria-label="Keyboard shortcuts">
      <header>
        <h3>Keyboard shortcuts</h3>
        <button class="x" @click="emit('close')" aria-label="Close">×</button>
      </header>
      <dl>
        <template v-for="row in rows" :key="row[1]">
          <dt><kbd v-for="k in row[0]" :key="k">{{ k }}</kbd></dt>
          <dd>{{ row[1] }}</dd>
        </template>
      </dl>
      <p class="note">
        Shortcuts are ignored while you are typing in a text field, except
        submit.
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
const emit = defineEmits<{ (e: 'close'): void }>()

const rows: [string[], string][] = [
  [['a', 's', 'd', 'f', 'g'], 'Select the first…fifth option'],
  [['1', '–', '5'], 'Set your confidence'],
  [['r'], 'Jump to the rationale box'],
  [['e'], 'Expand the earlier automated assessment (recorded)'],
  [['h'], 'Show or hide your decision history'],
  [['?'], 'This help'],
  [['⌘/Ctrl', '⏎'], 'Submit and move to the next item'],
]
</script>

<style scoped>
.backdrop { position: fixed; inset: 0; background: rgba(17, 24, 39, 0.45); display: flex; align-items: center; justify-content: center; z-index: 50; }
.sheet { background: #fff; border-radius: 12px; padding: 1.25rem 1.5rem; max-width: 30rem; width: calc(100% - 2rem); box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2); }
header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.9rem; }
h3 { font-size: 1.05rem; font-weight: 600; color: #111827; }
.x { background: none; border: none; font-size: 1.4rem; line-height: 1; cursor: pointer; color: #9ca3af; }

dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.5rem 1rem; align-items: baseline; }
dt { display: flex; gap: 0.25rem; }
dd { font-size: 0.87rem; color: #4b5563; margin: 0; }
kbd { background: #f3f4f6; border: 1px solid #e5e7eb; border-bottom-width: 2px; border-radius: 4px; padding: 0.1rem 0.35rem; font-size: 0.75rem; color: #374151; font-family: ui-monospace, monospace; }

.note { margin-top: 1rem; font-size: 0.78rem; color: #9ca3af; line-height: 1.5; }
</style>
