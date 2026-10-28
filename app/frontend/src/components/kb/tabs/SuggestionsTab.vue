<template>
  <div class="tab-content suggestions-tab" role="tabpanel" aria-label="Suggestions">
    <div class="tab-inner suggestions-inner">

      <!-- ── Pipeline review queues ───────────────────────────── -->
      <section class="sugg-section">
        <div class="section-header">
          <h2>Pipeline review queues</h2>
          <button type="button" class="btn sm" @click="loadSuggestions">Refresh</button>
        </div>
        <p class="dim small">
          Machine-generated output awaiting review. The sections below cover <em>user submissions</em> only,
          which is why they are usually empty — this is where the pipeline's own backlog lives.
        </p>

        <div v-if="!reviewQueues" class="empty-state">Loading queues…</div>
        <div v-else class="queue-grid">
          <button type="button" class="queue-card" @click="activeTab = 'kg'">
            <span class="queue-n">{{ formatCount(reviewQueues.studies_suggested) }}</span>
            <span class="queue-label">document → organism links</span>
            <span class="queue-sub">
              {{ formatCount(reviewQueues.studies_confirmed) }} confirmed · review in KG Builder →
            </span>
          </button>
          <div class="queue-card static">
            <span class="queue-n">{{ formatCount(reviewQueues.sf_support_suggested) }}</span>
            <span class="queue-label">fact → stylized-fact links</span>
            <span class="queue-sub">of {{ formatCount(reviewQueues.sf_support_total) }} total · no review UI yet</span>
          </div>
          <div class="queue-card static">
            <span class="queue-n">{{ formatCount(reviewQueues.facts_pending) }}</span>
            <span class="queue-label">extracted facts pending</span>
            <span class="queue-sub">of {{ formatCount(reviewQueues.facts_total) }} total · no review UI yet</span>
          </div>
          <div class="queue-card static">
            <span class="queue-n">{{ formatCount(reviewQueues.documents_off_domain) }}</span>
            <span class="queue-label">documents judged off-domain</span>
            <span class="queue-sub">
              of {{ formatCount(reviewQueues.documents_gated) }} gated · no review UI yet
            </span>
          </div>
        </div>
      </section>

      <!-- ── Document suggestions ─────────────────────────────── -->
      <section class="sugg-section">
        <div class="section-header">
          <h2>Document Suggestions
            <span class="sugg-count" v-if="docSuggestions.length">({{ docSuggestions.length }})</span>
          </h2>
        </div>
        <p class="dim small">Documents uploaded by users pending KB ingestion. Approve to queue for the ingestion pipeline; reject to discard.</p>

        <div v-if="suggLoading" class="empty-state">Loading…</div>
        <div v-else-if="!docSuggestions.length" class="empty-state">No document suggestions</div>
        <div v-else class="table-scroll">
          <table class="data-table sugg-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Type</th>
                <th>Uploaded</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="doc in docSuggestions" :key="doc._id">
                <td class="sugg-title">{{ doc.title || '(untitled)' }}</td>
                <td class="dim">{{ doc.source_type }}</td>
                <td class="dim">{{ formatDate(doc.created_at, '—') }}</td>
                <td class="actions-cell">
                  <button
                    type="button"
                    class="btn xs primary"
                    :disabled="pendingDocIds.has(doc._id)"
                    @click="handleDocAction(doc._id, 'approve')"
                  >{{ pendingDocIds.has(doc._id) ? '…' : 'Approve' }}</button>
                  <button
                    type="button"
                    class="btn xs danger"
                    :disabled="pendingDocIds.has(doc._id)"
                    @click="handleDocAction(doc._id, 'reject')"
                  >{{ pendingDocIds.has(doc._id) ? '…' : 'Reject' }}</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ── Fact suggestions ──────────────────────────────────── -->
      <section class="sugg-section">
        <div class="section-header">
          <h2>Fact Suggestions
            <span class="sugg-count" v-if="factSuggestions.length">({{ factSuggestions.length }})</span>
          </h2>
        </div>
        <p class="dim small">Facts submitted by users. Publish to make them visible in the KB; reject to discard.</p>

        <div v-if="suggLoading" class="empty-state">Loading…</div>
        <div v-else-if="!factSuggestions.length" class="empty-state">No fact suggestions</div>
        <div v-else class="table-scroll">
          <table class="data-table sugg-table">
            <thead>
              <tr>
                <th>Statement</th>
                <th>Tags</th>
                <th>Confidence</th>
                <th>Submitted</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="fact in factSuggestions" :key="fact._id">
                <td class="sugg-statement">{{ fact.statement }}</td>
                <td>
                  <span v-for="tag in (fact.tags ?? [])" :key="tag" class="tag-chip">{{ tag }}</span>
                </td>
                <td class="dim">{{ fact.confidence != null ? Math.round((fact.confidence as number) * 100) + '%' : '—' }}</td>
                <td class="dim">{{ formatDate(fact.created_at, '—') }}</td>
                <td class="actions-cell">
                  <button
                    type="button"
                    class="btn xs primary"
                    :disabled="pendingFactIds.has(fact._id)"
                    @click="handleFactAction(fact._id, 'published')"
                  >{{ pendingFactIds.has(fact._id) ? '…' : 'Publish' }}</button>
                  <button
                    type="button"
                    class="btn xs danger"
                    :disabled="pendingFactIds.has(fact._id)"
                    @click="handleFactAction(fact._id, 'rejected')"
                  >{{ pendingFactIds.has(fact._id) ? '…' : 'Reject' }}</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ── Stylized fact suggestions ─────────────────────────── -->
      <section class="sugg-section">
        <div class="section-header">
          <h2>Stylized Fact Suggestions
            <span class="sugg-count" v-if="sfSuggestions.length">({{ sfSuggestions.length }})</span>
          </h2>
        </div>
        <p class="dim small">Stylized facts submitted by users. Publish to make them citable; reject to discard.</p>

        <div v-if="suggLoading" class="empty-state">Loading…</div>
        <div v-else-if="!sfSuggestions.length" class="empty-state">No stylized fact suggestions</div>
        <div v-else class="table-scroll">
          <table class="data-table sugg-table">
            <thead>
              <tr>
                <th>Summary</th>
                <th>Tags</th>
                <th>Submitted</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="sf in sfSuggestions" :key="sf._id">
                <td class="sugg-statement">{{ sf.summary }}</td>
                <td>
                  <span v-for="tag in (sf.tags ?? [])" :key="tag" class="tag-chip">{{ tag }}</span>
                </td>
                <td class="dim">{{ formatDate(sf.created_at, '—') }}</td>
                <td class="actions-cell">
                  <button
                    type="button"
                    class="btn xs primary"
                    :disabled="pendingSfIds.has(sf._id)"
                    @click="handleSfAction(sf._id, 'published')"
                  >{{ pendingSfIds.has(sf._id) ? '…' : 'Publish' }}</button>
                  <button
                    type="button"
                    class="btn xs danger"
                    :disabled="pendingSfIds.has(sf._id)"
                    @click="handleSfAction(sf._id, 'rejected')"
                  >{{ pendingSfIds.has(sf._id) ? '…' : 'Reject' }}</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import {
  fetchReviewQueues,
  fetchDocumentSuggestions, approveDocument,
  fetchFactSuggestions, reviewFact,
  fetchStylizedFactSuggestions, reviewStylizedFact,
} from '@/utils/kbApi'
import type { DocumentSuggestion, FactSuggestion, ReviewQueues, StylizedFactSuggestion } from '@/utils/kbApi'
import { useKnowledgeBuilderStore } from '@/stores/knowledgeBuilder'
import { formatCount, formatDate } from '@/utils/format'

