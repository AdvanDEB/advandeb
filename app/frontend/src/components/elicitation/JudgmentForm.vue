<template>
  <div class="judgment">
    <EvidencePanel
      v-model="draft"
      :passages="item.passages"
      :total="item.n_passages_total"
      :disabled="submitting"
    />

    <!-- Step 2: the expert's own judgment of the fact (H-EK). -->
    <section class="el-card" aria-labelledby="overall-head">
      <h2 id="overall-head"><span class="step">2</span> Your judgment of the fact</h2>
      <p class="note">From these passages <strong>and</strong> from what you know of the literature.</p>
      <div class="scores">
        <fieldset class="score" :disabled="submitting">
          <legend>How strong is the evidence for it?</legend>
          <label v-for="o in STRENGTH_OPTIONS" :key="o.value" class="option"
                 :class="{ picked: draft.evidence_strength === o.value }">
            <input type="radio" :name="`strength-${uid}`" :value="o.value"
                   :checked="draft.evidence_strength === o.value"
                   @change="draft = { ...draft, evidence_strength: o.value }" />
            <span><strong>{{ o.label }}</strong> — {{ o.hint }}</span>
          </label>
        </fieldset>
        <fieldset class="score" :disabled="submitting">
          <legend>Which way does it point?</legend>
          <label v-for="o in CONSENSUS_OPTIONS" :key="o.value" class="option"
                 :class="{ picked: draft.consensus_direction === o.value }">
            <input type="radio" :name="`consensus-${uid}`" :value="o.value"
                   :checked="draft.consensus_direction === o.value"
                   @change="draft = { ...draft, consensus_direction: o.value }" />
            <span><strong>{{ o.label }}</strong> — {{ o.hint }}</span>
          </label>
        </fieldset>
      </div>
    </section>

    <!-- Step 3: departure, the reason where one is owed, and references. -->
    <section class="el-card" aria-labelledby="departure-head">
      <h2 id="departure-head"><span class="step">3</span> {{ DEPARTURE_QUESTION }}</h2>
      <fieldset class="yesno" :disabled="submitting" data-test="departure">
        <legend class="sr-only">{{ DEPARTURE_QUESTION }}</legend>
        <label v-for="o in DEPARTURE_OPTIONS" :key="o.value" class="option inline"
               :class="{ picked: departValue === o.value }">
          <input type="radio" :name="`departs-${uid}`" :value="o.value"
                 :checked="departValue === o.value"
                 @change="draft = { ...draft, departs: o.value === 'yes' }" />
          <span><strong>{{ o.label }}</strong> — {{ o.hint }}</span>
        </label>
      </fieldset>

      <p v-if="conflicts.length && draft.departs !== true" class="conflict" role="status"
         data-test="conflict">
        Your overall judgment goes beyond your passage labels: {{ conflictText(conflicts) }}.
        That is fine — add a line on what you are relying on.
      </p>

      <div class="field">
        <label :for="`rationale-${uid}`" class="field-label">
          <template v-if="needsReason">Why? <span class="req">required</span></template>
          <template v-else>Note <span class="opt">optional</span></template>
        </label>
        <textarea
          :id="`rationale-${uid}`"
          ref="rationaleRef"
          v-model="common.rationale"
          class="rationale"
          rows="2"
          :required="needsReason"
          :aria-required="needsReason ? 'true' : undefined"
          :disabled="submitting"
          :placeholder="needsReason
            ? 'One or two lines: what do you know that the passages do not show?'
            : 'Anything worth recording about this fact (optional)'"
        ></textarea>
      </div>

      <ReferencePanel
        v-if="allowReferences"
        :sf-number="item.sf_number"
        :statement-sha256="item.statement_sha256"
        :prominent="draft.departs === true"
        @changed="referenceIds = $event"
      />
    </section>

    <!-- Step 4: confidence and submit. -->
    <section class="el-card submit-card">
      <div class="confidence">
        <span id="conf-label" class="field-label">Your confidence</span>
        <div class="conf-buttons" role="radiogroup" aria-labelledby="conf-label">
          <button
            v-for="n in 5" :key="n" type="button" role="radio"
            :aria-checked="common.confidence === n"
            :class="['conf', { active: common.confidence === n }]"
            :disabled="submitting"
            @click="common.confidence = n"
          >{{ n }}</button>
        </div>
        <span class="conf-hint">1 = guessing · 5 = certain</span>
      </div>

      <div class="actions">
        <button class="el-btn el-btn--primary" type="button" data-test="submit"
                :disabled="!!blocked || submitting" @click="emitSubmit">
          {{ submitting ? 'Saving…' : submitLabel }}
        </button>
        <span class="hint" role="status" data-test="blocked">{{ touched ? blocked : '' }}</span>
        <span v-if="error" class="error" role="alert" data-test="error">{{ error }}</span>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import EvidencePanel from './EvidencePanel.vue'
