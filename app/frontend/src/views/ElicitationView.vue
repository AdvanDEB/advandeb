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
    <!-- The server refuses to serve or record anything before calibration
         (docs/10 §5.3), so there is no "skip": skipping only ever led to an
         empty queue that looked finished. -->
    <CalibrationFlow
      v-else-if="state === 'calibration'"
      @done="onCalibrationDone"
    />

    <div v-else-if="state === 'calibration-unavailable'" class="state card">
      <span class="icon">⏳</span>
      <h2>Calibration is not set up yet</h2>
      <p>
        Every expert works the calibration set before their first judgment,
        and it has not been prepared yet. An administrator needs to seed it;
        nothing you do here is lost in the meantime.
      </p>
      <button class="ghost" @click="load">Check again</button>
    </div>

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
          <span class="badge cond" :class="condition" data-test="condition">
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
        v-if="isEvidence"
        v-model="evidence"
        :passages="item!.passages"
        :total="item!.n_passages_total"
        :disabled="submitting"
      />

      <GuidelinesPanel :task="item!.task" />

      <!-- Prior machine output stays collapsed. Opening it is logged, so the
           anchoring effect is measurable rather than assumed. -->
      <section v-if="item!.legacy_assessment" class="card collapsed-card">
        <button class="disclose" data-test="machine-toggle" @click="revealMachine">
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

        <div v-if="isEvidence" class="scores">
          <fieldset class="score">
            <legend>Evidence strength — how much support these passages provide</legend>
            <label v-for="o in STRENGTH_OPTIONS" :key="o.value" class="option"
                   :class="{ picked: evidence.evidence_strength === o.value }">
              <input type="radio" name="evidence_strength" :value="o.value"
                     :checked="evidence.evidence_strength === o.value"
                     @change="evidence = { ...evidence, evidence_strength: o.value }" />
              <span><strong>{{ o.label }}</strong> — {{ o.hint }}</span>
            </label>
          </fieldset>
          <fieldset class="score">
            <legend>Consensus direction — which way the literature points</legend>
            <label v-for="o in CONSENSUS_OPTIONS" :key="o.value" class="option"
                   :class="{ picked: evidence.consensus_direction === o.value }">
              <input type="radio" name="consensus_direction" :value="o.value"
                     :checked="evidence.consensus_direction === o.value"
                     @change="evidence = { ...evidence, consensus_direction: o.value }" />
              <span><strong>{{ o.label }}</strong> — {{ o.hint }}</span>
            </label>
          </fieldset>
        </div>

        <div v-else class="options">
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
          <span v-if="blockedReason && dirty" class="hint" data-test="blocked">{{ blockedReason }}</span>
          <span v-if="error" class="error" data-test="error">{{ error }}</span>
          <button v-if="stale" class="ghost" @click="load">Load the next item</button>
          <span class="timer">{{ elapsed }}s on this item</span>
        </div>
      </section>
    </div>

    <section v-if="progress" class="card ladder">
      <h3>What the elicitation so far supports</h3>
      <p><strong>{{ progress.rung }}</strong> — {{ progress.rung_note }}</p>
      <p v-if="progress.next_rung_at" class="muted-text">
        Next rung at {{ progress.next_rung_at }} {{ progress.ladder_basis }}
        ({{ Math.max(progress.next_rung_at - progress.ladder_count, 0) }} to go).
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
import GuidelinesPanel from '@/components/elicitation/GuidelinesPanel.vue'
import HistoryPanel from '@/components/elicitation/HistoryPanel.vue'
import ReferencePanel from '@/components/elicitation/ReferencePanel.vue'
import ShortcutsOverlay from '@/components/elicitation/ShortcutsOverlay.vue'
import {
  CONSENSUS_OPTIONS, OPTION_KEYS, STRENGTH_OPTIONS, prettyCategory, taskSpec,
} from '@/components/elicitation/taskOptions'
import {
  blockedReason as reasonBlocked, buildDecision, emptyEvidenceDraft,
  labelledCount, type EvidenceDraft,
} from '@/components/elicitation/decision'
import type {
  CalibrationStatus, ElicitationEvent, ElicitationProgress, QueueItem,
} from '@/types/elicitation.generated'

type State =
  | 'loading' | 'error' | 'calibration' | 'calibration-unavailable'
  | 'working' | 'exhausted'