const kb = useKnowledgeBuilderStore()
const { activeTab } = storeToRefs(kb)
const { setError } = kb

const docSuggestions  = ref<DocumentSuggestion[]>([])
const factSuggestions = ref<FactSuggestion[]>([])
const sfSuggestions   = ref<StylizedFactSuggestion[]>([])
const suggLoading     = ref(false)
const pendingDocIds   = ref<Set<string>>(new Set())
const pendingFactIds  = ref<Set<string>>(new Set())
const pendingSfIds    = ref<Set<string>>(new Set())

const reviewQueues = ref<ReviewQueues | null>(null)

async function loadSuggestions() {
  suggLoading.value = true
  try {
    // Queue counts are fetched alongside the submission lists, and separately
    // guarded: the submission collections are empty in every deployment so far,
    // and their emptiness must not hide the pipeline backlog.
    const [docs, facts, sfs, queues] = await Promise.all([
      fetchDocumentSuggestions('suggestion'),
      fetchFactSuggestions('suggestion'),
      fetchStylizedFactSuggestions('suggestion'),
      fetchReviewQueues().catch((e) => { setError(e); return null }),
    ])
    docSuggestions.value  = Array.isArray(docs) ? docs : []
    factSuggestions.value = Array.isArray(facts) ? facts : []
    sfSuggestions.value   = Array.isArray(sfs) ? sfs : []
    reviewQueues.value    = queues
  } catch (e) { setError(e) }
  finally { suggLoading.value = false }
}

async function handleDocAction(docId: string, action: 'approve' | 'reject') {
  pendingDocIds.value = new Set([...pendingDocIds.value, docId])
  try {
    await approveDocument(docId, action)
    docSuggestions.value = docSuggestions.value.filter(d => d._id !== docId)
  } catch (e) { setError(e) }
  finally {
    const next = new Set(pendingDocIds.value)
    next.delete(docId)
    pendingDocIds.value = next
  }
}

