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
      <div v-if="progress" class="progress-chip" :title="progress.rung_note">
        <strong>{{ progress.completed }}</strong> / {{ progress.total_queue }}
        <span class="rung">{{ progress.rung }}</span>
      </div>
    </header>

    <div v-if="loading" class="state">Loading…</div>

    <div v-else-if="!item" class="state done">
      <span class="icon">✓</span>
      <h2>Nothing queued for you right now</h2>
      <p>
        Either the queue is complete, or every remaining item is one you
        authored or have already judged.
      </p>
      <button class="ghost" @click="load">Check again</button>
    </div>

    <div v-else class="work">
      <!-- The statement, and nothing that could anchor the judgment -->
      <section class="card statement-card">
        <div class="meta-row">
          <span class="badge">#{{ item.sf_number }}</span>
          <span class="badge muted">{{ prettyCategory(item.category) }}</span>
          <span v-if="item.repeated_judgment" class="badge second">
            second independent reading
          </span>
        </div>
        <p class="statement">{{ item.statement }}</p>
        <p class="hash" :title="item.statement_sha256">
          v{{ item.collection_version }} · {{ item.statement_sha256.slice(0, 12) }}
        </p>
      </section>

      <!-- Prior machine output stays collapsed. Opening it is logged, so the
           anchoring effect is measurable rather than assumed. -->
      <section v-if="item.legacy_assessment" class="card collapsed-card">
        <button class="disclose" @click="revealMachine">
          {{ machineShown ? '▾' : '▸' }} Previous automated assessment
          <span class="warn">— judge first, then open if useful</span>
        </button>
        <div v-if="machineShown" class="machine">
          <p>
            Legacy score
            <strong>{{ item.legacy_assessment.score_1_100 }}/100</strong>
            ({{ item.legacy_assessment.confidence }} confidence),
            {{ item.legacy_assessment.n_supporting_refs }} supporting references.
          </p>
          <p class="src">{{ item.legacy_assessment.source }}</p>
        </div>
      </section>

      <!-- Task -->
      <section class="card task-card">
        <h2 class="task-title">{{ taskTitle }}</h2>
        <p class="task-help">{{ taskHelp }}</p>

        <!-- Provenance -->
        <div v-if="item.task === 'provenance'" class="options">
          <label v-for="o in provenanceOptions" :key="o.value" class="option">
            <input type="radio" :value="o.value" v-model="form.provenance_type" />
            <span><strong>{{ o.label }}</strong> — {{ o.hint }}</span>
          </label>
          <input
            v-if="form.provenance_type === 'published' || form.provenance_type === 'adapted'"
            v-model="form.source_citation"
            class="text-input"
            placeholder="DOI, or book + chapter (e.g. Kooijman 2010, ch. 3)"
          />
        </div>

        <!-- Scope -->
        <div v-else-if="item.task === 'scope'" class="options">
          <label v-for="o in scopeOptions" :key="o.value" class="option">
            <input type="radio" :value="o.value" v-model="form.scope_verdict" />
            <span><strong>{{ o.label }}</strong> — {{ o.hint }}</span>
          </label>
          <input
            v-if="form.scope_verdict === 'stated' || form.scope_verdict === 'implicit'"
            v-model="form.proposed_scope"
            class="text-input"
            placeholder="What does this range over? e.g. ectotherms; isomorphic animals; phytoplankton"
          />
        </div>

        <!-- Assessability -->
        <div v-else class="options">
          <label v-for="o in assessabilityOptions" :key="o.value" class="option">
            <input type="radio" :value="o.value" v-model="form.assessability" />
            <span><strong>{{ o.label }}</strong> — {{ o.hint }}</span>
          </label>
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
          v-model="form.rationale"
          class="rationale"
          rows="3"
          placeholder="Why? One or two lines. Required — it is what makes a disagreement interpretable later."
        ></textarea>

        <div class="actions">
          <button class="primary" :disabled="!canSubmit || submitting" @click="submit">
            {{ submitting ? 'Saving…' : 'Submit and next' }}
            <kbd>⏎</kbd>
          </button>
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
        ({{ progress.next_rung_at - progress.completed }} to go).
      </p>
      <p class="muted-text">
        {{ progress.completed_by_me }} by you ·
        {{ progress.repeated_judgments }} repeated
        <template v-if="progress.median_seconds_per_item">
          · median {{ Math.round(progress.median_seconds_per_item) }}s per item
        </template>
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import api from '@/utils/api'

