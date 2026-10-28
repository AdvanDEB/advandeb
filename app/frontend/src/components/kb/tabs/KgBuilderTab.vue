<template>
  <div class="tab-content kg-tab" role="tabpanel" aria-label="KG Builder">
    <div class="tab-inner">
      <div class="section-header">
        <h2>KG Builder — Document–Taxon Linking</h2>
      </div>
      <div v-if="kgStats" class="kg-stats">
        <div class="stat-card">
          <span class="stat-label">Document–Taxon relations</span>
          <span class="stat-value">{{ formatCount(kgStats.total_relations ?? 0) }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">Suggested</span>
          <span class="stat-value">{{ formatCount(kgStats.suggested_relations ?? 0) }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">Confirmed</span>
          <span class="stat-value">{{ formatCount(kgStats.confirmed_relations ?? 0) }}</span>
        </div>
      </div>
      <div class="kg-actions">
        <button type="button" class="btn primary" @click="runKgLink(false)">Link Documents (keyword)</button>
        <button type="button" class="btn" @click="loadKgStats">Refresh stats</button>
      </div>
      <p class="dim small">
        Keyword linking scans document titles for taxon names and creates suggested document–taxon relations.
        Confirm or reject them in the relation list below, then rebuild the knowledge_graph schema.
      </p>

      <!-- ── Automatic resolution ─────────────────────────────── -->
      <section class="kg-review">
        <div class="section-header">
          <h3>Resolve automatically</h3>
        </div>
        <p class="dim small">
          Most links need no judgement — an exact match of a complete binomial in a domain-relevant
          paper is a string identity. These rules settle those; only what genuinely turns on a
          judgement call is left for review below.
        </p>
        <div class="kg-actions">
          <button type="button" class="btn primary" :disabled="autoBusy" @click="previewAutoResolve">
            {{ autoBusy ? 'Working…' : 'Preview automatic rules' }}
          </button>
        </div>

        <div v-if="autoPreview" class="auto-preview">
          <div class="table-scroll">
            <table class="data-table">
              <thead>
                <tr><th>Rule</th><th>Action</th><th>Links</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in autoPreview.rules" :key="r.rule">
                  <td>
                    <span class="mono">{{ r.rule }}</span>
                    <div class="dim small">{{ r.description }}</div>
                  </td>
                  <td :class="r.action === 'confirmed' ? 'tally-ok' : 'tally-no'">{{ r.action }}</td>
                  <td>{{ formatCount(r.matched) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="bulk-confirm">
            Applies to <strong>{{ formatCount(autoPreview.total) }}</strong> links, leaving
            <strong>{{ formatCount(autoPreview.remaining_suggested - autoPreview.total) }}</strong> for review.
            Auto-decisions are stamped <span class="mono">auto:&lt;rule&gt;</span> so they stay
            distinguishable from human review.
            <button type="button" class="btn xs danger" :disabled="autoBusy" @click="applyAutoResolve">Apply rules</button>
            <button type="button" class="btn xs" :disabled="autoBusy" @click="autoPreview = null">Cancel</button>
          </div>
        </div>
      </section>

      <!-- ── Relation review ──────────────────────────────────── -->
      <section class="kg-review">
        <div class="section-header">
          <h3>Review what's left</h3>
          <span class="dim small" v-if="relTotal !== null">{{ formatCount(relTotal) }} match the filter</span>
        </div>

        <div class="kg-filters">
          <label>Status
            <select v-model="relFilter.status">
              <option value="suggested">suggested</option>
              <option value="confirmed">confirmed</option>
              <option value="rejected">rejected</option>
              <option value="">any</option>
            </select>
          </label>
          <label>Min confidence
            <input type="number" min="0" max="1" step="0.05" v-model.number="relFilter.min_confidence" />
          </label>
          <label>Max confidence
            <input type="number" min="0" max="1" step="0.05" v-model.number="relFilter.max_confidence" />
          </label>
          <button type="button" class="btn sm primary" :disabled="relLoading" @click="loadRelations(true)">
            {{ relLoading ? 'Loading…' : 'Load random sample (50)' }}
          </button>
          <button type="button" class="btn sm" :disabled="relLoading" @click="loadRelations(false)">Load top by confidence</button>
        </div>

        <!-- Running tally: what the sample says about the whole set -->
        <div v-if="relReviewed > 0" class="kg-tally">
          <span>Reviewed <strong>{{ relReviewed }}</strong> of {{ relations.length }} shown</span>
          <span class="tally-ok">✓ {{ relConfirmed }}</span>
          <span class="tally-no">✕ {{ relRejected }}</span>
          <span v-if="relSampled" class="tally-est">
            — reject rate <strong>{{ (100 * relRejected / relReviewed).toFixed(0) }}%</strong>;
            on {{ formatCount(relTotal ?? 0) }} matching that projects to
            <strong>~{{ formatCount(Math.round((relTotal ?? 0) * relRejected / relReviewed)) }}</strong> bad links
          </span>
          <span v-else class="dim small">— not a random sample, so no rate estimate</span>
        </div>

        <div v-if="relLoading" class="empty-state">Loading…</div>
        <div v-else-if="!relations.length" class="empty-state">No relations match — load a sample to begin</div>
        <p v-if="relations.length && !relLoading" class="dim small kbd-hint">
          Keyboard: <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>y</kbd> confirm · <kbd>n</kbd> reject — decisions auto-advance
        </p>
        <div v-if="relations.length && !relLoading" class="table-scroll">
          <table class="data-table sugg-table rel-table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Taxon</th>
                <th>Conf.</th>
                <th>Evidence</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <!-- Clicking a row puts the review cursor on it. From the keyboard
                   the cursor follows j/k (above) and focus: tabbing into a row's
                   buttons moves the cursor there too. -->
              <tr
                v-for="(rel, i) in relations"
                :key="rel._key"
                :class="{ decided: relDecisions[rel._key], cursor: i === relCursor }"
                :aria-current="i === relCursor ? 'true' : undefined"
                :ref="el => setRelRowRef(el, i)"
                @click="relCursor = i"
                @focusin="relCursor = i"
              >
                <td class="sugg-title">
                  {{ rel.document_title || rel.document_id }}
                  <span v-if="rel.document_domain_relevant === false" class="off-domain" title="Domain gate marked this document off-domain">off-domain</span>
                </td>
                <td>
                  <span class="taxon-name">{{ rel.taxon_name || rel.tax_id }}</span>
                  <span class="dim small"> {{ rel.taxon_rank }}</span>
                </td>
                <td :class="{ 'low-conf': rel.confidence < 0.8 }">{{ rel.confidence?.toFixed(2) }}</td>
                <td class="dim small evidence-cell">{{ rel.evidence }}</td>
                <td class="actions-cell">
                  <template v-if="relDecisions[rel._key]">
                    <span :class="relDecisions[rel._key] === 'confirmed' ? 'tally-ok' : 'tally-no'">
                      {{ relDecisions[rel._key] }}
                    </span>
                  </template>
                  <template v-else>
                    <button type="button" class="btn xs primary" @click="decideRelation(rel, 'confirmed')">Confirm</button>
                    <button type="button" class="btn xs danger" @click="decideRelation(rel, 'rejected')">Reject</button>
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Bulk action, gated behind a dry-run count -->
        <div class="kg-bulk">
          <span class="dim small">Bulk apply to <strong>all {{ formatCount(relTotal ?? 0) }}</strong> matching the filter above:</span>
          <button type="button" class="btn sm" :disabled="relBulkBusy" @click="previewBulk('rejected')">Preview reject all</button>
          <button type="button" class="btn sm" :disabled="relBulkBusy" @click="previewBulk('confirmed')">Preview confirm all</button>
          <div v-if="relBulkPreview" class="bulk-confirm">
            This will set <strong>{{ formatCount(relBulkPreview.matched) }}</strong> relations to
            <strong>{{ relBulkPreview.status }}</strong>. This cannot be undone from the UI.
            <button type="button" class="btn xs danger" :disabled="relBulkBusy" @click="applyBulk">Apply</button>
            <button type="button" class="btn xs" :disabled="relBulkBusy" @click="relBulkPreview = null">Cancel</button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import {
  fetchKgRelations,
  updateKgRelation,
  bulkUpdateKgRelations,
  autoResolveKgRelations,
  fetchKgStats,
  linkDocuments,
} from '@/utils/kbApi'
import type { AutoResolveResult, KgRelation, KgRelationFilter, KgStats } from '@/utils/kbApi'
import { useKnowledgeBuilderStore } from '@/stores/knowledgeBuilder'
import { useDialogStore } from '@/stores/dialog'
import { formatCount } from '@/utils/format'

const kb = useKnowledgeBuilderStore()
const { activeTab } = storeToRefs(kb)
const { setError } = kb
const dialog = useDialogStore()

// ---- Stats and keyword linking ----------------------------------------------

const kgStats = ref<KgStats | null>(null)

async function loadKgStats() {
  try { kgStats.value = await fetchKgStats() } catch (e) { setError(e) }
}

async function runKgLink(overwrite: boolean) {
  try { await linkDocuments(1000, overwrite); await loadKgStats() } catch (e) { setError(e) }
}

// ---- Automatic resolution ---------------------------------------------------

const autoPreview = ref<AutoResolveResult | null>(null)
const autoBusy    = ref(false)

async function previewAutoResolve() {
  autoBusy.value = true
  try { autoPreview.value = await autoResolveKgRelations(true) }
  catch (e) { setError(e) }
  finally { autoBusy.value = false }
}

async function applyAutoResolve() {
  autoBusy.value = true
  try {
    const res = await autoResolveKgRelations(false)
    autoPreview.value = null
    await dialog.alert({
      title: `Applied ${formatCount(res.total)} automatic decisions`,
      message:
        res.rules.map(r => `${r.rule}: ${formatCount(r.applied)} ${r.action}`).join('\n') +
        `\n\n${formatCount(res.remaining_suggested)} left to review.`,
    })
    await Promise.all([loadKgStats(), loadRelations(relSampled.value)])
  } catch (e) { setError(e) }
  finally { autoBusy.value = false }
}

// ---- Relation review --------------------------------------------------------
//
// Sample-then-bulk: 6,003 suggested relations is far too many to click through,
// but reviewing a *random* sample gives a measured reject rate that can be
// projected onto the whole filtered set — so a bulk decision is made against a
// number rather than a hunch. Reviewing the first page instead would only tell
// you about the highest-confidence rows, which is the opposite of informative.

const relations     = ref<KgRelation[]>([])
const relTotal      = ref<number | null>(null)
const relLoading    = ref(false)
const relSampled    = ref(false)
const relDecisions  = ref<Record<string, 'confirmed' | 'rejected'>>({})
const relBulkBusy   = ref(false)
const relBulkPreview = ref<{ matched: number; status: 'confirmed' | 'rejected' } | null>(null)

const relFilter = ref<KgRelationFilter>({ status: 'suggested' })

const relReviewed  = computed(() => Object.keys(relDecisions.value).length)
const relConfirmed = computed(() => Object.values(relDecisions.value).filter(v => v === 'confirmed').length)
const relRejected  = computed(() => Object.values(relDecisions.value).filter(v => v === 'rejected').length)

function activeRelFilter(): KgRelationFilter {
  // Strip empty values so the backend doesn't filter on undefined.
  const f = relFilter.value
  const out: KgRelationFilter = {}
  if (f.status) out.status = f.status
  if (typeof f.min_confidence === 'number' && !Number.isNaN(f.min_confidence)) out.min_confidence = f.min_confidence
  if (typeof f.max_confidence === 'number' && !Number.isNaN(f.max_confidence)) out.max_confidence = f.max_confidence
  if (f.created_by) out.created_by = f.created_by
  return out
}

async function loadRelations(sample: boolean) {
  relLoading.value = true
  relBulkPreview.value = null
  try {
    const res = await fetchKgRelations(activeRelFilter(), { sample, limit: 50 })
    relations.value = res.relations
    relTotal.value = res.total
    relSampled.value = sample
    relDecisions.value = {}
    relCursor.value = 0
    relRowEls.length = 0
  } catch (e) {
    setError(e)
  } finally {
    relLoading.value = false
  }
}

// Cursor + keyboard review. Clicking two small buttons per row, 50 rows at a
// time, is the difference between a queue that gets worked and one that does
// not — so j/k to move and y/n to decide, with auto-advance to the next
// undecided row.
const relCursor = ref(0)
const relRowEls: (Element | null)[] = []

function setRelRowRef(el: unknown, i: number) {
  relRowEls[i] = (el as Element) ?? null
}

function moveRelCursor(delta: number) {
  if (!relations.value.length) return
  const next = Math.min(relations.value.length - 1, Math.max(0, relCursor.value + delta))
  relCursor.value = next
  relRowEls[next]?.scrollIntoView({ block: 'nearest' })
}

/** Advance to the next row that has not been decided yet, else just step on. */
function advancePastDecided() {
  const list = relations.value
  for (let i = relCursor.value + 1; i < list.length; i++) {
    if (!relDecisions.value[list[i]._key]) {
      relCursor.value = i
      relRowEls[i]?.scrollIntoView({ block: 'nearest' })
      return
    }
  }
  moveRelCursor(1)
}

function onReviewKey(ev: KeyboardEvent) {
  if (activeTab.value !== 'kg' || !relations.value.length) return
  // Never hijack typing in the filter inputs.
  const tag = (ev.target as HTMLElement | null)?.tagName
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return

  const key = ev.key.toLowerCase()
  if (key === 'j' || ev.key === 'ArrowDown') { ev.preventDefault(); moveRelCursor(1) }
  else if (key === 'k' || ev.key === 'ArrowUp') { ev.preventDefault(); moveRelCursor(-1) }
  else if (key === 'y') { ev.preventDefault(); decideCurrent('confirmed') }
  else if (key === 'n') { ev.preventDefault(); decideCurrent('rejected') }
}

function decideCurrent(status: 'confirmed' | 'rejected') {
  const rel = relations.value[relCursor.value]
  if (rel && !relDecisions.value[rel._key]) decideRelation(rel, status)
  else advancePastDecided()
}

async function decideRelation(rel: KgRelation, status: 'confirmed' | 'rejected') {
  try {
    await updateKgRelation(rel._key, status)
    relDecisions.value = { ...relDecisions.value, [rel._key]: status }
    advancePastDecided()
    loadKgStats()
  } catch (e) {
    setError(e)
  }
}

async function previewBulk(status: 'confirmed' | 'rejected') {
  relBulkBusy.value = true
  try {
    const res = await bulkUpdateKgRelations(status, activeRelFilter(), true)
    relBulkPreview.value = { matched: res.matched, status }
  } catch (e) {
    setError(e)
  } finally {
    relBulkBusy.value = false
  }
}

async function applyBulk() {
  const preview = relBulkPreview.value
  if (!preview) return
  relBulkBusy.value = true
  try {
    await bulkUpdateKgRelations(preview.status, activeRelFilter(), false)
    relBulkPreview.value = null
    await Promise.all([loadKgStats(), loadRelations(relSampled.value)])
  } catch (e) {
    setError(e)
  } finally {
    relBulkBusy.value = false
  }
}

// ---- Lifecycle ----------------------------------------------------------------

// Stats load the first time the tab is shown.
watch(activeTab, (tab) => {
  if (tab === 'kg' && !kgStats.value) loadKgStats()
}, { immediate: true })

onMounted(() => window.addEventListener('keydown', onReviewKey))
onUnmounted(() => window.removeEventListener('keydown', onReviewKey))
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

/* ---- Stats ------------------------------------------------------------------ */
.kg-stats {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}
.stat-card {
  flex: 1;
  min-width: 120px;
  padding: 1rem;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.stat-label { font-size: 0.7rem; color: #64748b; }
.stat-value { font-size: 1.4rem; font-weight: 700; color: #e2e8f0; }

.kg-actions { display: flex; gap: 0.75rem; flex-wrap: wrap; }

/* ── Relation review ─────────────────────────────────────────────────────── */
.kg-review { margin-top: 1.5rem; }

/* The document title is what a reviewer judges on, so it must not be clipped to
   320px like the compact suggestion tables. */
.rel-table .sugg-title {
  max-width: none;
  white-space: normal;
  line-height: 1.35;
}
.rel-table td { vertical-align: top; }
.rel-table tr.cursor td {
  background: rgba(96, 165, 250, 0.12);
  box-shadow: inset 3px 0 0 #60a5fa;
}
.auto-preview { margin-top: 0.6rem; }
.auto-preview .mono { color: #cbd5e1; }
.kbd-hint { margin: 0 0 0.5rem; }
.kbd-hint kbd {
  padding: 0.05rem 0.28rem;
  border: 1px solid #475569;
  border-bottom-width: 2px;
  border-radius: 3px;
  font-size: 0.68rem;
  color: #cbd5e1;
  background: #1e293b;
}
.kg-filters {
  display: flex;
  align-items: flex-end;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
}
.kg-filters label {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.7rem;
  color: #64748b;
}
.kg-filters select, .kg-filters input { padding: 0.25rem 0.4rem; font-size: 0.78rem; width: 8rem; }

.kg-tally {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  padding: 0.5rem 0.7rem;
  margin-bottom: 0.6rem;
  border-radius: 5px;
  background: rgba(100, 130, 220, 0.08);
  border: 1px solid rgba(100, 130, 220, 0.2);
  font-size: 0.78rem;
}
.tally-ok  { color: var(--app-success); font-weight: 600; }
.tally-no  { color: var(--app-danger); font-weight: 600; }
.tally-est { color: #475569; }

.evidence-cell { max-width: 22rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.taxon-name { font-style: italic; }
.low-conf { color: #b45309; font-weight: 600; }
tr.decided { opacity: 0.55; }
.off-domain {
  margin-left: 0.4rem;
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
  font-size: 0.62rem;
  background: rgba(180, 83, 9, 0.15);
  color: #b45309;
}

.kg-bulk {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  margin-top: 0.9rem;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}
.bulk-confirm {
  flex-basis: 100%;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: 0.5rem;
  padding: 0.55rem 0.7rem;
  border-radius: 5px;
  background: rgba(220, 38, 38, 0.08);
  border: 1px solid rgba(220, 38, 38, 0.25);
  font-size: 0.78rem;
  color: #7f1d1d;
}

/* ---- Shared with the suggestion tables -------------------------------------- */
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

/* ---- Utilities ------------------------------------------------------------- */
.mono { font-family: monospace; }
.small { font-size: 0.7rem !important; }
.dim { color: #475569; }

/* ---- Narrow screens ---------------------------------------------------------- */
@media (max-width: 768px) {
  .tab-inner { padding: 1rem; }
  .section-header { flex-wrap: wrap; gap: 0.5rem 1rem; }
  /* The title column is unclipped, so give the table room and scroll it. */
  .rel-table { min-width: 640px; }
  .evidence-cell { max-width: 14rem; }
}

@media (pointer: coarse) {
  .btn { min-height: var(--app-touch); }
}
</style>
