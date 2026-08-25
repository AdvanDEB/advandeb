<template>
  <div class="document-library">
    <!-- Filters bar -->
    <div class="filters-bar">
      <div class="search-wrap">
        <svg class="search-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input
          v-model="searchQuery"
          placeholder="Search title, DOI, journal…"
          class="search-input"
          @input="debouncedFetch"
        />
      </div>

      <select v-model="statusFilter" class="filter-select" @change="resetAndFetch">
        <option value="">All statuses</option>
        <option value="pending">Pending</option>
        <option value="processing">Processing</option>
        <option value="completed">Indexed</option>
        <option value="failed">Failed</option>
      </select>

      <select v-model="typeFilter" class="filter-select" @change="resetAndFetch">
        <option value="">All pipeline types</option>
        <option value="pdf_local">PDF (local)</option>
        <option value="pdf_upload">PDF (upload)</option>
        <option value="text">Text</option>
        <option value="manual">Manual</option>
        <option value="web">Web abstract</option>
      </select>

      <select v-model="flagFilter" class="filter-select" @change="resetAndFetch">
        <option value="">All documents</option>
        <option value="true">Flagged only</option>
        <option value="false">Unflagged only</option>
      </select>

      <label class="web-toggle">
        <input type="checkbox" v-model="includeWeb" @change="resetAndFetch" />
        Include web abstracts
      </label>

      <span class="count-badge">{{ totalCount.toLocaleString() }} document{{ totalCount !== 1 ? 's' : '' }}</span>
    </div>

    <!-- State messages -->
    <div v-if="loading" class="state-msg">Loading corpus…</div>
    <div v-else-if="documents.length === 0" class="state-msg empty">
      No documents found.
      <span v-if="!isCurator"> Contact a curator to add documents to the corpus.</span>
    </div>

    <!-- Table -->
    <div v-else class="table-wrap">
      <table class="doc-table">
        <thead>
          <tr>
            <th class="col-type"></th>
            <th class="col-title">Title / Authors</th>
            <th class="col-year">Year</th>
            <th class="col-journal">Journal</th>
            <th class="col-status">Status</th>
            <th class="col-actions"></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="doc in documents" :key="doc.id">
            <tr
              :class="['doc-row', { expanded: expandedId === doc.id, flagged: doc.potentially_irrelevant }]"
              @click="toggleExpand(doc.id)"
            >
              <td class="col-type">
                <span :class="['type-pill', typeClass(doc.source_type)]" :title="typeLabel(doc.source_type)">
                  {{ typeShort(doc.source_type) }}
                </span>
              </td>

              <td class="col-title">
                <div class="title-text">
                  {{ doc.title || '(untitled)' }}
                  <span v-if="doc.potentially_irrelevant" class="flag-pill" :title="doc.flag_reason || 'Flagged as potentially irrelevant'">
                    ⚑ irrelevant
                  </span>
                </div>
                <div v-if="formattedAuthors(doc)" class="authors-text">
                  {{ formattedAuthors(doc) }}
                </div>
              </td>

              <td class="col-year">{{ doc.year || '—' }}</td>

              <td class="col-journal">
                <span class="journal-text" :title="doc.journal || ''">{{ doc.journal || '—' }}</span>
                <a
                  v-if="doc.doi"
                  :href="`https://doi.org/${doc.doi}`"
                  class="doi-link"
                  target="_blank"
                  rel="noopener"
                  @click.stop
                >
                  DOI ↗
                </a>
              </td>

              <td class="col-status">
                <span :class="['status-badge', doc.processing_status]">
                  {{ STATUS_LABELS[doc.processing_status] || doc.processing_status }}
                </span>
                <div v-if="doc.num_chunks" class="chunk-count">{{ doc.num_chunks }}c{{ doc.num_facts ? ` · ${doc.num_facts}f` : '' }}</div>
              </td>

              <td class="col-actions" @click.stop>
                <button
                  v-if="!doc.potentially_irrelevant"
                  class="act-btn flag"
                  title="Flag as potentially irrelevant"
                  @click="openFlagModal(doc)"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>
                </button>
                <button
                  v-else-if="isCurator"
                  class="act-btn unflag"
                  title="Remove flag"
                  @click="unflag(doc)"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>
                </button>

                <button
                  v-if="isCurator"
                  class="act-btn delete"
                  :class="{ disabled: doc.processing_status === 'completed' }"
                  :title="doc.processing_status === 'completed'
                    ? 'Incorporated into KB — flag as irrelevant instead'
                    : 'Delete document'"
                  :disabled="doc.processing_status === 'completed'"
                  @click="confirmDelete(doc)"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
                </button>
              </td>
            </tr>

            <!-- Expanded abstract row -->
            <tr v-if="expandedId === doc.id" class="abstract-row">
              <td colspan="6">
                <div class="abstract-content">
                  <div v-if="doc.abstract" class="abstract-text">
                    <strong>Abstract</strong>
                    <p>{{ doc.abstract }}</p>
                  </div>
                  <div v-else class="abstract-text muted">No abstract available.</div>
                  <div v-if="doc.general_domain" class="meta-chips">
                    <span class="chip">{{ doc.general_domain }}</span>
                  </div>
                  <div v-if="doc.flag_reason && doc.potentially_irrelevant" class="flag-note">
                    <strong>Flag reason:</strong> {{ doc.flag_reason }}
                    <span v-if="doc.flagged_at"> · {{ formatDate(doc.flagged_at) }}</span>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- Pagination bar -->
    <div v-if="totalPages > 1 || documents.length > 0" class="pagination-bar">
      <div class="pagination-left">
        <select v-model="pageSize" class="page-size-select" @change="resetAndFetch">
          <option :value="25">25 / page</option>
          <option :value="50">50 / page</option>
          <option :value="100">100 / page</option>
          <option :value="200">200 / page</option>
        </select>
      </div>

      <div class="pagination-center">
        <button class="page-btn" :disabled="currentPage <= 1" @click="goToPage(1)">«</button>
        <button class="page-btn" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">‹</button>

        <span class="page-info">
          Page
          <input
            class="page-input"
            type="number"
            :min="1"
            :max="totalPages"
            :value="currentPage"
            @change="goToPage(Number(($event.target as HTMLInputElement).value))"
          />
          of {{ totalPages.toLocaleString() }}
        </span>

        <button class="page-btn" :disabled="currentPage >= totalPages" @click="goToPage(currentPage + 1)">›</button>
        <button class="page-btn" :disabled="currentPage >= totalPages" @click="goToPage(totalPages)">»</button>
      </div>

      <div class="pagination-right">
        <span class="page-range">
          {{ rangeStart }}–{{ rangeEnd }} of {{ totalCount.toLocaleString() }}
        </span>
      </div>
    </div>

    <!-- Flag modal -->
    <div v-if="flagModal" class="modal-overlay" @click.self="flagModal = null">
      <div class="modal">
        <h3>Flag as potentially irrelevant</h3>
        <p class="modal-doc-title">{{ flagModal.title }}</p>
        <label class="modal-label">Reason (optional)</label>
        <textarea
          v-model="flagReason"
          class="modal-textarea"
          placeholder="Why is this document potentially irrelevant?"
          rows="3"
        ></textarea>
        <div class="modal-actions">
          <button class="modal-btn cancel" @click="flagModal = null">Cancel</button>
          <button class="modal-btn confirm" @click="submitFlag">Flag document</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import api from '@/utils/api'
