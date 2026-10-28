<template>
  <section class="el-card cal-admin" aria-labelledby="cal-admin-head">
    <div class="card-head">
      <h2 id="cal-admin-head">Calibration examples</h2>
      <span v-if="list?.published_version" class="pill">v{{ list.published_version }} published</span>
      <span v-else class="pill ghost">none published</span>
    </div>
    <p class="note">
      Three to five real evidence items the team picks, each with the answer
      the team agrees on and a short explanation. While none is published,
      experts are not held up: their judgments are recorded as made before
      calibration. Publishing asks every expert to work the set once before
      their next fact, and takes those facts out of the measured queue for
      good — each was shown with its answer.
    </p>

    <LoadState v-if="loadError" :error="loadError" @retry="load" />

    <ul v-if="list?.sets.length" class="versions">
      <li v-for="s in list.sets" :key="s.version" class="version" :class="s.status">
        <div class="v-head">
          <strong>v{{ s.version }}</strong>
          <span class="status">{{ s.status }}</span>
          <span class="muted">{{ s.items.length }} item{{ s.items.length === 1 ? '' : 's' }}</span>
          <span v-if="s.note" class="muted">· {{ s.note }}</span>
          <span class="spacer" />
          <template v-if="s.status === 'draft'">
            <button type="button" class="el-btn el-btn--ghost sm" @click="edit(s)">Edit</button>
            <button type="button" class="el-btn el-btn--primary sm" :disabled="busy"
                    @click="publish(s)">Publish</button>
            <button type="button" class="el-btn el-btn--ghost sm" :disabled="busy"
                    @click="remove(s)">Delete</button>
          </template>
        </div>
        <ol class="items">
          <li v-for="it in s.items" :key="it.evidence_set_id">
            <span class="mono">#{{ it.sf_number }} · {{ corpusName(it.corpus_id) }}</span>
            — {{ consensusLabel(it.reference.consensus_direction) }},
            {{ strengthLabel(it.reference.evidence_strength).toLowerCase() }} evidence
            <span class="clamp">{{ it.statement }}</span>
          </li>
        </ol>
      </li>
    </ul>

    <button v-if="!editor" type="button" class="el-btn el-btn--ghost" @click="startNew">
      New draft
    </button>

    <!-- ── Draft editor ───────────────────────────────────────────── -->
    <div v-if="editor" class="editor" data-test="cal-editor">
      <h3>{{ editor.version ? `Edit draft v${editor.version}` : 'New draft' }}</h3>
      <label class="field">
        <span class="lbl">Note (optional)</span>
        <input v-model="editor.note" class="input" placeholder="e.g. agreed at the 4 November call" />
      </label>

      <div v-for="(it, i) in editor.items" :key="i" class="item-editor">
        <div class="item-head">
          <strong>Example {{ i + 1 }}</strong>
          <button type="button" class="link" @click="editor.items.splice(i, 1)">Remove</button>
        </div>
        <label class="field">
          <span class="lbl">Evidence item</span>
          <select v-model="it.evidence_set_id" class="input" @change="loadPassages(it)">
            <option value="" disabled>Choose a fact and corpus…</option>
            <option v-for="o in options" :key="o.evidence_set_id" :value="o.evidence_set_id">
              #{{ o.sf_number }} {{ corpusName(o.corpus_id) }} — {{ o.statement.slice(0, 80) }}{{ o.statement.length > 80 ? '…' : '' }}{{ o.n_judgments ? ` (${o.n_judgments} judgments already)` : '' }}
            </option>
          </select>
        </label>
        <p v-if="judgedWarning(it)" class="warn">{{ judgedWarning(it) }}</p>

        <div class="grid">
          <fieldset class="field">
            <legend class="lbl">Agreed evidence strength</legend>
            <label v-for="o in STRENGTH_OPTIONS" :key="o.value" class="radio">
              <input v-model.number="it.evidence_strength" type="radio" :value="o.value"
                     :name="`str-${i}`" /> {{ o.label }}
            </label>
          </fieldset>
          <fieldset class="field">
            <legend class="lbl">Agreed direction</legend>
            <label v-for="o in CONSENSUS_OPTIONS" :key="o.value" class="radio">
              <input v-model.number="it.consensus_direction" type="radio" :value="o.value"
                     :name="`con-${i}`" /> {{ o.label }}
            </label>
          </fieldset>
        </div>
        <label class="field">
          <span class="lbl">Explanation shown to experts</span>
          <textarea v-model="it.explanation" class="input" rows="3"
                    placeholder="Why this is the answer: which passages carry it, and what an expert should know beyond them."></textarea>
        </label>

        <details v-if="it.passages.length" class="passages">
          <summary>Agreed passage labels (optional) — {{ labelledCount(it) }} set</summary>
          <ol>
            <li v-for="p in it.passages" :key="p.index">
              <select v-model="it.passage_directions[String(p.index)]" class="input sm"
                      :aria-label="`Agreed label for passage ${p.index + 1}`">
                <option value="">—</option>
                <option value="supports">Supports</option>
                <option value="contradicts">Contradicts</option>
                <option value="neutral">Neutral</option>
              </select>
              <span class="p-text">{{ p.text.slice(0, 220) }}{{ p.text.length > 220 ? '…' : '' }}</span>
            </li>
          </ol>
        </details>
      </div>

      <div class="editor-actions">
        <button type="button" class="el-btn el-btn--ghost" :disabled="editor.items.length >= 8"
                @click="addItem">Add an example</button>
        <span class="spacer" />
        <button type="button" class="el-btn el-btn--ghost" @click="editor = null">Cancel</button>
        <button type="button" class="el-btn el-btn--primary" :disabled="!!editorProblem || busy"
                @click="save">Save draft</button>
      </div>
      <p class="hint" role="status">{{ editorProblem || '' }}</p>
    </div>
    <p v-if="actionError" class="err" role="alert">{{ actionError }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import api from '@/utils/api'
import LoadState from '@/components/enrolment/LoadState.vue'
import { CONSENSUS_OPTIONS, STRENGTH_OPTIONS, corpusName } from './taskOptions'
import type {
  CalibrationSet, CalibrationSetDraft, CalibrationSetList, EvidencePassage,
  EvidenceSetDetail, EvidenceSetOption, EvidenceSetOptionList, PassageDirection,
} from '@/types/elicitation.generated'

interface ItemDraft {
  evidence_set_id: string
  evidence_strength: number | null
  consensus_direction: number | null
  explanation: string
  passage_directions: Record<string, PassageDirection | ''>
  passages: EvidencePassage[]
}

const list = ref<CalibrationSetList | null>(null)
const options = ref<EvidenceSetOption[]>([])
const loadError = ref('')
const actionError = ref('')
const busy = ref(false)
const editor = ref<{ version: number | null; note: string; items: ItemDraft[] } | null>(null)

function strengthLabel(v: number | null | undefined) {
  return STRENGTH_OPTIONS.find((o) => o.value === v)?.label ?? '—'
}
function consensusLabel(v: number | null | undefined) {
  return CONSENSUS_OPTIONS.find((o) => o.value === v)?.label ?? '—'
}
function blankItem(): ItemDraft {
  return { evidence_set_id: '', evidence_strength: null, consensus_direction: null,
           explanation: '', passage_directions: {}, passages: [] }
}
function labelledCount(it: ItemDraft) {
  return Object.values(it.passage_directions).filter(Boolean).length
}
function judgedWarning(it: ItemDraft): string {
  const o = options.value.find((x) => x.evidence_set_id === it.evidence_set_id)
  return o?.n_judgments
    ? `This fact already has ${o.n_judgments} judgment(s). Publishing takes it out of the measured queue, so those stop counting toward the comparison.`
    : ''
}

const editorProblem = computed(() => {
  const e = editor.value
  if (!e) return null
  if (!e.items.length) return 'Add at least one example'
  const ids = e.items.map((i) => i.evidence_set_id)
  if (ids.some((id) => !id)) return 'Choose an evidence item for every example'
  if (new Set(ids).size !== ids.length) return 'The same evidence item is listed twice'
  for (const [n, it] of e.items.entries()) {
    if (!it.evidence_strength || !it.consensus_direction) return `Example ${n + 1}: give both agreed scores`
    if (!it.explanation.trim()) return `Example ${n + 1}: write the explanation`
  }
  return null
})

async function load() {
  loadError.value = ''
  try {
    const [sets, opts] = await Promise.all([
      api.get<CalibrationSetList>('/elicitation/calibration/sets'),
      api.get<EvidenceSetOptionList>('/elicitation/calibration/evidence-sets'),
    ])
    list.value = sets.data
    options.value = opts.data.sets
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail || 'Could not load the calibration sets'
  }
}

async function loadPassages(it: ItemDraft) {
  it.passages = []
  it.passage_directions = {}
  if (!it.evidence_set_id) return
  try {
    const { data } = await api.get<EvidenceSetDetail>(
      `/elicitation/calibration/evidence-sets/${encodeURIComponent(it.evidence_set_id)}`)
    it.passages = data.passages
  } catch { /* passage labels are optional; the scores are the answer */ }
}

function startNew() {
  editor.value = { version: null, note: '', items: [blankItem(), blankItem(), blankItem()] }
}
function addItem() {
  editor.value?.items.push(blankItem())
}
function edit(s: CalibrationSet) {
  editor.value = {
    version: s.version,
    note: s.note ?? '',
    items: s.items.map((it) => ({
      evidence_set_id: it.evidence_set_id,
      evidence_strength: it.reference.evidence_strength,
      consensus_direction: it.reference.consensus_direction,
      explanation: it.reference.explanation,
      passage_directions: { ...(it.reference.passage_directions ?? {}) },
      passages: [],
    })),
  }
  for (const it of editor.value.items) loadPassages(it).then(() => {
    const s0 = s.items.find((x) => x.evidence_set_id === it.evidence_set_id)
    it.passage_directions = { ...(s0?.reference.passage_directions ?? {}) }
  })
}

function payload(): CalibrationSetDraft {
  const e = editor.value!
  return {
    note: e.note.trim() || null,
    items: e.items.map((it) => ({
      evidence_set_id: it.evidence_set_id,
      reference: {
        evidence_strength: it.evidence_strength!,
        consensus_direction: it.consensus_direction!,
        explanation: it.explanation.trim(),
        passage_directions: Object.fromEntries(
          Object.entries(it.passage_directions).filter(([, v]) => !!v),
        ) as Record<string, PassageDirection>,
      },
    })),
  }
}

async function run(fn: () => Promise<unknown>) {
  busy.value = true
  actionError.value = ''
  try {
    await fn()
    await load()
  } catch (e: any) {
    actionError.value = e?.response?.data?.detail || 'That did not work'
  } finally {
    busy.value = false
  }
}

function save() {
  if (editorProblem.value || !editor.value) return
  const v = editor.value.version
  run(async () => {
    await (v ? api.put(`/elicitation/calibration/sets/${v}`, payload())
             : api.post('/elicitation/calibration/sets', payload()))
    editor.value = null
  })
}

function publish(s: CalibrationSet) {
  const ok = window.confirm(
    `Publish v${s.version}? Every expert works these ${s.items.length} example(s) once before their next fact, and these facts leave the measured queue.`)
  if (ok) run(() => api.post(`/elicitation/calibration/sets/${s.version}/publish`))
}

function remove(s: CalibrationSet) {
  if (window.confirm(`Delete draft v${s.version}?`)) {
    run(() => api.delete(`/elicitation/calibration/sets/${s.version}`))
  }
}

onMounted(load)
</script>

<style scoped>
.card-head { display: flex; align-items: center; gap: var(--el-s2); margin-bottom: var(--el-s2); }
.card-head h2 { font-size: var(--el-fs-lg); font-weight: 600; color: var(--el-ink); }
.pill { background: var(--el-accent); color: #fff; border-radius: 999px; padding: 0.1rem 0.5rem; font-size: var(--el-fs-xs); font-weight: 600; }
.pill.ghost { background: var(--el-bg-3); color: var(--el-ink-2); }
.note { font-size: var(--el-fs-sm); color: var(--el-ink-2); line-height: var(--el-lh); background: var(--el-bg-2); border-radius: var(--el-radius-sm); padding: var(--el-s3); margin-bottom: var(--el-s4); }
.versions { list-style: none; padding: 0; margin: 0 0 var(--el-s4); display: flex; flex-direction: column; gap: var(--el-s3); }
.version { border: 1px solid var(--el-line); border-radius: var(--el-radius-sm); padding: var(--el-s3); }
.version.published { border-left: 3px solid var(--el-accent); }
.version.retired { opacity: 0.7; }
.v-head { display: flex; align-items: center; gap: var(--el-s2); flex-wrap: wrap; }
.status { text-transform: uppercase; font-size: var(--el-fs-xs); letter-spacing: 0.04em; color: var(--el-ink-3); }
.spacer { flex: 1; }
.items { margin: var(--el-s2) 0 0; padding-left: 1.2rem; font-size: var(--el-fs-sm); color: var(--el-ink-2); display: flex; flex-direction: column; gap: var(--el-s1); }
.mono { font-family: ui-monospace, monospace; font-size: var(--el-fs-xs); }
.clamp { display: block; color: var(--el-ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 70ch; }
.muted { color: var(--el-ink-4); font-size: var(--el-fs-sm); }
.sm { min-height: 2rem; padding: 0 var(--el-s3); font-size: var(--el-fs-sm); }

.editor { border-top: 1px solid var(--el-line); margin-top: var(--el-s4); padding-top: var(--el-s4); display: flex; flex-direction: column; gap: var(--el-s3); }
.editor h3 { font-size: var(--el-fs-base); font-weight: 600; }
.item-editor { border: 1px solid var(--el-line); border-radius: var(--el-radius-sm); padding: var(--el-s3); display: flex; flex-direction: column; gap: var(--el-s2); }
.item-head { display: flex; justify-content: space-between; align-items: center; }
.field { display: flex; flex-direction: column; gap: var(--el-s1); border: none; padding: 0; margin: 0; }
.lbl { font-size: var(--el-fs-sm); font-weight: 600; color: var(--el-ink-2); }
.input { padding: var(--el-s2); border: 1px solid var(--el-line-2); border-radius: var(--el-radius-sm); font-size: var(--el-fs-sm); font-family: inherit; max-width: 100%; }
.input.sm { padding: 0.15rem var(--el-s1); }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--el-s3); }
@media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
.radio { font-size: var(--el-fs-sm); display: flex; align-items: center; gap: var(--el-s1); min-height: 2rem; }
.passages summary { cursor: pointer; font-size: var(--el-fs-sm); color: var(--el-ink-2); }
.passages ol { margin-top: var(--el-s2); display: flex; flex-direction: column; gap: var(--el-s2); font-size: var(--el-fs-xs); }
.passages li { display: flex; gap: var(--el-s2); align-items: flex-start; }
.p-text { color: var(--el-ink-3); line-height: 1.45; }
.warn { font-size: var(--el-fs-xs); color: var(--el-warn-ink); background: var(--el-warn-bg); border-radius: var(--el-radius-sm); padding: var(--el-s1) var(--el-s2); }
.editor-actions { display: flex; gap: var(--el-s2); align-items: center; flex-wrap: wrap; }
.link { background: none; border: none; color: var(--el-danger); cursor: pointer; font-size: var(--el-fs-sm); text-decoration: underline; }
.hint { font-size: var(--el-fs-xs); color: var(--el-warn-ink); min-height: 1.3em; }
.err { color: var(--el-danger); font-size: var(--el-fs-sm); margin-top: var(--el-s2); }
</style>
