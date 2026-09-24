<template>
  <div class="calibration">
    <header class="cal-head">
      <div>
        <h2>Calibration set</h2>
        <p class="sub">
          {{ total }} adjudicated cases, worked before the real queue opens.
          They train the label definitions and give a quality signal that costs
          no queue items — a disagreement here is cheap, one in the gold set is
          not.
        </p>
      </div>
      <div class="cal-progress">
        <strong>{{ completed }}</strong> / {{ total }}
      </div>
    </header>

    <div v-if="loading" class="state">Loading calibration case…</div>

    <div v-else-if="finished" class="state done card">
      <span class="icon">✓</span>
      <h3>Calibration complete</h3>
      <p>
        You matched the reference on <strong>{{ correctCount }}</strong> of
        {{ total }}.
        <template v-if="correctCount < total">
          The cases you missed are worth reviewing with a tier-A expert before
          you start — that conversation is the point of the exercise.
        </template>
      </p>
      <button class="primary" @click="emit('done')">Start the queue</button>
    </div>

    <div v-else-if="!currentCase" class="state card">
      <p>Calibration is unavailable right now.</p>
      <button class="ghost" @click="fetchNext">Try again</button>
      <button class="ghost" @click="emit('skip')">Continue to the queue</button>
      <p class="muted-text">
        Skipping is recorded — calibration status travels with your decisions.
      </p>
    </div>

    <template v-else>
      <section class="card statement-card">
        <div class="meta-row">
          <span class="badge">case {{ completed + 1 }} / {{ total }}</span>
          <span class="badge muted">{{ prettyCategory(currentCase.category || '') }}</span>
          <span class="badge task">{{ spec.title }}</span>
        </div>
        <p class="statement">{{ currentCase.statement }}</p>
      </section>

      <section class="card task-card">
        <div class="options">
          <label v-for="(o, i) in spec.options" :key="o.value" class="option"
                 :class="{ picked: answer === o.value, disabled: !!reveal }">
            <input type="radio" :value="o.value" v-model="answer" :disabled="!!reveal" />
            <kbd class="okey">{{ OPTION_KEYS[i] }}</kbd>
            <span><strong>{{ o.label }}</strong> — {{ o.hint }}</span>
          </label>
        </div>

        <div v-if="!reveal" class="actions">
          <button class="primary" :disabled="!answer || checking" @click="check">
            {{ checking ? 'Checking…' : 'Check answer' }}
          </button>
          <span v-if="error" class="error">{{ error }}</span>
        </div>

        <div v-else class="reveal" :class="reveal.correct ? 'ok' : 'miss'">
          <p class="verdict">
            <strong>{{ reveal.correct ? 'Matches the reference' : 'Differs from the reference' }}</strong>
            <template v-if="!reveal.correct">
              — reference answer: <strong>{{ referenceLabel }}</strong>
            </template>
          </p>
          <p v-if="reveal.explanation" class="explain">{{ reveal.explanation }}</p>
          <button class="primary" @click="next">
            {{ completed >= total ? 'Finish' : 'Next case' }}
          </button>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import api from '@/utils/api'
import { OPTION_KEYS, prettyCategory, taskSpec, type TaskType } from './taskOptions'

const emit = defineEmits<{ (e: 'done'): void; (e: 'skip'): void }>()

interface CalCase {
  case_id: string
  task: TaskType
  statement: string
  category?: string
}
interface Reveal {
  correct: boolean
  reference: string
  explanation?: string
}

const loading = ref(true)
const checking = ref(false)
const error = ref('')
const currentCase = ref<CalCase | null>(null)
const answer = ref<string | null>(null)
const reveal = ref<Reveal | null>(null)
const completed = ref(0)
const total = ref(15)
const correctCount = ref(0)
const finished = ref(false)

const spec = computed(() => taskSpec(currentCase.value?.task))
const referenceLabel = computed(() => {
  const r = reveal.value?.reference
  return spec.value.options.find((o) => o.value === r)?.label ?? r ?? '—'
})

async function fetchNext() {
  loading.value = true
  error.value = ''
  reveal.value = null
  answer.value = null
  try {
    const { data } = await api.get('/elicitation/calibration/next')
    if (!data || data.finished) {
      finished.value = true
      currentCase.value = null
      if (typeof data?.correct === 'number') correctCount.value = data.correct
      if (typeof data?.total === 'number') total.value = data.total
    } else {
      currentCase.value = data.case ?? data
      if (typeof data.completed === 'number') completed.value = data.completed
      if (typeof data.total === 'number') total.value = data.total
    }
  } catch {
    currentCase.value = null
  } finally {
    loading.value = false
  }
}

