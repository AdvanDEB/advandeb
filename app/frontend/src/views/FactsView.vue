<template>
  <div class="facts-view">
    <header class="page-header">
      <h1>Facts</h1>
      <div class="header-actions">
        <button class="btn-primary" @click="showCreateModal = true">+ New fact</button>
      </div>
    </header>

    <!-- Filters -->
    <div class="filters-bar">
      <input
        v-model="search"
        placeholder="Search facts…"
        class="search-input"
        aria-label="Search facts"
        @input="debouncedFetch"
      />
      <div class="status-tabs" role="tablist">
        <button
          v-for="tab in STATUS_TABS"
          :key="tab.value"
          :class="['status-tab', { active: statusFilter === tab.value }]"
          role="tab"
          :aria-selected="statusFilter === tab.value"
          @click="statusFilter = tab.value; fetchFacts()"
        >
          {{ tab.label }}
        </button>
      </div>
      <span class="count-info">{{ facts.length }} facts</span>
    </div>

    <!-- Skeleton loading -->
    <div v-if="loading" class="skeleton-list" aria-live="polite">
      <div v-for="n in 6" :key="n" class="skeleton-card">
        <LoadingSkeleton height="0.9rem" width="80%" />
        <LoadingSkeleton height="0.75rem" width="40%" />
      </div>
    </div>

    <!-- Empty state -->
    <div v-else-if="facts.length === 0" class="empty-state" role="status">
      <p>No facts found{{ search ? ' matching your search' : '' }}.</p>
    </div>

    <!-- Facts list -->
    <ul v-else class="facts-list" role="list">
      <li
        v-for="fact in facts"
        :key="fact.id"
        class="fact-card"
        tabindex="0"
        @keydown.enter="selectedFact = fact"
      >
        <div class="fact-body">
          <p class="fact-statement">{{ fact.statement }}</p>
          <div class="fact-meta">
            <span v-for="tag in fact.tags" :key="tag" class="tag">{{ tag }}</span>
            <span v-if="fact.confidence != null" class="confidence">
              {{ Math.round(fact.confidence * 100) }}% confidence
            </span>
            <span v-if="fact.source_page" class="source-page">p. {{ fact.source_page }}</span>
          </div>
        </div>
        <div class="fact-status-col">
          <span :class="['status-pill', fact.status]">{{ STATUS_LABELS[fact.status] || fact.status }}</span>
        </div>
      </li>
    </ul>

    <!-- Create fact modal -->
    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <h2 id="modal-title">New Fact</h2>
          <form @submit.prevent="submitCreateFact">
            <label class="form-label" for="fact-statement">Statement</label>
            <textarea
              id="fact-statement"
              v-model="newFact.statement"
              rows="3"
              class="form-textarea"
              placeholder="State the biological fact clearly…"
              required
            ></textarea>

            <label class="form-label" for="fact-tags">Tags (comma-separated)</label>
            <input
              id="fact-tags"
              v-model="newFactTagsRaw"
              type="text"
              class="form-input"
              placeholder="e.g. metabolism, DEB, energy"
            />

            <label class="form-label" for="fact-confidence">Confidence</label>
            <input
              id="fact-confidence"
              v-model.number="newFact.confidence"
              type="range"
              min="0"
              max="1"
              step="0.05"
              class="form-range"
            />
            <span class="range-value">{{ Math.round((newFact.confidence ?? 0) * 100) }}%</span>

            <div class="modal-actions">
              <button type="button" class="btn-secondary" @click="showCreateModal = false">Cancel</button>
              <button type="submit" class="btn-primary" :disabled="createLoading">
                {{ createLoading ? 'Saving…' : 'Create' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/utils/api'
import { useNotificationsStore } from '@/stores/notifications'
import LoadingSkeleton from '@/components/common/LoadingSkeleton.vue'

interface Fact {
  id: string
  statement: string
  confidence?: number
  tags: string[]
  status: string
  source_page?: number
}

const STATUS_TABS = [
  { label: 'All', value: '' },
  { label: 'Pending review', value: 'pending_review' },
  { label: 'Published', value: 'published' },
  { label: 'Rejected', value: 'rejected' },
]

const STATUS_LABELS: Record<string, string> = {
  pending_review: 'Pending',
  published: 'Published',
  rejected: 'Rejected',
  suggestion: 'Suggestion',
}

const facts = ref<Fact[]>([])
const loading = ref(false)
const search = ref('')
const statusFilter = ref('')
const showCreateModal = ref(false)
const createLoading = ref(false)
const selectedFact = ref<Fact | null>(null)
const notifs = useNotificationsStore()

const newFact = ref({ statement: '', confidence: 0.8 })
const newFactTagsRaw = ref('')

let debounceTimer: ReturnType<typeof setTimeout>
function debouncedFetch() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(fetchFacts, 350)
}

onMounted(fetchFacts)

async function fetchFacts() {
  loading.value = true
  try {
    const params = new URLSearchParams({ limit: '200' })
    if (statusFilter.value) params.set('status_filter', statusFilter.value)
    const { data } = await api.get(`/facts?${params}`)
    const all = (data as Fact[]).map((f: any) => ({ ...f, id: f._id || f.id }))
    facts.value = search.value
      ? all.filter((f) => f.statement.toLowerCase().includes(search.value.toLowerCase()))
      : all
  } finally {
    loading.value = false
  }
}

async function submitCreateFact() {
  createLoading.value = true
  try {
    const tags = newFactTagsRaw.value.split(',').map((t) => t.trim()).filter(Boolean)
    await api.post('/facts', { ...newFact.value, tags })
    notifs.success('Fact created')
    showCreateModal.value = false
    newFact.value = { statement: '', confidence: 0.8 }
    newFactTagsRaw.value = ''
    await fetchFacts()
  } finally {
    createLoading.value = false
  }
}
</script>

<style scoped>
.facts-view {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 1000px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.page-header h1 { font-size: 1.5rem; font-weight: 700; color: #111827; }

.btn-primary {
  background: #3b82f6; color: white; border: none;
  border-radius: 6px; padding: 0.4rem 1rem;
  font-size: 0.875rem; cursor: pointer;
}
.btn-primary:hover:not(:disabled) { background: #2563eb; }
.btn-primary:disabled { background: #93c5fd; cursor: not-allowed; }

.btn-secondary {
  background: white; color: #374151;
  border: 1px solid #d1d5db; border-radius: 6px;
  padding: 0.4rem 1rem; font-size: 0.875rem; cursor: pointer;
}
.btn-secondary:hover { background: #f9fafb; }

.filters-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.search-input {
  flex: 1; min-width: 180px;
  border: 1px solid #d1d5db; border-radius: 6px;
  padding: 0.4rem 0.75rem; font-size: 0.875rem;
}
.search-input:focus { outline: none; border-color: #3b82f6; }

.status-tabs { display: flex; gap: 0.25rem; }

.status-tab {
  background: none; border: 1px solid #e5e7eb;
  border-radius: 9999px; padding: 0.25rem 0.75rem;
  font-size: 0.78rem; cursor: pointer; color: #6b7280;
  transition: all 0.15s;
}
.status-tab:hover { border-color: #93c5fd; color: #1d4ed8; }
.status-tab.active { background: #3b82f6; color: white; border-color: #3b82f6; }

.count-info { font-size: 0.78rem; color: #9ca3af; }

/* Skeleton */
.skeleton-list { display: flex; flex-direction: column; gap: 0.5rem; }
.skeleton-card {
  background: #f9fafb; border: 1px solid #e5e7eb;
  border-radius: 8px; padding: 0.75rem 1rem;
  display: flex; flex-direction: column; gap: 0.5rem;
}

/* Empty */
.empty-state { text-align: center; padding: 3rem; color: #9ca3af; font-size: 0.9rem; }

/* List */
.facts-list { list-style: none; display: flex; flex-direction: column; gap: 0.5rem; }

.fact-card {
  background: white; border: 1px solid #e5e7eb;
  border-radius: 8px; padding: 0.75rem 1rem;
  display: flex; align-items: flex-start; gap: 1rem;
  cursor: pointer; transition: box-shadow 0.15s, border-color 0.15s;
}
.fact-card:hover, .fact-card:focus {
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  border-color: #93c5fd; outline: none;
}

.fact-body { flex: 1; min-width: 0; }
.fact-statement { font-size: 0.9rem; color: #111827; line-height: 1.5; margin-bottom: 0.4rem; }

.fact-meta { display: flex; flex-wrap: wrap; gap: 0.3rem; }

.tag {
  font-size: 0.7rem; background: #f3f4f6; color: #4b5563;
  border-radius: 4px; padding: 0.1rem 0.35rem;
}

.confidence { font-size: 0.75rem; color: #7c3aed; background: #ede9fe; border-radius: 4px; padding: 0.1rem 0.35rem; }
.source-page { font-size: 0.75rem; color: #9ca3af; }

.fact-status-col { flex-shrink: 0; }

.status-pill {
  font-size: 0.72rem; border-radius: 9999px;
  padding: 0.15rem 0.5rem; font-weight: 500;
}
.status-pill.pending_review { background: #fef9c3; color: #713f12; }
.status-pill.published      { background: #dcfce7; color: #166534; }
.status-pill.rejected       { background: #fee2e2; color: #991b1b; }
.status-pill.suggestion     { background: #dbeafe; color: #1e40af; }

/* Modal */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.modal {
  background: white; border-radius: 10px; padding: 1.5rem;
  width: 100%; max-width: 480px; box-shadow: 0 8px 24px rgba(0,0,0,0.15);
  display: flex; flex-direction: column; gap: 0.75rem;
}
.modal h2 { font-size: 1.1rem; font-weight: 700; color: #111827; }

.form-label { font-size: 0.82rem; font-weight: 500; color: #374151; display: block; margin-bottom: 0.2rem; }

.form-textarea, .form-input {
  width: 100%; border: 1px solid #d1d5db; border-radius: 6px;
  padding: 0.5rem 0.75rem; font-family: inherit; font-size: 0.875rem;
}
.form-textarea:focus, .form-input:focus { outline: none; border-color: #3b82f6; }
.form-textarea { resize: vertical; }

.form-range { width: 100%; }
.range-value { font-size: 0.82rem; color: #6b7280; }

.modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 0.5rem; }
</style>