import { useNotificationsStore } from '@/stores/notifications'

interface KbDocument {
  id: string
  title: string
  doi?: string
  authors?: string[]
  year?: number
  journal?: string
  abstract?: string
  source_type: string
  processing_status: string
  num_chunks?: number
  num_facts?: number
  general_domain?: string
  potentially_irrelevant?: boolean
  flag_reason?: string
  flagged_at?: string
  created_at?: string
}

const props = defineProps<{ isCurator: boolean }>()

const documents = ref<KbDocument[]>([])
const loading = ref(false)
const totalCount = ref(0)
const currentPage = ref(1)
const pageSize = ref(50)

const totalPages = computed(() => Math.max(1, Math.ceil(totalCount.value / pageSize.value)))
const rangeStart = computed(() => totalCount.value === 0 ? 0 : (currentPage.value - 1) * pageSize.value + 1)
const rangeEnd = computed(() => Math.min(currentPage.value * pageSize.value, totalCount.value))

const searchQuery = ref('')
const statusFilter = ref('')
const typeFilter = ref('')
const flagFilter = ref('')
const includeWeb = ref(false)
const expandedId = ref<string | null>(null)
const flagModal = ref<KbDocument | null>(null)
const flagReason = ref('')
const notifs = useNotificationsStore()

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  processing: 'Processing…',
  completed: 'Indexed',
  failed: 'Failed',
}

