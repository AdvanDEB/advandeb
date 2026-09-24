<template>
  <div class="familiarity">
    <div v-for="cat in SF_CATEGORIES" :key="cat.key" class="row">
      <span class="cat-label">{{ cat.label }}</span>
      <div class="scale" role="radiogroup" :aria-label="cat.label">
        <button
          v-for="n in 5"
          :key="n"
          type="button"
          role="radio"
          :aria-checked="modelValue[cat.key] === n"
          :class="['dot', { active: modelValue[cat.key] === n }]"
          :title="FAMILIARITY_LABELS[n]"
          @click="set(cat.key, n)"
        >{{ n }}</button>
      </div>
    </div>
    <p class="legend">
      <strong>1</strong> {{ FAMILIARITY_LABELS[1] }} &nbsp;·&nbsp;
      <strong>3</strong> {{ FAMILIARITY_LABELS[3] }} &nbsp;·&nbsp;
      <strong>5</strong> {{ FAMILIARITY_LABELS[5] }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { FAMILIARITY_LABELS, SF_CATEGORIES } from './categories'

const props = defineProps<{ modelValue: Record<string, number> }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: Record<string, number>): void }>()

function set(key: string, n: number) {
  // Clicking the active value clears it — an unanswered category is a real
  // answer ("I have no view"), and forcing a number would invent expertise.
  const next = { ...props.modelValue }
  if (next[key] === n) delete next[key]
  else next[key] = n
  emit('update:modelValue', next)
}
</script>

<style scoped>
.familiarity { display: flex; flex-direction: column; gap: 0.35rem; }

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.3rem 0.4rem;
  border-radius: 6px;
}
.row:hover { background: #f9fafb; }

.cat-label { font-size: 0.85rem; color: #374151; }

.scale { display: flex; gap: 0.25rem; flex-shrink: 0; }

.dot {
  width: 1.9rem;
  height: 1.9rem;
  border: 1px solid #d1d5db;
  background: #fff;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.8rem;
  color: #6b7280;
}
.dot:hover { background: #f3f4f6; }
.dot.active { background: #111827; border-color: #111827; color: #fff; font-weight: 600; }

.legend { font-size: 0.75rem; color: #9ca3af; margin-top: 0.4rem; }

@media (max-width: 640px) {
  .row { flex-direction: column; align-items: flex-start; gap: 0.3rem; }
}
</style>
