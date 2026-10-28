<template>
  <div class="calibration">
    <section class="el-card intro">
      <header class="cal-head">
        <h2>Worked examples</h2>
        <span class="cal-progress" data-test="cal-progress">
          {{ finished ? total : caseNumber }} of {{ total }}
        </span>
      </header>
      <p>
        Before your next fact, work through these {{ total }} examples exactly
        as you would a real one. The team agreed an answer for each, and you
        see it as soon as you submit. Examples are not part of the study, and
        a different answer is not a mistake to hide — it is what the
        explanation is for.
      </p>
    </section>

    <div v-if="loading" class="state" role="status">Loading the example…</div>

    <div v-else-if="finished" class="state done el-card">
      <h3>Examples done</h3>
      <p>
        Your overall judgment matched the team's on
        <strong>{{ correctCount }}</strong> of {{ total }}.
      </p>
      <button type="button" class="el-btn el-btn--primary" @click="emit('done')">
        Start assessing
      </button>
    </div>

    <!-- No skip. The server will not serve or record a judgment while a
         published set waits for this expert, so a skip could only ever lead
         to an empty queue that looked complete. -->
    <div v-else-if="!currentCase" class="state el-card">
      <p>The next example could not be loaded.</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button type="button" class="el-btn el-btn--ghost" @click="fetchNext">Try again</button>
    </div>

    <template v-else>
      <section class="el-card statement-card">
        <div class="meta-row">
          <span class="badge">Example {{ caseNumber }} of {{ total }}</span>
          <span class="badge muted">{{ prettyCategory(currentCase.category) }}</span>
        </div>
        <p class="statement">{{ currentCase.statement }}</p>
      </section>

      <JudgmentForm
        v-if="!reveal"
        :item="currentCase"
        :allow-references="false"
        :submitting="checking"
        :error="error"
        submit-label="Check against the team's answer"
        @submit="check"
      />

      <section v-else ref="revealRef" class="el-card reveal" tabindex="-1"
               :class="reveal.correct ? 'ok' : 'miss'" role="status" data-test="reveal">
        <h3>{{ reveal.correct ? 'Your judgment matches the team’s' : 'Your judgment differs from the team’s' }}</h3>
        <dl class="compare">
          <dt>Evidence strength</dt>
          <dd>
            Team: <strong>{{ strengthLabel(reveal.reference.evidence_strength) }}</strong>
            <span v-if="!reveal.strength_matches"> · you: {{ strengthLabel(given?.evidence_strength) }}</span>
          </dd>
          <dt>Direction</dt>
          <dd>
            Team: <strong>{{ consensusLabel(reveal.reference.consensus_direction) }}</strong>
            <span v-if="!reveal.consensus_matches"> · you: {{ consensusLabel(given?.consensus_direction) }}</span>
          </dd>
          <template v-if="reveal.passages_compared">
            <dt>Passages</dt>
            <dd>
              You agreed on {{ reveal.passages_agreed }} of the
              {{ reveal.passages_compared }} passages the team labelled.
            </dd>
          </template>
        </dl>
        <p class="explain">{{ reveal.reference.explanation }}</p>
        <button type="button" class="el-btn el-btn--primary" @click="next">
          {{ completed >= total ? 'Finish' : 'Next example' }}
        </button>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import api from '@/utils/api'
import type {
  CalibrationFeedback, CalibrationItem, CalibrationStatus,
} from '@/types/elicitation.generated'
import JudgmentForm, { type JudgmentSubmit } from './JudgmentForm.vue'
import { buildCalibrationDecision, type EvidenceDraft } from './decision'
import { CONSENSUS_OPTIONS, STRENGTH_OPTIONS, prettyCategory } from './taskOptions'

const emit = defineEmits<{ (e: 'done'): void }>()

const loading = ref(true)
const checking = ref(false)
const error = ref('')
const currentCase = ref<CalibrationItem | null>(null)
const reveal = ref<CalibrationFeedback | null>(null)
const given = ref<EvidenceDraft | null>(null)
const completed = ref(0)
const total = ref(0)
const correctCount = ref(0)
const finished = ref(false)
// Fixed when a case loads, so the number does not move on while the answer
// to that same case is on screen.
const caseNumber = ref(1)
const revealRef = ref<HTMLElement | null>(null)
let caseStarted = Date.now()

