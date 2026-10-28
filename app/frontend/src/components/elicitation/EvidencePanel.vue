<template>
  <section class="card evidence">
    <header class="ev-head">
      <h3>Evidence set</h3>
      <span class="count" :class="{ complete: done === passages.length }">
        {{ done }} / {{ passages.length }} labelled
      </span>
    </header>
    <p class="note">
      The same frozen passages the model panel judged. Give each one a
      direction and, unless it is neutral, an evidential role.
      <template v-if="total && total > passages.length">
        You are shown {{ passages.length }} of the {{ total }} passages in
        this set, spread across it rather than the top {{ passages.length }}.
      </template>
    </p>

    <ol class="passages">
      <li v-for="(p, i) in passages" :key="passageKey(p)" class="passage"
          :class="dirClass(p)" :data-passage="passageKey(p)">
        <div class="p-meta">
          <span class="n">{{ i + 1 }}</span>
          <span class="src">{{ p.title || '(untitled source)' }}</span>
          <span v-if="p.year" class="year">{{ p.year }}</span>
          <a v-if="p.doi" :href="`https://doi.org/${p.doi}`" target="_blank"
             rel="noopener" class="doi">DOI</a>
        </div>
        <p class="p-text">{{ p.text }}</p>

        <fieldset class="labels" :disabled="disabled">
          <legend class="sr-only">Passage {{ i + 1 }}: direction</legend>
          <label v-for="o in DIRECTION_OPTIONS" :key="o.value" class="seg"
                 :class="{ on: value(p)?.direction === o.value, [o.value]: true }"
                 :title="o.hint">
            <input type="radio" :name="`dir-${passageKey(p)}`" :value="o.value"
                   :checked="value(p)?.direction === o.value"
                   @change="setDirection(p, o.value)" />
            {{ o.label }}
          </label>
        </fieldset>

        <fieldset v-if="needsRole(p)" class="labels roles" :disabled="disabled">
          <legend class="role-legend">Evidential role</legend>
          <label v-for="o in ROLE_OPTIONS" :key="o.value" class="seg small"
                 :class="{ on: value(p)?.evidential_role === o.value }"
                 :title="o.hint">
            <input type="radio" :name="`role-${passageKey(p)}`" :value="o.value"
                   :checked="value(p)?.evidential_role === o.value"
                   @change="setRole(p, o.value)" />
            {{ o.label }}
          </label>
        </fieldset>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type {
  EvidencePassage, EvidentialRole, PassageDirection,
} from '@/types/elicitation.generated'
import { DIRECTION_OPTIONS, ROLE_OPTIONS } from './taskOptions'
import { passageKey, withDirection, withRole, type EvidenceDraft } from './decision'

const props = defineProps<{
  passages: EvidencePassage[]
  modelValue: EvidenceDraft
  /** How many passages the set holds, when fewer are shown. */
  total?: number | null
  disabled?: boolean
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: EvidenceDraft): void }>()

const done = computed(() =>
  props.passages.filter((p) => props.modelValue.passages[passageKey(p)]?.direction).length)

function value(p: EvidencePassage) {
  return props.modelValue.passages[passageKey(p)]
}
function needsRole(p: EvidencePassage) {
  const d = value(p)?.direction
  return !!d && d !== 'neutral'
}
function dirClass(p: EvidencePassage) {
  return value(p)?.direction ? `is-${value(p)!.direction}` : 'is-open'
}
function setDirection(p: EvidencePassage, d: PassageDirection) {
  emit('update:modelValue', withDirection(props.modelValue, passageKey(p), d))
}
function setRole(p: EvidencePassage, r: EvidentialRole) {
  emit('update:modelValue', withRole(props.modelValue, passageKey(p), r))
}
</script>

<style scoped>
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 1.1rem 1.25rem; }
.ev-head { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; }
.ev-head h3 { font-size: 1rem; font-weight: 600; color: #111827; }
.count { font-size: 0.78rem; color: #b45309; white-space: nowrap; }
.count.complete { color: #047857; }
.note { font-size: 0.82rem; color: #6b7280; margin: 0.35rem 0 0.9rem; line-height: 1.5; }

.passages { list-style: none; display: flex; flex-direction: column; gap: 1rem; padding: 0; }
.passage { border-left: 3px solid #e5e7eb; padding-left: 0.8rem; }
.passage.is-supports { border-left-color: #10b981; }
.passage.is-contradicts { border-left-color: #ef4444; }
.passage.is-neutral { border-left-color: #9ca3af; }
.p-meta { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; font-size: 0.75rem; color: #6b7280; margin-bottom: 0.3rem; }
.n { background: #f3f4f6; border-radius: 4px; padding: 0 0.35rem; font-weight: 600; color: #374151; }
.src { font-weight: 500; color: #4b5563; }
.doi { color: #3b82f6; text-decoration: none; }
.doi:hover { text-decoration: underline; }
.p-text { font-size: 0.87rem; line-height: 1.6; color: #374151; }

.labels { display: flex; flex-wrap: wrap; gap: 0.35rem; margin: 0.5rem 0 0; padding: 0; border: none; align-items: center; }
.roles { margin-top: 0.35rem; }
.role-legend { font-size: 0.72rem; color: #6b7280; margin-right: 0.35rem; float: left; padding: 0; }
.seg { position: relative; display: inline-flex; align-items: center; min-height: 2rem; padding: 0.25rem 0.7rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.8rem; color: #374151; cursor: pointer; background: #fff; }
.seg.small { min-height: 1.8rem; font-size: 0.75rem; padding: 0.2rem 0.55rem; }
.seg input { position: absolute; opacity: 0; width: 1px; height: 1px; }
.seg:focus-within { outline: 2px solid #6366f1; outline-offset: 1px; }
.seg.on { background: #111827; color: #fff; border-color: #111827; }
.seg.on.supports { background: #047857; border-color: #047857; }
.seg.on.contradicts { background: #b91c1c; border-color: #b91c1c; }
.seg.on.neutral { background: #4b5563; border-color: #4b5563; }
fieldset:disabled .seg { cursor: default; opacity: 0.7; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
