<template>
  <div class="elicitation-view">
    <header class="page-header">
      <div>
        <h1>Elicitation</h1>
        <p class="sub">
          Structured expert judgment on stylized facts. One of the two
          consensus processes the method compares — not a gold standard, a
          second measurement.
        </p>
      </div>
      <div class="head-right">
        <div v-if="progress" class="progress-chip" :title="progress.rung_note">
          <strong>{{ progress.completed }}</strong> / {{ progress.total_queue }}
          <span class="rung">{{ progress.rung }}</span>
        </div>
        <button class="icon-btn" title="Keyboard shortcuts (?)"
                @click="showShortcuts = true">?</button>
      </div>
    </header>

    <!-- ── loading ────────────────────────────────────────────────── -->
    <div v-if="state === 'loading'" class="state">Loading…</div>

    <!-- ── fatal error ────────────────────────────────────────────── -->
    <div v-else-if="state === 'error'" class="state card err">
      <span class="icon">⚠</span>
      <h2>Could not load the queue</h2>
      <p class="muted-text">{{ error }}</p>
      <button class="primary" @click="load">Try again</button>
    </div>

    <!-- ── calibration gate ───────────────────────────────────────── -->
    <CalibrationFlow
      v-else-if="state === 'calibration'"
      @done="onCalibrationDone"
      @skip="onCalibrationDone"
    />

    <!-- ── queue exhausted ────────────────────────────────────────── -->
    <div v-else-if="state === 'exhausted'" class="state done card">
      <span class="icon">✓</span>
      <h2>Nothing queued for you right now</h2>
      <p>
        Either the queue is complete, or every remaining item is one you
        authored or have already judged.
      </p>
      <button class="ghost" @click="load">Check again</button>
    </div>

    <!-- ── working ────────────────────────────────────────────────── -->
    <div v-else class="work">
      <section class="card statement-card">
        <div class="meta-row">
          <span class="badge">#{{ item!.sf_number }}</span>
          <span class="badge muted">{{ prettyCategory(item!.category) }}</span>
          <span v-if="item!.repeated_judgment" class="badge second">
            independent re-reading
          </span>
          <span v-if="item!.comparison_item" class="badge panel">
            panel comparison item
          </span>
          <span class="badge cond" :class="condition">
            {{ condition === 'matched' ? 'judging the evidence set' : 'judging from expertise' }}
          </span>
        </div>
        <p class="statement">{{ item!.statement }}</p>
        <p class="hash" :title="item!.statement_sha256">
          v{{ item!.collection_version }} ·
          {{ (item!.statement_sha256 || '').slice(0, 12) }}
        </p>
      </section>

      <!-- Condition is not cosmetic: the two arms are different tasks, and a
           disagreement between them is an information difference rather than a
           judgment difference (docs/09 §5.2). -->
      <p class="cond-note">
        <template v-if="condition === 'matched'">
          Judge <strong>only from the passages below</strong> — the same frozen
          set the model panel read. Set aside what you know beyond them.
        </template>
        <template v-else>
          Judge <strong>from your own knowledge of the field</strong>. There is
          no evidence set for this item; what you know that no corpus contains
          is exactly what this arm is for.
        </template>
      </p>

      <EvidencePanel
        v-if="condition === 'matched' && (item!.passages?.length ?? 0) > 0"
        :passages="item!.passages!"
      />

      <GuidelinesPanel :task="item!.task" />

      <!-- Prior machine output stays collapsed. Opening it is logged, so the
           anchoring effect is measurable rather than assumed. -->
      <section v-if="item!.legacy_assessment" class="card collapsed-card">
        <button class="disclose" @click="revealMachine">
          {{ machineShown ? '▾' : '▸' }} Earlier automated assessment
          <span class="warn">— judge first, then open if useful</span>
          <kbd class="inline-key">e</kbd>
        </button>
        <div v-if="machineShown" class="machine">
          <p>
            Legacy score
            <strong>{{ item!.legacy_assessment.score_1_100 }}/100</strong>
            ({{ item!.legacy_assessment.confidence }} confidence),
            {{ item!.legacy_assessment.n_supporting_refs }} supporting references.
          </p>
          <p class="src">{{ item!.legacy_assessment.source }}</p>
        </div>
      </section>

      <section class="card task-card">
        <h2 class="task-title">{{ spec.title }}</h2>
        <p class="task-help">{{ spec.help }}</p>

        <div class="options">
          <label v-for="(o, i) in spec.options" :key="o.value" class="option"
                 :class="{ picked: chosen === o.value }">
            <input type="radio" :value="o.value" :checked="chosen === o.value"
                   @change="choose(o.value)" />
            <kbd class="okey">{{ OPTION_KEYS[i] }}</kbd>
            <span><strong>{{ o.label }}</strong> — {{ o.hint }}</span>
          </label>

          <div v-if="textRequired" class="text-wrap">
            <label class="text-label">
              {{ spec.textLabel }} <span class="req">required for this choice</span>
            </label>
            <input
              ref="textRef"
              v-model="form.text"
              class="text-input"
              :placeholder="spec.textPlaceholder"
            />
          </div>
        </div>

        <div class="confidence">
          <label>Your confidence</label>
          <div class="conf-buttons">
            <button
              v-for="n in 5" :key="n"
              :class="['conf', { active: form.confidence === n }]"
              @click="form.confidence = n"
            >{{ n }}</button>
          </div>
          <span class="conf-hint">1 = guessing · 5 = certain</span>
        </div>

        <textarea
          ref="rationaleRef"
          v-model="form.rationale"
          class="rationale"
          rows="3"
          placeholder="Why? One or two lines. Required — it is what makes a disagreement interpretable later."
        ></textarea>

        <div class="actions">
          <button class="primary" :disabled="!canSubmit || submitting" @click="submit">
            {{ submitting ? 'Saving…' : 'Submit and next' }}
            <kbd>⌘⏎</kbd>
          </button>
          <span v-if="blockedReason && dirty" class="hint">{{ blockedReason }}</span>
          <span v-if="error" class="error">{{ error }}</span>
          <span class="timer">{{ elapsed }}s on this item</span>
        </div>
      </section>
    </div>

    <section v-if="progress" class="card ladder">
      <h3>What the elicitation so far supports</h3>
      <p><strong>{{ progress.rung }}</strong> — {{ progress.rung_note }}</p>
      <p v-if="progress.next_rung_at" class="muted-text">
        Next rung at {{ progress.next_rung_at }} decisions
        ({{ Math.max(progress.next_rung_at - progress.completed, 0) }} to go).
      </p>
      <p class="muted-text">
        {{ progress.completed_by_me }} by you ·
        {{ progress.repeated_judgments }} repeated
        <template v-if="progress.median_seconds_per_item">
          · median {{ Math.round(progress.median_seconds_per_item) }}s per item
        </template>
      </p>
    </section>

    <!-- Secondary to the judgment, and placed after it deliberately: citing a
         paper must not compete with the task the queue actually asked for. -->
    <ReferencePanel
      v-if="state === 'working' && item"
      :sf-number="item.sf_number"
      :statement-sha256="item.statement_sha256"
    />

    <button class="ghost toggle-history" @click="showHistory = !showHistory">
      {{ showHistory ? 'Hide' : 'Show' }} your decisions <kbd class="inline-key">h</kbd>
    </button>
    <HistoryPanel v-if="showHistory" ref="historyRef" />

    <ShortcutsOverlay v-if="showShortcuts" @close="showShortcuts = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import api from '@/utils/api'