let debounceTimer: ReturnType<typeof setTimeout>
function debouncedFetch() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => { currentPage.value = 1; fetchDocuments() }, 350)
}

function resetAndFetch() {
  currentPage.value = 1
  fetchDocuments()
}

function goToPage(page: number) {
  const clamped = Math.max(1, Math.min(page, totalPages.value))
  if (clamped === currentPage.value) return
  currentPage.value = clamped
  fetchDocuments()
}

onMounted(fetchDocuments)

async function fetchDocuments() {
  loading.value = true
  expandedId.value = null
  try {
    const params = new URLSearchParams()
    if (searchQuery.value) params.set('search', searchQuery.value)
    if (statusFilter.value) params.set('status', statusFilter.value)
    if (typeFilter.value) params.set('source_type', typeFilter.value)
    if (flagFilter.value) params.set('flagged', flagFilter.value)
    if (includeWeb.value) params.set('include_web', 'true')
    params.set('limit', String(pageSize.value))
    params.set('skip', String((currentPage.value - 1) * pageSize.value))

    const resp = await api.get(`/kb/documents/?${params}`)
    const { items, total } = resp.data as { items: KbDocument[]; total: number }
    documents.value = items ?? []
    totalCount.value = total ?? 0
  } catch {
    // interceptor shows error toast
  } finally {
    loading.value = false
  }
}

function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function formattedAuthors(doc: KbDocument): string {
  const a = doc.authors || []
  if (a.length === 0) return ''
  if (a.length <= 3) return a.join(', ')
  return a.slice(0, 3).join(', ') + ` et al.`
}

function typeShort(t: string): string {
  return { pdf_local: 'PDF', pdf_upload: 'PDF', web: 'ABS', text: 'TXT', manual: 'MAN' }[t] ?? 'DOC'
}

function typeLabel(t: string): string {
  return { pdf_local: 'PDF (local)', pdf_upload: 'PDF (upload)', web: 'Abstract', text: 'Text', manual: 'Manual' }[t] ?? t
}

function typeClass(t: string): string {
  return { pdf_local: 'pdf', pdf_upload: 'pdf', web: 'abs', text: 'txt', manual: 'man' }[t] ?? 'doc'
}

function formatDate(iso: string): string {
  try { return new Date(iso).toLocaleDateString() } catch { return '' }
}

function openFlagModal(doc: KbDocument) {
  flagModal.value = doc
  flagReason.value = ''
}

async function submitFlag() {
  if (!flagModal.value) return
  const doc = flagModal.value
  flagModal.value = null
  try {
    await api.post(`/kb/documents/${doc.id}/flag`, { reason: flagReason.value })
    const idx = documents.value.findIndex((d) => d.id === doc.id)
    if (idx !== -1) {
      documents.value[idx] = {
        ...documents.value[idx],
        potentially_irrelevant: true,
        flag_reason: flagReason.value,
        flagged_at: new Date().toISOString(),
      }
    }
    notifs.success('Document flagged')
  } catch {
    // interceptor shows error
  }
}

async function unflag(doc: KbDocument) {
  try {
    await api.delete(`/kb/documents/${doc.id}/flag`)
    const idx = documents.value.findIndex((d) => d.id === doc.id)
    if (idx !== -1) {
      documents.value[idx] = {
        ...documents.value[idx],
        potentially_irrelevant: false,
        flag_reason: undefined,
        flagged_at: undefined,
      }
    }
    notifs.success('Flag removed')
  } catch {
    // interceptor shows error
  }
}

async function confirmDelete(doc: KbDocument) {
  if (doc.processing_status === 'completed') return
  if (!window.confirm(`Delete "${doc.title}"? This cannot be undone.`)) return
  try {
    await api.delete(`/kb/documents/${doc.id}`)
    documents.value = documents.value.filter((d) => d.id !== doc.id)
    totalCount.value = Math.max(0, totalCount.value - 1)
    notifs.success('Document deleted')
  } catch {
    // interceptor shows error (409 includes reason)
  }
}