async function check() {
  if (!answer.value || !currentCase.value) return
  checking.value = true
  error.value = ''
  try {
    const { data } = await api.post('/elicitation/calibration/answer', {
      case_id: currentCase.value.case_id,
      task: currentCase.value.task,
      answer: answer.value,
    })
    reveal.value = {
      correct: !!data?.correct,
      reference: data?.reference,
      explanation: data?.explanation,
    }
    if (data?.correct) correctCount.value += 1
    completed.value = typeof data?.completed === 'number'
      ? data.completed
      : completed.value + 1
    if (typeof data?.total === 'number') total.value = data.total
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not check that answer'
  } finally {
    checking.value = false
  }
}

function next() {
  if (completed.value >= total.value) { finished.value = true; return }
  fetchNext()
}

function onKey(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
  if (reveal.value) {
    if (e.key === 'Enter') next()
    return
  }
  const i = OPTION_KEYS.indexOf(e.key.toLowerCase() as any)
  if (i >= 0 && i < spec.value.options.length) {
    answer.value = spec.value.options[i].value
    return
  }
  if (e.key === 'Enter' && answer.value) check()
}

onMounted(() => { fetchNext(); window.addEventListener('keydown', onKey) })
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.calibration { display: flex; flex-direction: column; gap: 1.1rem; }
.cal-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
.cal-head h2 { font-size: 1.2rem; font-weight: 700; color: #111827; }
.sub { color: #6b7280; font-size: 0.85rem; margin-top: 0.25rem; max-width: 52ch; line-height: 1.55; }
.cal-progress { background: #f3f4f6; border-radius: 8px; padding: 0.45rem 0.75rem; font-size: 0.9rem; color: #374151; white-space: nowrap; }

.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 1.1rem 1.25rem; }
.meta-row { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.7rem; }
.badge { background: #eef2ff; color: #3730a3; border-radius: 5px; padding: 0.15rem 0.45rem; font-size: 0.75rem; font-weight: 600; }
.badge.muted { background: #f3f4f6; color: #4b5563; font-weight: 500; }
.badge.task { background: #ecfdf5; color: #065f46; font-weight: 500; }
.statement { font-size: 1.1rem; line-height: 1.6; color: #111827; }

.options { display: flex; flex-direction: column; gap: 0.45rem; }
.option { display: flex; gap: 0.6rem; align-items: flex-start; font-size: 0.9rem; color: #374151; cursor: pointer; padding: 0.35rem 0.5rem; border-radius: 6px; }
.option:hover { background: #f9fafb; }
.option.picked { background: #eef2ff; }
.option.disabled { cursor: default; opacity: 0.75; }
.okey { background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 4px; padding: 0 0.3rem; font-size: 0.7rem; color: #6b7280; }

.actions { display: flex; align-items: center; gap: 1rem; margin-top: 0.9rem; }
.primary { background: #111827; color: #fff; border: none; border-radius: 6px; padding: 0.55rem 1.1rem; font-size: 0.9rem; cursor: pointer; }
.primary:disabled { background: #d1d5db; cursor: not-allowed; }
.ghost { background: #fff; border: 1px solid #d1d5db; border-radius: 6px; padding: 0.45rem 0.9rem; cursor: pointer; font-size: 0.85rem; margin-right: 0.5rem; }
.error { color: #b91c1c; font-size: 0.85rem; }

.reveal { margin-top: 1rem; padding: 0.8rem 0.9rem; border-radius: 8px; }
.reveal.ok { background: #f0fdf4; border: 1px solid #bbf7d0; }
.reveal.miss { background: #fffbeb; border: 1px solid #fde68a; }
.verdict { font-size: 0.9rem; color: #111827; }
.explain { font-size: 0.85rem; color: #4b5563; line-height: 1.55; margin: 0.4rem 0 0.8rem; }

.state { padding: 2.5rem 1rem; text-align: center; color: #6b7280; }
.state.done { display: flex; flex-direction: column; align-items: center; gap: 0.7rem; }
.state .icon { font-size: 2.5rem; }
.state h3 { font-size: 1.1rem; color: #374151; font-weight: 600; }
.muted-text { color: #9ca3af; font-size: 0.8rem; margin-top: 0.4rem; }
</style>