interface QueueItem {
  queue_position: number
  task: 'provenance' | 'scope' | 'assessability'
  sf_number: number
  statement: string
  statement_sha256: string
  category: string
  collection_version: string
  legacy_assessment: Record<string, any> | null
  repeated_judgment: boolean
  stratum: string
}

const item = ref<QueueItem | null>(null)
const progress = ref<any>(null)
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const machineShown = ref(false)

// Time on task is captured automatically — it is the throughput figure the
// method needs, and asking experts to record it would be both unreliable
// and irritating. Paused on blur so a coffee break is not counted as thinking.
const elapsed = ref(0)
let ticker: number | undefined
let focused = true

const form = ref<any>({
  provenance_type: null, source_citation: '',
  scope_verdict: null, proposed_scope: '',
  assessability: null,
  confidence: 0, rationale: '',
})

const provenanceOptions = [
  { value: 'published', label: 'Published', hint: 'states a result already in the literature' },
  { value: 'new', label: 'New', hint: 'first stated here, not from a published source' },
  { value: 'adapted', label: 'Adapted', hint: 'a published result, materially restated' },
  { value: 'unknown', label: 'Unknown', hint: 'cannot establish — an acceptable answer' },
]

const scopeOptions = [
  { value: 'stated', label: 'Scope stated', hint: 'the statement says what it ranges over' },
  { value: 'implicit', label: 'Implicit', hint: 'not stated, but clear from context — give it below' },
  { value: 'absent', label: 'Absent', hint: 'no scope, and none can be inferred' },
  { value: 'not_applicable', label: 'Not applicable', hint: 'not a claim about organisms' },
]

const assessabilityOptions = [
  { value: 'assessable', label: 'Assessable', hint: 'could be checked against literature as written' },
  { value: 'too_vague', label: 'Too vague', hint: 'no determinate claim to check' },
  { value: 'compound', label: 'Compound', hint: 'several claims in one sentence' },
  { value: 'not_empirical', label: 'Not empirical', hint: 'a modelling convention or definition' },
  { value: 'unclear_terms', label: 'Unclear terms', hint: 'key terms undefined or ambiguous' },
]

const taskTitle = computed(() => ({
  provenance: 'Where does this fact come from?',
  scope: 'What does this fact range over?',
  assessability: 'Can this be assessed as written?',
}[item.value?.task ?? 'provenance']))

const taskHelp = computed(() => ({
  provenance: 'The collection is mixed provenance and largely untraced. Published facts must be cited to their source; new ones are published here for the first time.',
  scope: 'Most of the collection states no organismal scope. Without one, evidence cannot be checked against the claim it is supposed to support.',
  assessability: 'Some statements cannot be evaluated as written. Recording that is more useful than quietly excluding them.',
}[item.value?.task ?? 'provenance']))

const canSubmit = computed(() => {
  if (!item.value || form.value.confidence < 1) return false
  if (!form.value.rationale.trim()) return false
  if (item.value.task === 'provenance') return !!form.value.provenance_type
  if (item.value.task === 'scope') return !!form.value.scope_verdict
  return !!form.value.assessability
})

function prettyCategory(c: string) {
  return (c || '').replace(/_/g, ' ')
}

function revealMachine() {
  machineShown.value = !machineShown.value
}

function resetForm() {
  form.value = {
    provenance_type: null, source_citation: '',
    scope_verdict: null, proposed_scope: '',
    assessability: null, confidence: 0, rationale: '',
  }
  machineShown.value = false
  elapsed.value = 0
  error.value = ''
}

async function load() {
  loading.value = true
  try {
    const [next, prog] = await Promise.all([
      api.get('/elicitation/next'),
      api.get('/elicitation/progress'),
    ])
    item.value = next.data || null
    progress.value = prog.data
    resetForm()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not load the queue'
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!item.value || !canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    await api.post('/elicitation/decide', {
      task: item.value.task,
      sf_number: item.value.sf_number,
      statement_sha256: item.value.statement_sha256,
      provenance_type: form.value.provenance_type,
      source_citation: form.value.source_citation || null,
      scope_verdict: form.value.scope_verdict,
      proposed_scope: form.value.proposed_scope || null,
      proposed_taxon_ids: [],
      assessability: form.value.assessability,
      confidence: form.value.confidence,
      rationale: form.value.rationale.trim(),
      time_spent_s: elapsed.value,
      machine_verdict_expanded: machineShown.value,
    })
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not save'
  } finally {
    submitting.value = false
  }
}