defineExpose({ fetchDocuments })
</script>

<style scoped>
.document-library {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  flex: 1;
  min-height: 0;
}

/* Filters */
.filters-bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.search-wrap {
  position: relative;
  flex: 1;
  min-width: 200px;
}

.search-icon {
  position: absolute;
  left: 0.6rem;
  top: 50%;
  transform: translateY(-50%);
  color: #9ca3af;
  pointer-events: none;
}

.search-input {
  width: 100%;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0.4rem 0.75rem 0.4rem 2rem;
  font-size: 0.875rem;
  outline: none;
  transition: border-color 0.15s;
}
.search-input:focus { border-color: #3b82f6; }

.filter-select {
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0.4rem 0.5rem;
  font-size: 0.82rem;
  background: white;
  cursor: pointer;
  outline: none;
}
.filter-select:focus { border-color: #3b82f6; }

.web-toggle {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.82rem;
  color: #6b7280;
  cursor: pointer;
  white-space: nowrap;
}
.web-toggle input { cursor: pointer; }

.count-badge {
  font-size: 0.78rem;
  color: #6b7280;
  white-space: nowrap;
  margin-left: auto;
}

.chunk-count {
  font-size: 0.68rem;
  color: #9ca3af;
  margin-top: 0.15rem;
}

/* States */
.state-msg {
  text-align: center;
  padding: 3rem;
  color: #9ca3af;
  font-size: 0.9rem;
}
.state-msg.empty { color: #6b7280; }

/* Table */
.table-wrap {
  flex: 1;
  overflow-y: auto;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  min-height: 0;
}

.doc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.doc-table thead th {
  position: sticky;
  top: 0;
  background: #f9fafb;
  padding: 0.5rem 0.75rem;
  text-align: left;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #6b7280;
  border-bottom: 1px solid #e5e7eb;
  white-space: nowrap;
  z-index: 1;
}

.doc-row {
  cursor: pointer;
  transition: background 0.1s;
}
.doc-row:hover { background: #f9fafb; }
.doc-row.expanded { background: #eff6ff; }
.doc-row.flagged td:first-child { border-left: 3px solid #f59e0b; }

.doc-row td {
  padding: 0.6rem 0.75rem;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: middle;
}

.col-type   { width: 52px; }
.col-title  { min-width: 220px; }
.col-year   { width: 60px; white-space: nowrap; }
.col-journal { width: 180px; }
.col-status { width: 90px; }
.col-actions { width: 72px; }

/* Type pill */
.type-pill {
  display: inline-block;
  font-size: 0.68rem;
  font-weight: 700;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  letter-spacing: 0.04em;
}
.type-pill.pdf { background: #fee2e2; color: #991b1b; }
.type-pill.abs { background: #dbeafe; color: #1e40af; }
.type-pill.txt { background: #f3f4f6; color: #374151; }
.type-pill.man { background: #f0fdf4; color: #166534; }
.type-pill.doc { background: #faf5ff; color: #7c3aed; }

/* Title cell */
.title-text {
  font-weight: 500;
  color: #111827;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.flag-pill {
  display: inline-flex;
  align-items: center;
  font-size: 0.68rem;
  font-weight: 600;
  background: #fef3c7;
  color: #92400e;
  border-radius: 4px;
  padding: 0.1rem 0.35rem;
  white-space: nowrap;
}

.authors-text {
  font-size: 0.75rem;
  color: #6b7280;
  margin-top: 0.15rem;
}

/* Journal cell */
.journal-text {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 160px;
  color: #374151;
}

.doi-link {
  display: block;
  font-size: 0.72rem;
  color: #3b82f6;
  text-decoration: none;
  margin-top: 0.1rem;
}
.doi-link:hover { text-decoration: underline; }

/* Status badge */
.status-badge {
  display: inline-block;
  font-size: 0.72rem;
  border-radius: 4px;
  padding: 0.15rem 0.4rem;
  white-space: nowrap;
}
.status-badge.pending    { background: #fef9c3; color: #713f12; }
.status-badge.processing { background: #dbeafe; color: #1e40af; }
.status-badge.completed  { background: #dcfce7; color: #166534; }
.status-badge.failed     { background: #fee2e2; color: #991b1b; }

/* Actions */
.col-actions { text-align: right; }

.act-btn {
  background: none;
  border: 1px solid transparent;
  border-radius: 5px;
  padding: 0.25rem;
  cursor: pointer;
  color: #9ca3af;
  display: inline-flex;
  align-items: center;
  transition: color 0.15s, background 0.15s, border-color 0.15s;
}
.act-btn:hover { color: #374151; border-color: #d1d5db; background: #f9fafb; }
.act-btn.flag:hover   { color: #d97706; border-color: #fcd34d; background: #fffbeb; }
.act-btn.unflag       { color: #d97706; }
.act-btn.unflag:hover { color: #92400e; border-color: #fcd34d; background: #fef3c7; }
.act-btn.delete:hover { color: #dc2626; border-color: #fca5a5; background: #fef2f2; }
.act-btn.disabled { opacity: 0.3; cursor: not-allowed; pointer-events: none; }

/* Abstract expansion */
.abstract-row td {
  background: #f8faff;
  border-bottom: 1px solid #dbeafe;
  padding: 0;
}

.abstract-content {
  padding: 0.75rem 1rem 0.75rem 2.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.abstract-text {
  font-size: 0.82rem;
  color: #374151;
  line-height: 1.55;
}
.abstract-text strong { display: block; margin-bottom: 0.2rem; color: #111827; }
.abstract-text.muted { color: #9ca3af; }

.meta-chips {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.chip {
  font-size: 0.72rem;
  background: #e0e7ff;
  color: #3730a3;
  border-radius: 4px;
  padding: 0.1rem 0.45rem;
}

.flag-note {
  font-size: 0.78rem;
  color: #92400e;
  background: #fef3c7;
  border-radius: 4px;
  padding: 0.3rem 0.6rem;
}

/* Pagination */
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  padding: 0.4rem 0.25rem;
  gap: 0.75rem;
}

.pagination-left,
.pagination-right {
  min-width: 120px;
}

.pagination-right {
  text-align: right;
}

.pagination-center {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.page-size-select {
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0.3rem 0.4rem;
  font-size: 0.78rem;
  background: white;
  cursor: pointer;
  outline: none;
  color: #374151;
}

.page-btn {
  background: white;
  border: 1px solid #d1d5db;
  border-radius: 5px;
  padding: 0.25rem 0.55rem;
  font-size: 0.85rem;
  cursor: pointer;
  color: #374151;
  line-height: 1;
  transition: background 0.1s, border-color 0.1s;
}
.page-btn:hover:not(:disabled) { background: #f3f4f6; border-color: #9ca3af; }
.page-btn:disabled { opacity: 0.35; cursor: not-allowed; }

.page-info {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.82rem;
  color: #374151;
  white-space: nowrap;
}

.page-input {
  width: 52px;
  border: 1px solid #d1d5db;
  border-radius: 5px;
  padding: 0.25rem 0.4rem;
  font-size: 0.82rem;
  text-align: center;
  outline: none;
}
.page-input:focus { border-color: #3b82f6; }

.page-range {
  font-size: 0.78rem;
  color: #6b7280;
  white-space: nowrap;
}

/* Flag modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.modal {
  background: white;
  border-radius: 10px;
  padding: 1.5rem;
  width: 420px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  box-shadow: 0 10px 30px rgba(0,0,0,0.15);
}

.modal h3 {
  font-size: 1rem;
  font-weight: 700;
  color: #111827;
}

.modal-doc-title {
  font-size: 0.82rem;
  color: #6b7280;
  font-style: italic;
}

.modal-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #374151;
}

.modal-textarea {
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  font-family: inherit;
  font-size: 0.875rem;
  resize: vertical;
  outline: none;
}
.modal-textarea:focus { border-color: #3b82f6; }

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.25rem;
}

.modal-btn {
  border: none;
  border-radius: 6px;
  padding: 0.4rem 1rem;
  font-size: 0.875rem;
  cursor: pointer;
}
.modal-btn.cancel  { background: #f3f4f6; color: #374151; }
.modal-btn.cancel:hover  { background: #e5e7eb; }
.modal-btn.confirm { background: #d97706; color: white; }
.modal-btn.confirm:hover { background: #b45309; }
</style>
