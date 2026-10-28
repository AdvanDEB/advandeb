<template>
  <div class="elicitation-view">
    <header class="page-header">
      <div>
        <h1>Assess stylized facts</h1>
        <p class="sub">
          Judge each fact from the passages shown and from your own knowledge.
        </p>
      </div>
      <div class="head-right">
        <span v-if="progress" class="progress-chip" data-test="progress">
          <strong>{{ progress.completed_by_me }}</strong> assessed by you
        </span>
        <button type="button" class="el-btn el-btn--ghost" :aria-expanded="showHow"
                @click="showHow = !showHow">How this works</button>
        <button type="button" class="icon-btn" title="Keyboard shortcuts (?)"
                aria-label="Keyboard shortcuts" @click="showShortcuts = true">?</button>
      </div>
    </header>

    <HowItWorks
      v-if="showHow && guidelines?.how_it_works?.length"
      :steps="guidelines.how_it_works"
      :version="guidelines.version"
      @close="closeHow"
    />

    <div v-if="state === 'loading'" class="state" role="status">Loading…</div>

    <div v-else-if="state === 'error'" class="state el-card err">
      <h2>Could not load the next fact</h2>
      <p class="muted-text">{{ error }}</p>
      <button type="button" class="el-btn el-btn--primary" @click="load">Try again</button>
    </div>

    <!-- The server serves and records nothing while a published calibration
         set waits for this expert (docs/10 §5.3), so there is no "skip".
         With no set published there is nothing to wait for. -->
    <CalibrationFlow v-else-if="state === 'calibration'" @done="load" />

    <div v-else-if="state === 'exhausted'" class="state done el-card">
      <h2>Nothing to assess right now</h2>
      <p>
        You have assessed every fact the queue holds for you — or the rest
        are facts you authored, which you are never given.
      </p>
      <button type="button" class="el-btn el-btn--ghost" @click="load">Check again</button>
    </div>

    <div v-else-if="item" class="work">
      <section ref="statementRef" class="el-card statement-card" aria-labelledby="fact-head"
               tabindex="-1">
        <div class="meta-row">
          <span class="badge">Fact #{{ item.sf_number }}</span>
          <span class="badge muted">{{ prettyCategory(item.category) }}</span>
          <!-- No corpus badge: the corpus of origin stays hidden from experts
               (advandeb_methods docs/02 §5). Each passage's own citation is
               shown; which retrieval corpus it came from is not. -->
        </div>
        <h2 id="fact-head" class="sr-only">The fact</h2>
        <p class="statement">{{ item.statement }}</p>
      </section>

      <JudgmentForm
        :item="item"
        :submitting="submitting"
        :error="error"
        @submit="submit"
      />
      <button v-if="stale" type="button" class="el-btn el-btn--ghost" @click="load">
        Load the next fact
      </button>

      <GuidelinesPanel task="evidence" />
    </div>

    <button type="button" class="el-btn el-btn--ghost toggle-history"
            :aria-expanded="showHistory" @click="showHistory = !showHistory">
      {{ showHistory ? 'Hide' : 'Show' }} your past assessments
    </button>
    <HistoryPanel v-if="showHistory" ref="historyRef" />

    <ShortcutsOverlay v-if="showShortcuts" @close="showShortcuts = false" />
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import api from '@/utils/api'
import CalibrationFlow from '@/components/elicitation/CalibrationFlow.vue'
import GuidelinesPanel from '@/components/elicitation/GuidelinesPanel.vue'
import HistoryPanel from '@/components/elicitation/HistoryPanel.vue'
import HowItWorks from '@/components/elicitation/HowItWorks.vue'
import JudgmentForm, { type JudgmentSubmit } from '@/components/elicitation/JudgmentForm.vue'
import ShortcutsOverlay from '@/components/elicitation/ShortcutsOverlay.vue'
import { prettyCategory } from '@/components/elicitation/taskOptions'
import { buildDecision } from '@/components/elicitation/decision'
import type {
  CalibrationStatus, ElicitationProgress, Guidelines, QueueItem,
} from '@/types/elicitation.generated'

type State = 'loading' | 'error' | 'calibration' | 'working' | 'exhausted'

// Remembered per browser, so the introduction opens on an expert's first
// visit and stays out of the way afterwards.
const HOW_SEEN_KEY = 'advandeb.elicitation.howSeen'

const state = ref<State>('loading')
const item = ref<QueueItem | null>(null)
const progress = ref<ElicitationProgress | null>(null)
const guidelines = ref<Guidelines | null>(null)
const submitting = ref(false)
const error = ref('')
// The queue moved on under this item (409): someone completed it, or it is no
// longer this expert's head. Offer the next one instead of a dead end.
const stale = ref(false)
const showHow = ref(false)
const showShortcuts = ref(false)
const showHistory = ref(false)
const historyRef = ref<InstanceType<typeof HistoryPanel> | null>(null)
const statementRef = ref<HTMLElement | null>(null)

