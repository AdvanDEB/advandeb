<template>
  <div class="document-library">
    <!-- Controls bar -->
    <div class="controls">
      <input
        v-model="searchQuery"
        placeholder="Search documents…"
        class="search-input"
        @input="debouncedFetch"
      />

      <select v-model="statusFilter" @change="fetchDocuments" class="status-filter">
        <option value="">All statuses</option>
        <option value="pending">Pending</option>
        <option value="processing">Processing</option>
        <option value="completed">Completed</option>
        <option value="failed">Failed</option>
      </select>

      <span class="count-badge">{{ documents.length }} document{{ documents.length !== 1 ? 's' : '' }}</span>
    </div>

    <!-- Loading / empty states -->
    <div v-if="loading" class="state-message">Loading…</div>
    <div v-else-if="documents.length === 0" class="state-message empty">
      No documents found. Upload some above.
    </div>

    <!-- Document grid -->
    <div v-else class="doc-grid">
      <div
        v-for="doc in documents"
        :key="doc.id"
        class="doc-card"
        @click="$emit('open', doc)"
      >
        <div class="doc-type-icon">{{ typeIcon(doc.source_type) }}</div>

        <div class="doc-body">
          <div class="doc-title" :title="doc.title">{{ doc.title }}</div>
          <div v-if="doc.metadata?.authors" class="doc-authors">
            {{ doc.metadata.authors }}
          </div>

          <div class="doc-meta-row">
            <span v-if="doc.metadata?.year" class="meta-tag">{{ doc.metadata.year }}</span>
            <span :class="['status-badge', doc.status]">{{ STATUS_LABELS[doc.status] || doc.status }}</span>
            <span v-if="doc.extracted_facts_count > 0" class="facts-count">
              {{ doc.extracted_facts_count }} facts
            </span>
          </div>
        </div>

        <!-- Actions -->
        <div class="doc-actions" @click.stop>
          <button
            v-if="doc.status === 'pending'"
            class="action-btn embed"
            title="Trigger embedding"
            @click="embedDoc(doc.id)"
          >
            ⚙
          </button>
          <button
            class="action-btn delete"
            title="Delete document"
            @click="deleteDoc(doc.id)"
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/utils/api'
import { useNotificationsStore } from '@/stores/notifications'

interface DocMeta {
  filename?: string
  authors?: string
  year?: number
  size?: number
}

interface Document {
  id: string
  title: string
  source_type: string
  status: string
  extracted_facts_count: number
  metadata?: DocMeta
  created_at?: string
}

defineEmits<{
  (e: 'open', doc: Document): void
}>()

const documents = ref<Document[]>([])
const loading = ref(false)
const searchQuery = ref('')
const statusFilter = ref('')
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
  debounceTimer = setTimeout(fetchDocuments, 350)
}

onMounted(fetchDocuments)

async function fetchDocuments() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (searchQuery.value) params.set('search', searchQuery.value)
    if (statusFilter.value) params.set('status', statusFilter.value)
    params.set('limit', '200')

    const { data } = await api.get(`/documents?${params}`)
    documents.value = (data as Document[]).map((d: any) => ({
      ...d,
      id: d._id || d.id,
    }))
  } finally {
    loading.value = false
  }
}

async function embedDoc(docId: string) {
  try {
    await api.post(`/documents/${docId}/embed`)
    notifs.success('Embedding queued')
    await fetchDocuments()
  } catch {
    // error toast handled by api interceptor
  }
}

async function deleteDoc(docId: string) {
  if (!confirm('Delete this document?')) return
  try {
    await api.delete(`/documents/${docId}`)
    notifs.success('Document deleted')
    documents.value = documents.value.filter((d) => d.id !== docId)
  } catch {
    // error toast handled by api interceptor
  }
}

function typeIcon(sourceType: string): string {
  const icons: Record<string, string> = {
    pdf: '📕', url: '🔗', text: '📝', upload: '📄',
  }
  return icons[sourceType] || '📄'
}

// Expose refresh so parent can call after upload
defineExpose({ fetchDocuments })
</script>

<style scoped>
.document-library {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.search-input {
  flex: 1;
  min-width: 180px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0.4rem 0.75rem;
  font-size: 0.875rem;
}

.status-filter {
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0.4rem 0.5rem;
  font-size: 0.875rem;
  background: white;
}

.count-badge {
  font-size: 0.78rem;
  color: #6b7280;
  white-space: nowrap;
}

.state-message {
  text-align: center;
  padding: 3rem;
  color: #9ca3af;
  font-size: 0.9rem;
}

.state-message.empty { color: #6b7280; }

.doc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 0.75rem;
}

.doc-card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 0.75rem;
  cursor: pointer;
  display: flex;
  gap: 0.6rem;
  align-items: flex-start;
  transition: box-shadow 0.15s, border-color 0.15s;
  position: relative;
}

.doc-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  border-color: #93c5fd;
}

.doc-type-icon {
  font-size: 1.5rem;
  flex-shrink: 0;
  padding-top: 0.1rem;
}

.doc-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.doc-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.doc-authors {
  font-size: 0.75rem;
  color: #6b7280;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.doc-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-top: 0.2rem;
}

.meta-tag {
  font-size: 0.7rem;
  background: #f3f4f6;
  color: #6b7280;
  border-radius: 4px;
  padding: 0.1rem 0.35rem;
}

.status-badge {
  font-size: 0.7rem;
  border-radius: 4px;
  padding: 0.1rem 0.35rem;
}

.status-badge.pending    { background: #fef9c3; color: #713f12; }
.status-badge.processing { background: #dbeafe; color: #1e40af; }
.status-badge.completed  { background: #dcfce7; color: #166534; }
.status-badge.failed     { background: #fee2e2; color: #991b1b; }

.facts-count {
  font-size: 0.7rem;
  color: #7c3aed;
  background: #ede9fe;
  border-radius: 4px;
  padding: 0.1rem 0.35rem;
}

.doc-actions {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  opacity: 0;
  transition: opacity 0.15s;
}

.doc-card:hover .doc-actions { opacity: 1; }

.action-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0.2rem;
  border-radius: 4px;
  line-height: 1;
  color: #6b7280;
}

.action-btn.embed:hover { background: #dbeafe; color: #1d4ed8; }
.action-btn.delete:hover { background: #fee2e2; color: #dc2626; }
</style>
