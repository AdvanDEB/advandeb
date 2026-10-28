<template>
  <section class="el-card evidence" aria-labelledby="ev-head">
    <header class="ev-head">
      <h2 id="ev-head"><span class="step">1</span> Label each passage</h2>
      <span class="count" :class="{ complete: done === passages.length }" aria-live="polite">
        {{ done }} of {{ passages.length }} labelled
      </span>
    </header>
    <p class="note">
      Does the passage support the fact, contradict it, or neither? Label it
      by what the passage itself says — most are neutral. Your own knowledge
      goes into step 2.
      <template v-if="total && total > passages.length">
        You see {{ passages.length }} of the {{ total }} passages found,
        spread across them rather than only the closest matches.
      </template>
    </p>

    <ol class="passages">
      <li v-for="(p, i) in passages" :key="passageKey(p)" class="passage"
          :class="dirClass(p)" :data-passage="passageKey(p)">
        <div class="p-head">
          <span class="n" :aria-label="`Passage ${i + 1}`">{{ i + 1 }}</span>
          <cite class="cite" data-test="citation">
            <template v-if="cite(p).unresolved">
              <span class="unresolved">{{ cite(p).unresolved }}</span>
            </template>
            <template v-else>
              <span class="lead">{{ cite(p).lead }}</span>
              <span class="title">{{ cite(p).title }}</span>
              <span v-if="cite(p).venue" class="venue">{{ cite(p).venue }}</span>
            </template>
            <a v-if="cite(p).doiUrl" :href="cite(p).doiUrl!" target="_blank"
               rel="noopener" class="doi">doi:{{ cite(p).doi }}</a>
          </cite>
        </div>
        <blockquote class="p-text">{{ p.text }}</blockquote>

        <fieldset class="labels" :disabled="disabled">
          <legend class="sr-only">Passage {{ i + 1 }}: does it support the fact?</legend>
          <label v-for="o in DIRECTION_OPTIONS" :key="o.value" class="seg"
                 :class="{ on: value(p)?.direction === o.value, [o.value]: true }"
                 :title="o.hint">
            <input type="radio" :name="`dir-${uid}-${passageKey(p)}`" :value="o.value"
                   :checked="value(p)?.direction === o.value"
                   @change="setDirection(p, o.value)" />
            {{ o.label }}
          </label>
        </fieldset>

        <fieldset v-if="needsRole(p)" class="labels roles" :disabled="disabled">
          <legend class="role-legend">What kind of evidence?</legend>
          <label v-for="o in ROLE_OPTIONS" :key="o.value" class="seg small"
                 :class="{ on: value(p)?.evidential_role === o.value }"
                 :title="o.hint">
            <input type="radio" :name="`role-${uid}-${passageKey(p)}`" :value="o.value"
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
import { citationView } from './citation'
import { passageKey, withDirection, withRole, type EvidenceDraft } from './decision'

const props = defineProps<{
  passages: EvidencePassage[]
  modelValue: EvidenceDraft
  /** How many passages the set holds, when fewer are shown. */
  total?: number | null
  disabled?: boolean
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: EvidenceDraft): void }>()

// Radio names must not collide when two panels are on one page (the admin
// calibration editor shows one beside the form).
const uid = Math.random().toString(36).slice(2, 8)

const done = computed(() =>
  props.passages.filter((p) => props.modelValue.passages[passageKey(p)]?.direction).length)

const cites = computed(() => new Map(props.passages.map((p) => [passageKey(p), citationView(p.citation)])))
function cite(p: EvidencePassage) {
  return cites.value.get(passageKey(p)) ?? citationView(null)
}

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
.ev-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--el-s4); }
.ev-head h2 { font-size: var(--el-fs-lg); font-weight: 600; color: var(--el-ink); display: flex; align-items: center; gap: var(--el-s2); }
.step { display: inline-flex; align-items: center; justify-content: center; width: 1.5rem; height: 1.5rem; border-radius: 50%; background: var(--el-ink); color: #fff; font-size: var(--el-fs-sm); }
.count { font-size: var(--el-fs-sm); color: var(--el-warn-ink); white-space: nowrap; }
.count.complete { color: var(--el-ok-ink); }
.note { font-size: var(--el-fs-sm); color: var(--el-ink-3); margin: var(--el-s2) 0 var(--el-s4); line-height: var(--el-lh); max-width: 70ch; }

.passages { list-style: none; display: flex; flex-direction: column; gap: var(--el-s5); padding: 0; margin: 0; }
.passage { border-left: 3px solid var(--el-line); padding-left: var(--el-s4); }
.passage.is-supports { border-left-color: #10b981; }
.passage.is-contradicts { border-left-color: #ef4444; }
.passage.is-neutral { border-left-color: #9ca3af; }

.p-head { display: flex; align-items: flex-start; gap: var(--el-s2); margin-bottom: var(--el-s2); }
.n { flex-shrink: 0; background: var(--el-bg-3); border-radius: var(--el-radius-sm); padding: 0 0.4rem; font-weight: 600; font-size: var(--el-fs-sm); color: var(--el-ink-2); }
.cite { font-style: normal; font-size: var(--el-fs-sm); color: var(--el-ink-2); line-height: 1.45; }
.cite .lead { font-weight: 600; margin-right: 0.3em; }
.cite .title { margin-right: 0.3em; }
.cite .title::after { content: '.'; }
.cite .venue { font-style: italic; color: var(--el-ink-3); margin-right: 0.4em; }
.cite .unresolved { color: var(--el-warn-ink); margin-right: 0.4em; }
.doi { color: #1d4ed8; text-decoration: underline; text-underline-offset: 2px; overflow-wrap: anywhere; }

.p-text { margin: 0; font-size: var(--el-fs-base); line-height: 1.6; color: var(--el-ink); background: var(--el-bg-2); border-radius: var(--el-radius-sm); padding: var(--el-s3) var(--el-s4); }

.labels { display: flex; flex-wrap: wrap; gap: var(--el-s2); margin: var(--el-s3) 0 0; padding: 0; border: none; align-items: center; }
.roles { margin-top: var(--el-s2); }
.role-legend { font-size: var(--el-fs-xs); color: var(--el-ink-3); margin-right: var(--el-s2); float: left; padding: 0; }
.seg { position: relative; display: inline-flex; align-items: center; min-height: var(--el-touch); padding: 0 var(--el-s4); border: 1px solid var(--el-line-2); border-radius: var(--el-radius-sm); font-size: var(--el-fs-sm); color: var(--el-ink-2); cursor: pointer; background: var(--el-bg); }
.seg.small { min-height: 2.25rem; font-size: var(--el-fs-xs); padding: 0 var(--el-s3); }
.seg input { position: absolute; opacity: 0; width: 1px; height: 1px; }
.seg:focus-within { outline: 2px solid var(--el-accent); outline-offset: 1px; }
.seg.on { background: var(--el-ink); color: #fff; border-color: var(--el-ink); }
.seg.on.supports { background: #047857; border-color: #047857; }
.seg.on.contradicts { background: #b91c1c; border-color: #b91c1c; }
.seg.on.neutral { background: #4b5563; border-color: #4b5563; }
fieldset:disabled .seg { cursor: default; opacity: 0.7; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