const state = ref<State>('loading')
const item = ref<QueueItem | null>(null)
const progress = ref<ElicitationProgress | null>(null)
const submitting = ref(false)
const error = ref('')
// The queue moved on under this item (409): someone completed it, or it is no
// longer this expert's head. Offer the next one instead of a dead end.
const stale = ref(false)
const machineShown = ref(false)
const showShortcuts = ref(false)
const showHistory = ref(false)

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
const evidence = ref<EvidenceDraft>(emptyEvidenceDraft(null))

const spec = computed(() => taskSpec(item.value?.task))
const chosen = computed(() => form.value.choice)
const isEvidence = computed(() => item.value?.task === 'evidence')
// Decided by the server from the task; never defaulted here. Defaulting to
// `expertise` when the field was absent is what hid every evidence passage.
const condition = computed(() => item.value?.evidence_condition ?? 'expertise')

const chosenOption = computed(() =>
  spec.value.options.find((o) => o.value === form.value.choice))

const textRequired = computed(() =>
  !!(chosenOption.value?.requiresText && spec.value.textField))

// Single source of truth, unit-tested in tests/elicitationValidation.test.ts
// and tests/elicitationEvidence.test.ts. Two copies of a validation rule
// drift, and the one that drifts is the one that lets a gap through.
const blockedReason = computed(() =>
  reasonBlocked(item.value, form.value, evidence.value))

const canSubmit = computed(() =>
  !!item.value && !submitting.value && blockedReason.value === null)

// Only explain what is missing once they have started; an untouched form
// showing "Pick an option" is noise, not help.
const dirty = computed(() =>
  !!form.value.choice || form.value.confidence > 0 || !!form.value.rationale.trim()
  || (!!item.value && isEvidence.value && labelledCount(item.value, evidence.value) > 0))

const answered = computed(() => isEvidence.value
  ? !!item.value && labelledCount(item.value, evidence.value) > 0
  : !!form.value.choice)

function choose(value: string) {
  form.value.choice = value
  if (!textRequired.value) form.value.text = ''
}

// Every opening and closing is logged with whether the expert had already
// answered. Exposure is derived from these on the server; the state at submit
// time alone would report an open-read-close as "never opened".
function logEvent(event: ElicitationEvent['event']) {
  if (!item.value) return
  const payload: ElicitationEvent = {
    event,
    sf_number: item.value.sf_number,
    task: item.value.task,
    corpus_id: item.value.corpus_id,
    answered: answered.value,
  }
  api.post('/elicitation/events', payload).catch(() => {
    // Logging must not block judging; a lost event under-reports exposure,
    // and the submit-time flag is still recorded beside it.
  })
}

function revealMachine() {
  machineShown.value = !machineShown.value
  logEvent(machineShown.value ? 'machine_verdict_opened' : 'machine_verdict_closed')
}

function resetForm() {
  form.value = { choice: null, text: '', confidence: 0, rationale: '' }
  evidence.value = emptyEvidenceDraft(item.value)
  machineShown.value = false
  elapsed.value = 0
  error.value = ''
  stale.value = false
}

/** Where calibration stands, from the typed status contract. */
async function calibrationState(): Promise<'done' | 'calibration' | 'calibration-unavailable'> {
  const { data } = await api.get<CalibrationStatus>('/elicitation/calibration/status')
  if (data.done) return 'done'
  return data.available ? 'calibration' : 'calibration-unavailable'
}

async function load() {
  state.value = 'loading'
  error.value = ''
  try {
    // Not waved through on failure. The server gates /next on calibration,
    // so a client that guessed "calibrated" only ever showed an empty queue
    // that looked finished.
    const cal = await calibrationState()
    if (cal !== 'done') { state.value = cal; return }

    const [next, prog] = await Promise.all([
      api.get<QueueItem | null>('/elicitation/next'),
      api.get<ElicitationProgress>('/elicitation/progress').catch(() => ({ data: null })),
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
  load()
}

async function submit() {
  if (!item.value || !canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    await api.post('/elicitation/decide', buildDecision(item.value, form.value, evidence.value, {
      time_spent_s: elapsed.value,
      machine_verdict_expanded: machineShown.value,
    }))
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not save'
    stale.value = e?.response?.status === 409
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
.scores { display: flex; flex-direction: column; gap: 0.9rem; }
.score { border: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.35rem; }
.score legend { font-size: 0.85rem; font-weight: 500; color: #374151; margin-bottom: 0.3rem; }
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