async function handleFactAction(factId: string, status: 'published' | 'rejected') {
  pendingFactIds.value = new Set([...pendingFactIds.value, factId])
  try {
    await reviewFact(factId, status)
    factSuggestions.value = factSuggestions.value.filter(f => f._id !== factId)
  } catch (e) { setError(e) }
  finally {
    const next = new Set(pendingFactIds.value)
    next.delete(factId)
    pendingFactIds.value = next
  }
}

async function handleSfAction(sfId: string, status: 'published' | 'rejected') {
  pendingSfIds.value = new Set([...pendingSfIds.value, sfId])
  try {
    await reviewStylizedFact(sfId, status)
    sfSuggestions.value = sfSuggestions.value.filter(s => s._id !== sfId)
  } catch (e) { setError(e) }
  finally {
    const next = new Set(pendingSfIds.value)
    next.delete(sfId)
    pendingSfIds.value = next
  }
}

// Suggestions reload each time the tab is shown.
watch(activeTab, (tab) => {
  if (tab === 'suggestions') loadSuggestions()
}, { immediate: true })
</script>

<style scoped>
.tab-content { flex: 1; min-height: 0; overflow: hidden; }

.tab-inner {
  padding: 1.5rem;
  /* Was max-width:1200px with no auto margin, so every non-graph tab hugged the
     left edge and left a dead column on the right — while table cells truncated. */
  max-width: 1600px;
  margin-inline: auto;
  width: 100%;
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.section-header h2 { font-size: 1rem; font-weight: 600; color: #e2e8f0; margin: 0; }

/* ---- Buttons ---------------------------------------------------------------- */
.btn {
  padding: 0.35rem 0.75rem;
  border-radius: 5px;
  border: 1px solid #334155;
  background: #1e293b;
  color: #cbd5e1;
  font-size: 0.75rem;
  cursor: pointer;
  white-space: nowrap;
}
.btn:hover { background: #334155; }
.btn.primary { background: #1d4ed8; border-color: var(--app-primary); color: white; }
.btn.primary:hover { background: var(--app-primary-strong); }
.btn.danger { border-color: #7f1d1d; color: #fca5a5; }
.btn.danger:hover { background: #7f1d1d; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn.sm { padding: 0.25rem 0.55rem; font-size: 0.7rem; }
.btn.xs { padding: 0.15rem 0.4rem; font-size: 0.65rem; }

/* ---- Tables ----------------------------------------------------------------- */
.table-scroll { overflow-x: auto; }

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}
.data-table th {
  text-align: left;
  padding: 0.4rem 0.6rem;
  border-bottom: 1px solid #334155;
  color: #64748b;
  font-weight: 600;
  font-size: 0.65rem;
  text-transform: uppercase;
}
.data-table td {
  padding: 0.4rem 0.6rem;
  border-bottom: 1px solid #1e293b;
  color: #cbd5e1;
}
.data-table tr:hover td { background: #1e293b; }

.actions-cell { display: flex; gap: 0.3rem; align-items: center; }

.empty-state { padding: 2rem; text-align: center; color: #475569; font-size: 0.85rem; }

/* ---- Review queues ---------------------------------------------------------- */
.queue-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 0.6rem;
  margin-bottom: 0.5rem;
}
.queue-card {
  font: inherit;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.7rem 0.8rem;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 6px;
  cursor: pointer;
}
.queue-card.static { cursor: default; }
.queue-card:not(.static):hover { border-color: var(--app-primary); }
.queue-card:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }
.queue-n { font-size: 1.25rem; font-weight: 600; color: #e2e8f0; }
.queue-label { font-size: 0.75rem; color: #cbd5e1; }
.queue-sub { font-size: 0.68rem; color: #64748b; }

/* ---- Suggestions ------------------------------------------------------------ */
.suggestions-tab { overflow-y: auto; }

.suggestions-inner {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.sugg-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.sugg-count {
  font-size: 0.75rem;
  font-weight: 400;
  color: #64748b;
  margin-left: 0.4rem;
}

.sugg-table { table-layout: auto; }
.sugg-table th:last-child { width: 130px; }

.sugg-title {
  font-size: 0.8rem;
  color: #e2e8f0;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sugg-statement {
  font-size: 0.78rem;
  color: #cbd5e1;
  max-width: 400px;
  white-space: normal;
  line-height: 1.4;
}

.tag-chip {
  display: inline-block;
  background: #1e3a5f;
  color: #93c5fd;
  font-size: 0.6rem;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  margin-right: 2px;
  white-space: nowrap;
}

/* ---- Utilities ------------------------------------------------------------- */
.small { font-size: 0.7rem !important; }
.dim { color: #475569; }

/* ---- Narrow screens ---------------------------------------------------------- */
@media (max-width: 768px) {
  .tab-inner { padding: 1rem; }
  .section-header { flex-wrap: wrap; gap: 0.5rem 1rem; }
  .sugg-title { max-width: 200px; }
  .sugg-statement { min-width: 220px; }
}

@media (pointer: coarse) {
  .btn { min-height: var(--app-touch); }
}
</style>