function strengthLabel(v: number | null | undefined) {
  return STRENGTH_OPTIONS.find((o) => o.value === v)?.label ?? '—'
}
function consensusLabel(v: number | null | undefined) {
  return CONSENSUS_OPTIONS.find((o) => o.value === v)?.label ?? '—'
}

async function refreshStatus() {
  try {
    const { data } = await api.get<CalibrationStatus>('/elicitation/calibration/status')
    total.value = data.total
    completed.value = data.completed
    correctCount.value = data.correct
  } catch { /* the counts are a courtesy; the case flow does not depend on them */ }
}

async function fetchNext() {
  loading.value = true
  error.value = ''
  reveal.value = null
  given.value = null
  try {
    const { data } = await api.get<CalibrationItem | null>('/elicitation/calibration/next')
    if (!data) {
      finished.value = true
      currentCase.value = null
      await refreshStatus()
    } else {
      currentCase.value = data
      completed.value = data.completed
      caseNumber.value = data.completed + 1
      total.value = data.total
      caseStarted = Date.now()
    }
  } catch (e: any) {
    currentCase.value = null
    error.value = e?.response?.data?.detail || ''
  } finally {
    loading.value = false
  }
}

async function check(j: JudgmentSubmit) {
  const c = currentCase.value
  if (!c) return
  checking.value = true
  error.value = ''
  try {
    const { data } = await api.post<CalibrationFeedback>(
      '/elicitation/calibration/decide',
      buildCalibrationDecision(c, j.draft, j.common,
                               Math.round((Date.now() - caseStarted) / 1000)))
    given.value = j.draft
    reveal.value = data
    if (data.correct) correctCount.value += 1
    completed.value = data.completed
    total.value = data.total
    await nextTick()
    revealRef.value?.focus()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not check that answer'
  } finally {
    checking.value = false
  }
}

function next() {
  if (total.value && completed.value >= total.value) {
    finished.value = true
    refreshStatus()
    return
  }
  fetchNext()
}

onMounted(() => { refreshStatus(); fetchNext() })
</script>

<style scoped>
.calibration { display: flex; flex-direction: column; gap: var(--el-s5); }
.cal-head { display: flex; justify-content: space-between; align-items: center; gap: var(--el-s4); }
.cal-head h2 { font-size: var(--el-fs-xl); font-weight: 700; color: var(--el-ink); }
.intro p { margin-top: var(--el-s2); color: var(--el-ink-2); line-height: var(--el-lh); max-width: 70ch; font-size: var(--el-fs-base); }
.cal-progress { background: var(--el-bg-3); border-radius: var(--el-radius-sm); padding: var(--el-s1) var(--el-s3); font-size: var(--el-fs-sm); color: var(--el-ink-2); white-space: nowrap; }
.meta-row { display: flex; gap: var(--el-s2); flex-wrap: wrap; margin-bottom: var(--el-s3); }
.badge { background: var(--el-info-bg); color: var(--el-info-ink); border-radius: var(--el-radius-sm); padding: 0.15rem 0.5rem; font-size: var(--el-fs-xs); font-weight: 600; }
.badge.muted { background: var(--el-bg-3); color: var(--el-ink-2); font-weight: 500; }
.statement { font-size: 1.2rem; line-height: 1.6; color: var(--el-ink); font-weight: 500; }

.reveal:focus { outline: none; }
.reveal h3 { font-size: var(--el-fs-lg); font-weight: 600; color: var(--el-ink); }
.reveal.ok { border-color: #bbf7d0; background: #f0fdf4; }
.reveal.miss { border-color: #fde68a; background: #fffbeb; }
.compare { display: grid; grid-template-columns: max-content 1fr; gap: var(--el-s1) var(--el-s4); margin: var(--el-s3) 0; font-size: var(--el-fs-base); }
.compare dt { color: var(--el-ink-3); }
.compare dd { margin: 0; color: var(--el-ink-2); }
.explain { font-size: var(--el-fs-base); color: var(--el-ink-2); line-height: var(--el-lh); margin-bottom: var(--el-s4); max-width: 70ch; }
.state { padding: var(--el-s6) var(--el-s4); text-align: center; color: var(--el-ink-3); }
.state.done { display: flex; flex-direction: column; align-items: center; gap: var(--el-s3); }
.state h3 { font-size: var(--el-fs-lg); color: var(--el-ink-2); font-weight: 600; }
.error { color: var(--el-danger); font-size: var(--el-fs-sm); }
</style>