import ReferencePanel from './ReferencePanel.vue'
import {
  CONSENSUS_OPTIONS, DEPARTURE_OPTIONS, DEPARTURE_QUESTION, STRENGTH_OPTIONS,
} from './taskOptions'
import {
  conflictText, emptyEvidenceDraft, labelledCount, rationaleRequired,
  scoreLabelConflicts, validateEvidence, type EvidenceDraft, type JudgmentCommon,
} from './decision'
import type { EvidencePassage } from '@/types/elicitation.generated'

export interface JudgmentSubmit {
  draft: EvidenceDraft
  common: JudgmentCommon
  referenceIds: string[]
}

const props = withDefaults(defineProps<{
  item: {
    passages: EvidencePassage[]
    n_passages_total?: number | null
    sf_number: number
    statement_sha256: string
  }
  allowReferences?: boolean
  submitting?: boolean
  submitLabel?: string
  error?: string
}>(), { allowReferences: true, submitting: false, submitLabel: 'Submit and next', error: '' })

const emit = defineEmits<{ (e: 'submit', v: JudgmentSubmit): void }>()

const uid = Math.random().toString(36).slice(2, 8)
const draft = ref<EvidenceDraft>(emptyEvidenceDraft(props.item))
const common = ref<JudgmentCommon>({ confidence: 0, rationale: '' })
const referenceIds = ref<string[]>([])
const rationaleRef = ref<HTMLTextAreaElement | null>(null)

const departValue = computed(() =>
  draft.value.departs === null ? null : draft.value.departs ? 'yes' : 'no')
const conflicts = computed(() => scoreLabelConflicts(props.item, draft.value))
const needsReason = computed(() => rationaleRequired(props.item, draft.value))
const blocked = computed(() => validateEvidence(props.item, draft.value, common.value))
// Only explain what is missing once they have started: an untouched form
// saying "Label every passage" is noise, not help.
const touched = computed(() =>
  labelledCount(props.item, draft.value) > 0 || common.value.confidence > 0
  || draft.value.evidence_strength !== null)

function reset() {
  draft.value = emptyEvidenceDraft(props.item)
  common.value = { confidence: 0, rationale: '' }
  referenceIds.value = []
}
watch(() => props.item, reset)

function emitSubmit() {
  if (blocked.value || props.submitting) return
  emit('submit', {
    draft: draft.value, common: { ...common.value }, referenceIds: [...referenceIds.value],
  })
}

/** The state the parent may need for logging, without owning the draft. */
defineExpose({ reset, answered: computed(() => labelledCount(props.item, draft.value) > 0) })