function onKey(e: KeyboardEvent) {
  // Keyboard-first: an expert working two hundred items will not use a mouse.
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { submit(); return }
  if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return
  if (e.key >= '1' && e.key <= '5') form.value.confidence = Number(e.key)
}

onMounted(() => {
  load()
  ticker = window.setInterval(() => { if (focused) elapsed.value += 1 }, 1000)
  window.addEventListener('keydown', onKey)
  window.addEventListener('focus', () => { focused = true })
  window.addEventListener('blur', () => { focused = false })
})

onUnmounted(() => {
  if (ticker) window.clearInterval(ticker)
  window.removeEventListener('keydown', onKey)
})
</script>

<style scoped>
.elicitation-view { padding: 1.5rem 2rem; display: flex; flex-direction: column; gap: 1.25rem; max-width: 880px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
.page-header h1 { font-size: 1.5rem; font-weight: 700; color: #111827; }
.sub { color: #6b7280; font-size: 0.9rem; margin-top: 0.25rem; max-width: 46ch; }

.progress-chip { background: #f3f4f6; border-radius: 8px; padding: 0.45rem 0.75rem; font-size: 0.85rem; color: #374151; white-space: nowrap; }
.progress-chip .rung { margin-left: 0.5rem; background: #111827; color: #fff; border-radius: 4px; padding: 0.1rem 0.35rem; font-size: 0.72rem; }

.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 1.1rem 1.25rem; }

.meta-row { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.7rem; }
.badge { background: #eef2ff; color: #3730a3; border-radius: 5px; padding: 0.15rem 0.45rem; font-size: 0.75rem; font-weight: 600; }
.badge.muted { background: #f3f4f6; color: #4b5563; font-weight: 500; }
.badge.second { background: #fef3c7; color: #92400e; }
.statement { font-size: 1.12rem; line-height: 1.6; color: #111827; }
.hash { margin-top: 0.6rem; font-size: 0.72rem; color: #9ca3af; font-family: ui-monospace, monospace; }

.collapsed-card { padding: 0.6rem 1rem; }
.disclose { background: none; border: none; cursor: pointer; font-size: 0.85rem; color: #4b5563; padding: 0.2rem 0; }
.disclose .warn { color: #b45309; }
.machine { margin-top: 0.6rem; font-size: 0.85rem; color: #374151; }
.machine .src { color: #9ca3af; font-size: 0.75rem; margin-top: 0.25rem; }

.task-title { font-size: 1.05rem; font-weight: 600; color: #111827; }
.task-help { color: #6b7280; font-size: 0.85rem; margin: 0.35rem 0 0.9rem; line-height: 1.5; }

.options { display: flex; flex-direction: column; gap: 0.45rem; }
.option { display: flex; gap: 0.6rem; align-items: flex-start; font-size: 0.9rem; color: #374151; cursor: pointer; padding: 0.35rem 0.5rem; border-radius: 6px; }
.option:hover { background: #f9fafb; }
.text-input { margin-top: 0.5rem; width: 100%; padding: 0.5rem 0.65rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.9rem; }

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
.error { color: #b91c1c; font-size: 0.85rem; }
.timer { margin-left: auto; font-size: 0.75rem; color: #9ca3af; }

.state { padding: 3rem 1rem; text-align: center; color: #6b7280; }
.state.done { display: flex; flex-direction: column; align-items: center; gap: 0.7rem; }
.state .icon { font-size: 2.5rem; }
.state h2 { font-size: 1.15rem; color: #374151; font-weight: 600; }

.ladder h3 { font-size: 0.95rem; font-weight: 600; color: #111827; margin-bottom: 0.4rem; }
.ladder p { font-size: 0.85rem; color: #374151; }
.muted-text { color: #9ca3af; font-size: 0.8rem; margin-top: 0.3rem; }
</style>