import CalibrationFlow from '@/components/elicitation/CalibrationFlow.vue'
import EvidencePanel from '@/components/elicitation/EvidencePanel.vue'
import type { EvidencePassage } from '@/components/elicitation/EvidencePanel.vue'
import GuidelinesPanel from '@/components/elicitation/GuidelinesPanel.vue'
import HistoryPanel from '@/components/elicitation/HistoryPanel.vue'
import ReferencePanel from '@/components/elicitation/ReferencePanel.vue'
import ShortcutsOverlay from '@/components/elicitation/ShortcutsOverlay.vue'
import {
  OPTION_KEYS, prettyCategory, taskSpec, validateDecision, type TaskType,
} from '@/components/elicitation/taskOptions'

interface QueueItem {
  queue_position: number
  task: TaskType
  sf_number: number
  statement: string
  statement_sha256: string
  category: string
  collection_version: string
  legacy_assessment: Record<string, any> | null
  repeated_judgment: boolean
  comparison_item?: boolean
  n_required?: number
  stratum: string
  evidence_condition?: 'matched' | 'expertise'
  passages?: EvidencePassage[]
}

type State = 'loading' | 'error' | 'calibration' | 'working' | 'exhausted'

const state = ref<State>('loading')
const item = ref<QueueItem | null>(null)
const progress = ref<any>(null)
const submitting = ref(false)
const error = ref('')
const machineShown = ref(false)
const showShortcuts = ref(false)
const showHistory = ref(false)
const calibrationSatisfied = ref(false)