function onKey(e: KeyboardEvent) {
  // Submit works from anywhere, including mid-sentence in the reason.
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); emitSubmit(); return }
  const typing = e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement
    && e.target.type !== 'radio'
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return
  if (e.key >= '1' && e.key <= '5') { common.value.confidence = Number(e.key); return }
  if (e.key.toLowerCase() === 'r') { e.preventDefault(); rationaleRef.value?.focus() }
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.judgment { display: flex; flex-direction: column; gap: var(--el-s5); }
h2 { font-size: var(--el-fs-lg); font-weight: 600; color: var(--el-ink); display: flex; align-items: flex-start; gap: var(--el-s2); line-height: 1.35; }
.step { flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; width: 1.5rem; height: 1.5rem; border-radius: 50%; background: var(--el-ink); color: #fff; font-size: var(--el-fs-sm); }
.note { font-size: var(--el-fs-sm); color: var(--el-ink-3); margin: var(--el-s2) 0 var(--el-s3); }
.scores { display: grid; grid-template-columns: 1fr 1fr; gap: var(--el-s5); }
@media (max-width: 640px) { .scores { grid-template-columns: 1fr; } }
.score, .yesno { border: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: var(--el-s1); }
.yesno { margin-top: var(--el-s3); flex-direction: row; flex-wrap: wrap; gap: var(--el-s2); }
.score legend { font-size: var(--el-fs-sm); font-weight: 600; color: var(--el-ink-2); margin-bottom: var(--el-s2); }
.option { display: flex; gap: var(--el-s2); align-items: center; min-height: var(--el-touch); font-size: var(--el-fs-sm); color: var(--el-ink-2); cursor: pointer; padding: 0 var(--el-s3); border-radius: var(--el-radius-sm); border: 1px solid transparent; }
.option:hover { background: var(--el-bg-2); }
.option.picked { background: var(--el-info-bg); border-color: var(--el-line-2); }
.option.inline { border-color: var(--el-line); flex: 1 1 16rem; }
.option input:focus-visible { outline: 2px solid var(--el-accent); outline-offset: 2px; }

.conflict { margin-top: var(--el-s3); background: var(--el-warn-bg); color: var(--el-warn-ink); border-radius: var(--el-radius-sm); padding: var(--el-s2) var(--el-s3); font-size: var(--el-fs-sm); line-height: var(--el-lh); }
.field { margin-top: var(--el-s4); }
.field-label { display: block; font-size: var(--el-fs-sm); font-weight: 600; color: var(--el-ink-2); margin-bottom: var(--el-s1); }
.req { color: var(--el-warn-ink); font-weight: 500; }
.opt { color: var(--el-ink-4); font-weight: 400; }
.rationale { width: 100%; padding: var(--el-s2) var(--el-s3); border: 1px solid var(--el-line-2); border-radius: var(--el-radius-sm); font-size: var(--el-fs-base); font-family: inherit; resize: vertical; }
.rationale:focus-visible { outline: 2px solid var(--el-accent); outline-offset: 1px; }

.submit-card { display: flex; flex-direction: column; gap: var(--el-s4); }
.confidence { display: flex; align-items: center; gap: var(--el-s3); flex-wrap: wrap; }
.confidence .field-label { margin: 0; }
.conf-buttons { display: flex; gap: var(--el-s1); }
.conf { width: var(--el-touch); height: var(--el-touch); border: 1px solid var(--el-line-2); background: var(--el-bg); border-radius: var(--el-radius-sm); cursor: pointer; font-size: var(--el-fs-base); }
.conf.active { background: var(--el-ink); color: #fff; border-color: var(--el-ink); }
.conf:focus-visible { outline: 2px solid var(--el-accent); outline-offset: 2px; }
.conf-hint { font-size: var(--el-fs-xs); color: var(--el-ink-3); }
.actions { display: flex; align-items: center; gap: var(--el-s4); flex-wrap: wrap; }
/* Reserved so a message appearing never moves the button under a finger. */
.hint { color: var(--el-warn-ink); font-size: var(--el-fs-sm); min-height: 1.4em; }
.error { color: var(--el-danger); font-size: var(--el-fs-sm); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
