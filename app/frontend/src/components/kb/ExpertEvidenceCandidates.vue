<template>
  <section class="cand-section" aria-labelledby="cand-head">
    <div class="section-header">
      <h2 id="cand-head">Expert evidence candidates
        <span v-if="counts.pending" class="count">({{ counts.pending }} to review)</span>
      </h2>
      <div class="filters" role="group" aria-label="Show">
        <button v-for="s in STATUSES" :key="s" type="button"
                :class="['btn', 'sm', { active: filter === s }]" :aria-pressed="filter === s"
                @click="setFilter(s)">{{ s }} · {{ counts[s] ?? 0 }}</button>
      </div>
    </div>
    <p class="dim small">
      Papers experts named while assessing a stylized fact, by DOI. Each is a
      candidate until a curator accepts or rejects it. Accepting records that
      the paper bears on the fact; it changes no score, and a paper not yet in
      the corpus still has to be added under Ingestion with its PDF.
    </p>

    <div v-if="loading" class="empty-state">Loading…</div>
    <!-- A polite status, not an alert: this list is secondary to the tab,
         and its failure must not read as a failure of the review above. -->
    <div v-else-if="error" class="empty-state err" role="status" data-test="cand-error">
      {{ error }} <button type="button" class="btn xs" @click="load">Retry</button>
    </div>
    <div v-else-if="!items.length" class="empty-state">No {{ filter }} candidates</div>
    <div v-else class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>Fact</th>
            <th>Paper</th>
            <th>Says</th>
            <th>In corpus?</th>
            <th v-if="filter === 'pending'">Review</th>
            <th v-else>Comment</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in items" :key="c.id">
            <td class="fact"><b>#{{ c.sf_number }}</b> <span class="clamp">{{ c.statement }}</span></td>
            <td>
              <a :href="`https://doi.org/${c.doi}`" target="_blank" rel="noopener" class="doi">{{ c.doi }}</a>
              <div v-if="c.resolved_title" class="title">
                {{ c.resolved_title }}<span v-if="c.resolved_year"> ({{ c.resolved_year }})</span>
              </div>
              <div v-if="c.note" class="note">“{{ c.note }}”</div>
            </td>
            <td><span :class="['dir', c.direction]">{{ c.direction }}</span>
              <div class="tier">{{ c.tier || 'unknown' }} tier</div></td>
            <td class="dim">{{ corpusStatus(c.resolution_status) }}</td>
            <td v-if="filter === 'pending'" class="review">
              <label class="sr-only" :for="`cmt-${c.id}`">Comment on {{ c.doi }}</label>
              <input :id="`cmt-${c.id}`" v-model="comments[c.id]" class="comment"
                     placeholder="Comment (optional)" />
              <div class="actions-cell">
                <button type="button" class="btn xs primary" :disabled="busy.has(c.id)"
                        @click="review(c, true)">Accept</button>
                <button type="button" class="btn xs danger" :disabled="busy.has(c.id)"
                        @click="review(c, false)">Reject</button>
              </div>
            </td>
            <td v-else class="dim">{{ c.review_comment || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import api, { apiErrorMessage } from '@/utils/api'
import type {
  CandidateStatus, EvidenceCandidate, EvidenceCandidateList,
} from '@/types/elicitation.generated'

const STATUSES: CandidateStatus[] = ['pending', 'accepted', 'rejected']

const filter = ref<CandidateStatus>('pending')
const items = ref<EvidenceCandidate[]>([])
const counts = ref<Record<string, number>>({})
const comments = reactive<Record<string, string>>({})
const busy = ref<Set<string>>(new Set())
const loading = ref(true)
const error = ref('')

const CORPUS: Record<string, string> = {
  not_in_corpus: 'No — needs ingesting',
  in_corpus_not_retrieved: 'Yes, but retrieval missed it',
  in_corpus_retrieved: 'Yes, and retrieved',
  in_corpus_retrieval_unknown: 'Yes',
  pending: 'Checking',
}
function corpusStatus(s: string | null | undefined) {
  return CORPUS[s || 'pending'] ?? s ?? '—'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get<EvidenceCandidateList>(
      '/elicitation/references/candidates', { params: { status_filter: filter.value } })
    items.value = data?.candidates ?? []
    counts.value = data?.counts ?? {}
  } catch (e) {
    error.value = apiErrorMessage(e)
    items.value = []
  } finally {
    loading.value = false
  }
}

function setFilter(s: CandidateStatus) {
  filter.value = s
  load()
}

async function review(c: EvidenceCandidate, accept: boolean) {
  busy.value = new Set([...busy.value, c.id])
  try {
    await api.post(`/elicitation/references/${c.id}/review`,
      { accept, comment: comments[c.id]?.trim() || null })
    await load()
  } catch (e) {
    error.value = apiErrorMessage(e)
  } finally {
    const next = new Set(busy.value)
    next.delete(c.id)
    busy.value = next
  }
}

onMounted(load)
</script>

<style scoped>
.cand-section { display: flex; flex-direction: column; gap: 0.5rem; }
.section-header { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
.section-header h2 { font-size: 1rem; font-weight: 600; color: #e2e8f0; margin: 0; }
.count { color: #fbbf24; font-weight: 500; font-size: 0.85rem; }
.filters { display: flex; gap: 0.3rem; }
.dim { color: #94a3b8; }
.small { font-size: 0.75rem; line-height: 1.5; max-width: 90ch; }
.btn { padding: 0.35rem 0.75rem; border-radius: 5px; border: 1px solid #334155; background: #1e293b; color: #cbd5e1; font-size: 0.75rem; cursor: pointer; white-space: nowrap; }
.btn:hover { background: #334155; }
.btn.active { border-color: #60a5fa; color: #fff; }
.btn.primary { background: #1d4ed8; border-color: #1d4ed8; color: #fff; }
.btn.danger { border-color: #7f1d1d; color: #fca5a5; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn.sm { padding: 0.25rem 0.55rem; font-size: 0.7rem; text-transform: capitalize; }
.btn.xs { padding: 0.15rem 0.45rem; font-size: 0.7rem; }
.table-scroll { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.75rem; }
.data-table th { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #334155; color: #94a3b8; font-weight: 600; font-size: 0.65rem; text-transform: uppercase; }
.data-table td { padding: 0.45rem 0.6rem; border-bottom: 1px solid #1e293b; color: #cbd5e1; vertical-align: top; }
.fact { max-width: 26rem; }
.clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: #94a3b8; }
.doi { color: #93c5fd; font-family: ui-monospace, monospace; word-break: break-all; }
.title { color: #e2e8f0; margin-top: 0.2rem; }
.note { color: #94a3b8; font-style: italic; margin-top: 0.2rem; }
.dir { font-weight: 600; text-transform: capitalize; }
.dir.supports { color: #86efac; }
.dir.opposes { color: #fca5a5; }
.tier { color: #94a3b8; font-size: 0.68rem; }
.review { min-width: 12rem; }
.comment { width: 100%; margin-bottom: 0.3rem; padding: 0.25rem 0.4rem; border-radius: 4px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; font-size: 0.72rem; }
.actions-cell { display: flex; gap: 0.3rem; }
.empty-state { padding: 1.5rem; text-align: center; color: #94a3b8; font-size: 0.85rem; }
.empty-state.err { color: #fca5a5; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