const rationaleRef = ref<HTMLTextAreaElement | null>(null)
const textRef = ref<HTMLInputElement | null>(null)
const historyRef = ref<InstanceType<typeof HistoryPanel> | null>(null)

// Time on task is captured automatically — it is the throughput figure the
// method needs, and asking experts to record it would be unreliable and
// irritating. Paused on blur so a coffee break is not counted as thinking.
const elapsed = ref(0)
let ticker: number | undefined
let focused = true

const form = ref<{ choice: string | null; text: string; confidence: number; rationale: string }>({
  choice: null, text: '', confidence: 0, rationale: '',
})

const spec = computed(() => taskSpec(item.value?.task))
const chosen = computed(() => form.value.choice)
const condition = computed(() => item.value?.evidence_condition ?? 'expertise')

const chosenOption = computed(() =>
  spec.value.options.find((o) => o.value === form.value.choice))

const textRequired = computed(() =>
  !!(chosenOption.value?.requiresText && spec.value.textField))

// Single source of truth, unit-tested in tests/elicitationValidation.test.ts.
// Deliberately not duplicated as a separate boolean check — two copies of a
// validation rule drift, and the one that drifts is the one that lets an empty
// required field through.
const blockedReason = computed(() =>
  item.value ? validateDecision(item.value.task, form.value) : 'No item')

const canSubmit = computed(() =>
  !!item.value && !submitting.value && blockedReason.value === null)

// Only explain what is missing once they have started; an untouched form
// showing "Pick an option" is noise, not help.
const dirty = computed(() =>
  !!form.value.choice || form.value.confidence > 0 || !!form.value.rationale.trim())

function choose(value: string) {
  form.value.choice = value
  if (!textRequired.value) form.value.text = ''
}

function revealMachine() {
  machineShown.value = !machineShown.value
}

function resetForm() {
  form.value = { choice: null, text: '', confidence: 0, rationale: '' }
  machineShown.value = false
  elapsed.value = 0
  error.value = ''
}

async function checkCalibration(): Promise<boolean> {
  if (calibrationSatisfied.value) return true
  try {
    const { data } = await api.get('/elicitation/calibration/status')
    // Absent or non-committal response = not gated. Calibration should train
    // experts, never lock them out because an endpoint is missing.
    const required = !!data?.required
    const complete = !!data?.complete || !!data?.passed
    calibrationSatisfied.value = !required || complete
    return calibrationSatisfied.value
  } catch {
    calibrationSatisfied.value = true
    return true
  }
}

async function load() {
  state.value = 'loading'
  error.value = ''
  try {
    if (!(await checkCalibration())) { state.value = 'calibration'; return }

    const [next, prog] = await Promise.all([
      api.get('/elicitation/next'),
      api.get('/elicitation/progress').catch(() => ({ data: null })),
    ])
    progress.value = prog.data
    item.value = next.data || null
    resetForm()
    state.value = item.value ? 'working' : 'exhausted'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not load the queue'
    state.value = 'error'
  }
}

function onCalibrationDone() {
  calibrationSatisfied.value = true
  load()
}

