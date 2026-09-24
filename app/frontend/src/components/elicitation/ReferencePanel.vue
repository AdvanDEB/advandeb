<template>
  <section class="card refs-card">
    <button class="disclose" @click="open = !open">
      {{ open ? '▾' : '▸' }} Cite a publication
      <span v-if="refs.length" class="count">{{ refs.length }}</span>
      <span class="hint">— evidence you know of, whether or not the system found it</span>
    </button>

    <div v-if="open" class="body">
      <p class="lede">
        A DOI you consider to support or oppose this fact. It is recorded as
        <strong>your</strong> assertion and never changes the automated score.
        If the paper is missing from the corpus it is queued for ingestion, and
        the panel re-reads this fact.
      </p>

      <div class="form">
        <input
          v-model="doi"
          class="doi"
          placeholder="10.1234/abc or https://doi.org/10.1234/abc"
          :disabled="saving"
          @keydown.enter.prevent="submit"
        />
        <div class="dir">
          <button
            v-for="d in directions" :key="d.value"
            :class="['pill', { active: direction === d.value }]"
            :disabled="saving"
            @click="direction = d.value"
          >{{ d.label }}</button>
        </div>
      </div>
      <input
        v-model="note"
        class="note"
        placeholder="Optional — why does it bear on this fact?"
        :disabled="saving"
      />
      <div class="actions">
        <button class="primary" :disabled="!canSubmit || saving" @click="submit">
          {{ saving ? 'Resolving…' : 'Add reference' }}
        </button>
        <span v-if="err" class="err">{{ err }}</span>
      </div>

      <ul v-if="refs.length" class="list">
        <li v-for="r in refs" :key="r._id" class="ref">
          <div class="ref-head">
            <span :class="['dirbadge', r.direction]">{{ r.direction }}</span>
            <a :href="'https://doi.org/' + r.doi" target="_blank" rel="noopener"
               class="doi-link">{{ r.doi }}</a>
            <button class="rm" title="Remove" @click="remove(r._id)">×</button>
          </div>
          <div v-if="r.resolution && r.resolution.resolved_title" class="title">
            {{ r.resolution.resolved_title }}
            <span v-if="r.resolution.resolved_year">({{ r.resolution.resolved_year }})</span>
          </div>
          <div :class="['status', statusClass(r.resolution && r.resolution.status)]">
            {{ statusLabel(r.resolution && r.resolution.status) }}
          </div>

          <div v-if="r.resolution && r.resolution.status === 'in_corpus_retrieved'" class="panel-said">
            <strong>The panel read this paper.</strong>
            <span v-if="r.resolution.agrees_with_panel === false">
              It reached a different conclusion from yours, so this is a
              disagreement about judgment rather than about retrieval.
            </span>
            <span v-else-if="r.resolution.agrees_with_panel === true">
              It agreed with you.
            </span>
            <ul class="labels">
              <li v-for="(ps, scope) in (r.resolution.panel_labels || {})" :key="scope">
                <em>{{ scope }}</em>: {{ labelsOf(ps) }}
              </li>
            </ul>
          </div>
          <div v-if="r.note" class="note-shown">“{{ r.note }}”</div>
        </li>
      </ul>

      <p v-if="evidence && evidence.n_recall_misses" class="miss">
        {{ evidence.n_recall_misses }} of the papers cited here
        {{ evidence.n_recall_misses === 1 ? 'was' : 'were' }} already in the
        corpus but never surfaced by retrieval.
      </p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import api from '@/utils/api'

const props = defineProps<{ sfNumber: number; statementSha256: string }>()

const open = ref(false)
const doi = ref('')
const direction = ref<'supports' | 'opposes'>('supports')
const note = ref('')
const saving = ref(false)
const err = ref('')
const refs = ref<any[]>([])
const evidence = ref<any>(null)

const directions = [
  { value: 'supports' as const, label: 'Supports' },
  { value: 'opposes' as const, label: 'Opposes' },
]

const canSubmit = computed(() => doi.value.trim().includes('/'))

// Each status means something different and the wording has to carry it:
// "not in corpus" and "not retrieved" have opposite remedies.
const LABELS: Record<string, string> = {
  pending: 'Resolving…',
  not_in_corpus: 'Not in the corpus — queued for ingestion, the panel will re-read this fact',
  in_corpus_not_retrieved: 'In the corpus, but retrieval never surfaced it — recorded as a retrieval miss',
  in_corpus_retrieved: 'Already read by the panel',
  in_corpus_retrieval_unknown: 'In the corpus; whether retrieval surfaced it could not be determined',
  unresolvable: 'Could not be resolved',
}