// Time on task is captured automatically — it is the throughput figure the
// method needs, and asking experts to record it would be unreliable and
// irritating. Paused on blur so a coffee break is not counted as thinking.
const elapsed = ref(0)
let ticker: number | undefined
let focused = true

function readHowSeen(): boolean {
  try { return localStorage.getItem(HOW_SEEN_KEY) === '1' } catch { return false }
}
function closeHow() {
  showHow.value = false
  try { localStorage.setItem(HOW_SEEN_KEY, '1') } catch { /* private mode */ }
}

async function loadGuidelines() {
  try {
    guidelines.value = (await api.get<Guidelines>('/elicitation/guidelines')).data
  } catch {
    guidelines.value = null
  }
}

async function load() {
  state.value = 'loading'
  error.value = ''
  stale.value = false
  try {
    // Not waved through on failure: the server gates /next on calibration,
    // so a client that guessed wrong only ever showed an empty queue that
    // looked finished.
    const { data: cal } = await api.get<CalibrationStatus>('/elicitation/calibration/status')
    if (cal.required) { state.value = 'calibration'; return }

    const [next, prog] = await Promise.all([
      api.get<QueueItem | null>('/elicitation/next'),
      api.get<ElicitationProgress>('/elicitation/progress').catch(() => ({ data: null })),
    ])
    progress.value = prog.data
    item.value = next.data || null
    elapsed.value = 0
    state.value = item.value ? 'working' : 'exhausted'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not load the next fact'
    state.value = 'error'
  }
}

async function submit(j: JudgmentSubmit) {
  if (!item.value || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    await api.post('/elicitation/decide', buildDecision(item.value, j.draft, j.common, {
      time_spent_s: elapsed.value,
      reference_ids: j.referenceIds,
    }))
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not save'
    stale.value = e?.response?.status === 409
    submitting.value = false
    return
  }
  submitting.value = false
  await load()
  // The next fact starts at the top; focus moves there so a keyboard or
  // screen-reader user lands on the new statement, not at the old form's end.
  await nextTick()
  statementRef.value?.focus()
  historyRef.value?.refresh?.()
}

function onKey(e: KeyboardEvent) {
  if (showShortcuts.value && e.key === 'Escape') { showShortcuts.value = false; return }
  const typing = e.target instanceof HTMLTextAreaElement
    || (e.target instanceof HTMLInputElement && e.target.type !== 'radio')
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return
  if (e.key === '?') { showShortcuts.value = !showShortcuts.value; return }
  if (e.key.toLowerCase() === 'h' && state.value === 'working') showHistory.value = !showHistory.value
}

function onFocus() { focused = true }
function onBlur() { focused = false }

onMounted(() => {
  showHow.value = !readHowSeen()
  loadGuidelines()
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
.elicitation-view { padding: var(--el-s5) var(--el-s6); display: flex; flex-direction: column; gap: var(--el-s5); max-width: 920px; }
@media (max-width: 640px) { .elicitation-view { padding: var(--el-s4) var(--el-s3); } }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--el-s4); flex-wrap: wrap; }
.page-header h1 { font-size: var(--el-fs-xl); font-weight: 700; color: var(--el-ink); }
.sub { color: var(--el-ink-3); font-size: var(--el-fs-base); margin-top: var(--el-s1); max-width: 52ch; }
.head-right { display: flex; align-items: center; gap: var(--el-s2); flex-wrap: wrap; }
.icon-btn { width: var(--el-touch); height: var(--el-touch); border-radius: var(--el-radius-sm); border: 1px solid var(--el-line-2); background: var(--el-bg); cursor: pointer; color: var(--el-ink-2); font-weight: 600; }
.progress-chip { background: var(--el-bg-3); border-radius: var(--el-radius-sm); padding: var(--el-s2) var(--el-s3); font-size: var(--el-fs-sm); color: var(--el-ink-2); white-space: nowrap; }

.work { display: flex; flex-direction: column; gap: var(--el-s5); }
.meta-row { display: flex; gap: var(--el-s2); flex-wrap: wrap; margin-bottom: var(--el-s3); }
.badge { background: var(--el-info-bg); color: var(--el-info-ink); border-radius: var(--el-radius-sm); padding: 0.15rem 0.5rem; font-size: var(--el-fs-xs); font-weight: 600; }
.badge.muted { background: var(--el-bg-3); color: var(--el-ink-2); font-weight: 500; }
.statement-card:focus { outline: none; }
.statement-card:focus-visible { outline: 2px solid var(--el-accent); outline-offset: 2px; }
.statement { font-size: 1.2rem; line-height: 1.6; color: var(--el-ink); font-weight: 500; }

.toggle-history { align-self: flex-start; }
.state { padding: var(--el-s7) var(--el-s4); text-align: center; color: var(--el-ink-3); }
.state.done, .state.err { display: flex; flex-direction: column; align-items: center; gap: var(--el-s3); }
.state h2 { font-size: var(--el-fs-lg); color: var(--el-ink-2); font-weight: 600; }
.muted-text { color: var(--el-ink-3); font-size: var(--el-fs-sm); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