async function submit() {
  if (!item.value || !canSubmit.value) return
  submitting.value = true
  error.value = ''
  const t = item.value.task
  try {
    await api.post('/elicitation/decide', {
      task: t,
      sf_number: item.value.sf_number,
      statement_sha256: item.value.statement_sha256,
      provenance_type: t === 'provenance' ? form.value.choice : null,
      source_citation: t === 'provenance' ? (form.value.text.trim() || null) : null,
      scope_verdict: t === 'scope' ? form.value.choice : null,
      proposed_scope: t === 'scope' ? (form.value.text.trim() || null) : null,
      proposed_taxon_ids: [],
      assessability: t === 'assessability' ? form.value.choice : null,
      confidence: form.value.confidence,
      rationale: form.value.rationale.trim(),
      evidence_condition: condition.value,
      time_spent_s: elapsed.value,
      machine_verdict_expanded: machineShown.value,
    })
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not save'
    submitting.value = false
    return
  }
  submitting.value = false
  await load()
  historyRef.value?.refresh?.()
}

function onKey(e: KeyboardEvent) {
  // Submit works from anywhere, including mid-sentence in the rationale.
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); return }
  if (showShortcuts.value && e.key === 'Escape') { showShortcuts.value = false; return }

  const typing = e.target instanceof HTMLTextAreaElement
    || e.target instanceof HTMLInputElement
  if (typing) return
  if (e.metaKey || e.ctrlKey || e.altKey) return
  if (e.key === '?') { showShortcuts.value = !showShortcuts.value; return }
  if (state.value !== 'working' || !item.value) return

  const k = e.key.toLowerCase()
  if (k === 'h') { showHistory.value = !showHistory.value; return }
  if (k === 'e' && item.value.legacy_assessment) { revealMachine(); return }
  if (k === 'r') {
    e.preventDefault()
    nextTick(() => rationaleRef.value?.focus())
    return
  }
  if (e.key >= '1' && e.key <= '5') { form.value.confidence = Number(e.key); return }

  const i = OPTION_KEYS.indexOf(k as any)
  if (i >= 0 && i < spec.value.options.length) {
    choose(spec.value.options[i].value)
    if (textRequired.value) nextTick(() => textRef.value?.focus())
  }
}

function onFocus() { focused = true }
function onBlur() { focused = false }

onMounted(() => {
  load()
  ticker = window.setInterval(() => {
    if (focused && state.value === 'working') elapsed.value += 1
  }, 1000)
  window.addEventListener('keydown', onKey)
  window.addEventListener('focus', onFocus)
  window.addEventListener('blur', onBlur)
})

onUnmounted(() => {
  if (ticker) window.clearInterval(ticker)
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('focus', onFocus)
  window.removeEventListener('blur', onBlur)
})
</script>