function statusLabel(s?: string | null) {
  return LABELS[s || 'pending'] || 'Resolving…'
}
function statusClass(s?: string | null) {
  if (s === 'in_corpus_not_retrieved') return 'miss'
  if (s === 'not_in_corpus') return 'gap'
  if (s === 'in_corpus_retrieved') return 'seen'
  return 'unknown'
}
function labelsOf(ps: any) {
  return Array.isArray(ps) ? ps.map((p: any) => p.label).join(', ') : ''
}

async function load() {
  if (!props.sfNumber) return
  try {
    const { data } = await api.get('/elicitation/references', {
      params: { sf_number: props.sfNumber, mine_only: true },
    })
    refs.value = data.references || []
    evidence.value = data.asserted_evidence || null
  } catch {
    // Secondary to the judgment: a failure here must never block the form.
    refs.value = []
    evidence.value = null
  }
}

async function submit() {
  if (!canSubmit.value) return
  saving.value = true
  err.value = ''
  try {
    await api.post('/elicitation/references', {
      sf_number: props.sfNumber,
      statement_sha256: props.statementSha256,
      doi: doi.value.trim(),
      direction: direction.value,
      note: note.value.trim() || null,
    })
    doi.value = ''
    note.value = ''
    await load()
  } catch (e: any) {
    err.value = (e && e.response && e.response.data && e.response.data.detail)
      || 'Could not add that reference'
  } finally {
    saving.value = false
  }
}

async function remove(id: string) {
  try {
    await api.delete('/elicitation/references/' + id)
    await load()
  } catch (e: any) {
    err.value = (e && e.response && e.response.data && e.response.data.detail)
      || 'Could not remove'
  }
}

watch(() => props.sfNumber,
      () => { refs.value = []; evidence.value = null; load() },
      { immediate: true })
</script>

<style scoped>
.refs-card { padding: 0.6rem 1rem; }
.disclose { background: none; border: none; cursor: pointer; font-size: 0.85rem; color: #4b5563; padding: 0.2rem 0; text-align: left; width: 100%; }
.disclose .hint { color: #9ca3af; }
.disclose .count { background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 0 0.4rem; font-size: 0.72rem; margin-left: 0.3rem; }
.body { margin-top: 0.7rem; }
.lede { font-size: 0.8rem; color: #6b7280; line-height: 1.5; margin-bottom: 0.6rem; }
.form { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
.doi { flex: 1 1 18rem; padding: 0.45rem 0.6rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.85rem; font-family: ui-monospace, monospace; }
.note { width: 100%; margin-top: 0.4rem; padding: 0.45rem 0.6rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.85rem; }
.dir { display: flex; gap: 0.25rem; }
.pill { border: 1px solid #d1d5db; background: #fff; border-radius: 6px; padding: 0.4rem 0.7rem; font-size: 0.82rem; cursor: pointer; }
.pill.active { background: #111827; color: #fff; border-color: #111827; }
.actions { display: flex; align-items: center; gap: 0.8rem; margin-top: 0.5rem; }
.primary { background: #374151; color: #fff; border: none; border-radius: 6px; padding: 0.42rem 0.9rem; font-size: 0.83rem; cursor: pointer; }
.primary:disabled { background: #d1d5db; cursor: not-allowed; }
.err { color: #b91c1c; font-size: 0.8rem; }
.list { list-style: none; margin-top: 0.8rem; display: flex; flex-direction: column; gap: 0.6rem; }
.ref { border: 1px solid #e5e7eb; border-radius: 8px; padding: 0.5rem 0.65rem; }
.ref-head { display: flex; align-items: center; gap: 0.5rem; }
.dirbadge { font-size: 0.7rem; font-weight: 600; border-radius: 4px; padding: 0.1rem 0.35rem; }
.dirbadge.supports { background: #dcfce7; color: #166534; }
.dirbadge.opposes { background: #fee2e2; color: #991b1b; }
.doi-link { font-size: 0.78rem; font-family: ui-monospace, monospace; color: #3b82f6; text-decoration: none; }
.rm { margin-left: auto; background: none; border: none; cursor: pointer; color: #9ca3af; font-size: 1rem; }
.title { font-size: 0.85rem; color: #374151; margin-top: 0.25rem; }
.status { font-size: 0.75rem; margin-top: 0.3rem; }
.status.miss { color: #b45309; font-weight: 600; }
.status.gap { color: #2563eb; }
.status.seen { color: #6b7280; }
.status.unknown { color: #9ca3af; }
.panel-said { margin-top: 0.4rem; background: #f9fafb; border-radius: 6px; padding: 0.45rem 0.55rem; font-size: 0.78rem; color: #374151; }
.labels { list-style: none; margin-top: 0.25rem; color: #6b7280; }
.note-shown { font-size: 0.78rem; color: #6b7280; margin-top: 0.3rem; font-style: italic; }
.miss { margin-top: 0.7rem; font-size: 0.78rem; color: #b45309; }
</style>