<style scoped>
.elicitation-view { padding: 1.5rem 2rem; display: flex; flex-direction: column; gap: 1.25rem; max-width: 880px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
.page-header h1 { font-size: 1.5rem; font-weight: 700; color: #111827; }
.sub { color: #6b7280; font-size: 0.9rem; margin-top: 0.25rem; max-width: 46ch; }
.head-right { display: flex; align-items: center; gap: 0.5rem; }
.icon-btn { width: 1.9rem; height: 1.9rem; border-radius: 6px; border: 1px solid #e5e7eb; background: #fff; cursor: pointer; color: #6b7280; font-weight: 600; }

.progress-chip { background: #f3f4f6; border-radius: 8px; padding: 0.45rem 0.75rem; font-size: 0.85rem; color: #374151; white-space: nowrap; }
.progress-chip .rung { margin-left: 0.5rem; background: #111827; color: #fff; border-radius: 4px; padding: 0.1rem 0.35rem; font-size: 0.72rem; }

.work { display: flex; flex-direction: column; gap: 1.25rem; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 1.1rem 1.25rem; }

.meta-row { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.7rem; }
.badge { background: #eef2ff; color: #3730a3; border-radius: 5px; padding: 0.15rem 0.45rem; font-size: 0.75rem; font-weight: 600; }
.badge.muted { background: #f3f4f6; color: #4b5563; font-weight: 500; }
.badge.second { background: #fef3c7; color: #92400e; }
.badge.panel { background: #ede9fe; color: #5b21b6; }
.badge.cond.matched { background: #dbeafe; color: #1e40af; }
.badge.cond.expertise { background: #ecfdf5; color: #065f46; }
.statement { font-size: 1.12rem; line-height: 1.6; color: #111827; }
.hash { margin-top: 0.6rem; font-size: 0.72rem; color: #9ca3af; font-family: ui-monospace, monospace; }

.cond-note { font-size: 0.85rem; color: #4b5563; line-height: 1.55; background: #f9fafb; border-left: 3px solid #d1d5db; padding: 0.55rem 0.8rem; border-radius: 0 6px 6px 0; }

.collapsed-card { padding: 0.6rem 1rem; }
.disclose { background: none; border: none; cursor: pointer; font-size: 0.85rem; color: #4b5563; padding: 0.2rem 0; text-align: left; }
.disclose .warn { color: #b45309; }
.inline-key { background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 4px; padding: 0 0.3rem; font-size: 0.7rem; color: #6b7280; margin-left: 0.4rem; }
.machine { margin-top: 0.6rem; font-size: 0.85rem; color: #374151; }
.machine .src { color: #9ca3af; font-size: 0.75rem; margin-top: 0.25rem; }

.task-title { font-size: 1.05rem; font-weight: 600; color: #111827; }
.task-help { color: #6b7280; font-size: 0.85rem; margin: 0.35rem 0 0.9rem; line-height: 1.5; }

.options { display: flex; flex-direction: column; gap: 0.45rem; }
.option { display: flex; gap: 0.6rem; align-items: flex-start; font-size: 0.9rem; color: #374151; cursor: pointer; padding: 0.35rem 0.5rem; border-radius: 6px; }
.option:hover { background: #f9fafb; }
.option.picked { background: #eef2ff; }
.okey { background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 4px; padding: 0 0.3rem; font-size: 0.7rem; color: #6b7280; }

.text-wrap { margin-top: 0.6rem; }
.text-label { display: block; font-size: 0.8rem; color: #374151; font-weight: 500; margin-bottom: 0.25rem; }
.text-label .req { color: #b45309; font-weight: 400; }
.text-input { width: 100%; padding: 0.5rem 0.65rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.9rem; }

.confidence { display: flex; align-items: center; gap: 0.6rem; margin-top: 1rem; flex-wrap: wrap; }
.confidence label { font-size: 0.85rem; color: #374151; font-weight: 500; }
.conf-buttons { display: flex; gap: 0.25rem; }
.conf { width: 2rem; height: 2rem; border: 1px solid #d1d5db; background: #fff; border-radius: 6px; cursor: pointer; }
.conf.active { background: #111827; color: #fff; border-color: #111827; }
.conf-hint { font-size: 0.75rem; color: #9ca3af; }

.rationale { margin-top: 0.8rem; width: 100%; padding: 0.6rem 0.7rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.9rem; font-family: inherit; resize: vertical; }

.actions { display: flex; align-items: center; gap: 1rem; margin-top: 0.9rem; flex-wrap: wrap; }
.primary { background: #111827; color: #fff; border: none; border-radius: 6px; padding: 0.55rem 1.1rem; font-size: 0.9rem; cursor: pointer; }
.primary:disabled { background: #d1d5db; cursor: not-allowed; }
.primary kbd { margin-left: 0.5rem; opacity: 0.6; font-size: 0.75rem; }
.ghost { background: #fff; border: 1px solid #d1d5db; border-radius: 6px; padding: 0.45rem 0.9rem; cursor: pointer; font-size: 0.85rem; }
.toggle-history { align-self: flex-start; }
.error { color: #b91c1c; font-size: 0.85rem; }
.hint { color: #b45309; font-size: 0.82rem; }
.timer { margin-left: auto; font-size: 0.75rem; color: #9ca3af; }

.state { padding: 3rem 1rem; text-align: center; color: #6b7280; }
.state.done, .state.err { display: flex; flex-direction: column; align-items: center; gap: 0.7rem; }
.state .icon { font-size: 2.5rem; }
.state h2 { font-size: 1.15rem; color: #374151; font-weight: 600; }

.ladder h3 { font-size: 0.95rem; font-weight: 600; color: #111827; margin-bottom: 0.4rem; }
.ladder p { font-size: 0.85rem; color: #374151; }
.muted-text { color: #9ca3af; font-size: 0.8rem; margin-top: 0.3rem; }
</style>
