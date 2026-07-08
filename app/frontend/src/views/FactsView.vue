<template>
  <div class="facts-view">
    <header class="page-header">
      <div class="header-left">
        <h1>Facts</h1>
        <span class="subtitle">Knowledge base fact library</span>
      </div>
      <button v-if="activeTab === 'submissions'" class="btn-primary" @click="showCreateModal = true">
        + New fact
      </button>
    </header>

    <!-- Tab bar -->
    <div class="tab-bar">
      <button
        v-for="t in TABS"
        :key="t.key"
        :class="['tab-btn', { active: activeTab === t.key }]"
        @click="activeTab = t.key"
      >
        {{ t.label }}
      </button>
    </div>

    <!-- ── Stylized Facts tab ─────────────────────────────────── -->
    <template v-if="activeTab === 'sf'">
      <div class="filters-bar">
        <div class="search-wrap">
          <svg class="search-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input v-model="sf.search" placeholder="Search statements…" class="search-input" @input="sfDebouncedFetch" />
        </div>
        <select v-model="sf.category" class="filter-select" @change="sfResetFetch">
          <option value="">All categories</option>
          <option v-for="c in SF_CATEGORIES" :key="c.value" :value="c.value">{{ c.label }}</option>
        </select>
        <span class="count-badge">{{ sf.total.toLocaleString() }} stylized fact{{ sf.total !== 1 ? 's' : '' }}</span>
      </div>

      <div v-if="sf.loading" class="state-msg">Loading…</div>
      <div v-else-if="sf.items.length === 0" class="state-msg empty">No stylized facts found.</div>

      <div v-else class="table-wrap">
        <table class="fact-table">
          <thead>
            <tr>
              <th class="col-num">#</th>
              <th class="col-statement">Statement</th>
              <th class="col-cat">Category</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in sf.items"
              :key="item.id"
              :class="['fact-row', { expanded: sf.expandedId === item.id }]"
              @click="sf.expandedId = sf.expandedId === item.id ? null : item.id"
            >
              <td class="col-num text-muted">{{ item.sf_number }}</td>
              <td class="col-statement">
                <span :class="sf.expandedId === item.id ? '' : 'clamp-2'">{{ item.statement }}</span>
              </td>
              <td class="col-cat">
                <span class="cat-chip">{{ formatCategory(item.category) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="sf.total > 0" class="pagination-bar">
        <div class="pagination-left">
          <select v-model="sf.pageSize" class="page-size-select" @change="sfResetFetch">
            <option :value="25">25 / page</option>
            <option :value="50">50 / page</option>
            <option :value="100">100 / page</option>
            <option :value="200">200 / page</option>
          </select>
        </div>
        <div class="pagination-center">
          <button class="page-btn" :disabled="sf.page <= 1" @click="sfGoTo(1)">«</button>
          <button class="page-btn" :disabled="sf.page <= 1" @click="sfGoTo(sf.page - 1)">‹</button>
          <span class="page-info">
            Page
            <input class="page-input" type="number" :min="1" :max="sfTotalPages" :value="sf.page"
              @change="sfGoTo(Number(($event.target as HTMLInputElement).value))" />
            of {{ sfTotalPages.toLocaleString() }}
          </span>
          <button class="page-btn" :disabled="sf.page >= sfTotalPages" @click="sfGoTo(sf.page + 1)">›</button>
          <button class="page-btn" :disabled="sf.page >= sfTotalPages" @click="sfGoTo(sfTotalPages)">»</button>
        </div>
        <div class="pagination-right">
          <span class="page-range">{{ sfRangeStart }}–{{ sfRangeEnd }} of {{ sf.total.toLocaleString() }}</span>
        </div>
      </div>
    </template>

    <!-- ── KB Facts tab ───────────────────────────────────────── -->
    <template v-if="activeTab === 'kbfacts'">
      <div class="filters-bar">
        <div class="search-wrap">
          <svg class="search-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input v-model="kf.search" placeholder="Search fact content…" class="search-input" @input="kfDebouncedFetch" />
        </div>
        <select v-model="kf.domain" class="filter-select" @change="kfResetFetch">
          <option value="">All domains</option>
          <option value="reproduction">Reproduction</option>
          <option value="__none__">No domain</option>
        </select>
        <span class="count-badge">{{ kf.total.toLocaleString() }} fact{{ kf.total !== 1 ? 's' : '' }}</span>
      </div>

      <div v-if="kf.loading" class="state-msg">Loading…</div>
      <div v-else-if="kf.items.length === 0" class="state-msg empty">No facts found.</div>

      <div v-else class="table-wrap">
        <table class="fact-table">
          <thead>
            <tr>
              <th class="col-content">Content</th>
              <th class="col-conf">Confidence</th>
              <th class="col-domain">Domain</th>
              <th class="col-tags">Tags</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="item in kf.items" :key="item.id">
              <tr
                :class="['fact-row', { expanded: kf.expandedId === item.id }]"
                @click="kf.expandedId = kf.expandedId === item.id ? null : item.id"
              >
                <td class="col-content">
                  <span :class="kf.expandedId === item.id ? '' : 'clamp-2'">{{ item.content }}</span>
                </td>
                <td class="col-conf">
                  <span v-if="item.confidence != null" class="conf-pill">
                    {{ Math.round(item.confidence * 100) }}%
                  </span>
                  <span v-else class="text-muted">—</span>
                </td>
                <td class="col-domain">
                  <span v-if="item.general_domain" class="domain-chip">{{ item.general_domain }}</span>
                  <span v-else class="text-muted">—</span>
                </td>
                <td class="col-tags">
                  <span v-for="tag in (item.tags || [])" :key="tag" class="tag-chip">{{ tag }}</span>
                </td>
              </tr>
              <tr v-if="kf.expandedId === item.id" class="expanded-row">
                <td colspan="4">
                  <div class="expanded-content">
                    <p class="expanded-text">{{ item.content }}</p>
                    <div class="expanded-meta">
                      <span v-if="item.document_id" class="meta-item">Doc: {{ item.document_id }}</span>
                      <span v-if="item.page_number" class="meta-item">p. {{ item.page_number }}</span>
                      <span v-if="item.created_at" class="meta-item">{{ formatDate(item.created_at) }}</span>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <div v-if="kf.total > 0" class="pagination-bar">
        <div class="pagination-left">
          <select v-model="kf.pageSize" class="page-size-select" @change="kfResetFetch">
            <option :value="25">25 / page</option>
            <option :value="50">50 / page</option>
            <option :value="100">100 / page</option>
            <option :value="200">200 / page</option>
          </select>
        </div>
        <div class="pagination-center">
          <button class="page-btn" :disabled="kf.page <= 1" @click="kfGoTo(1)">«</button>
          <button class="page-btn" :disabled="kf.page <= 1" @click="kfGoTo(kf.page - 1)">‹</button>
          <span class="page-info">
            Page
            <input class="page-input" type="number" :min="1" :max="kfTotalPages" :value="kf.page"
              @change="kfGoTo(Number(($event.target as HTMLInputElement).value))" />
            of {{ kfTotalPages.toLocaleString() }}
          </span>
          <button class="page-btn" :disabled="kf.page >= kfTotalPages" @click="kfGoTo(kf.page + 1)">›</button>
          <button class="page-btn" :disabled="kf.page >= kfTotalPages" @click="kfGoTo(kfTotalPages)">»</button>
        </div>
        <div class="pagination-right">
          <span class="page-range">{{ kfRangeStart }}–{{ kfRangeEnd }} of {{ kf.total.toLocaleString() }}</span>
        </div>
      </div>
    </template>

    <!-- ── Submissions tab ────────────────────────────────────── -->
    <template v-if="activeTab === 'submissions'">
      <div class="filters-bar">
        <input v-model="sub.search" placeholder="Search facts…" class="search-input" @input="subDebouncedFetch" />
        <div class="status-tabs">
          <button
            v-for="tab in STATUS_TABS"
            :key="tab.value"
            :class="['status-tab', { active: sub.statusFilter === tab.value }]"
            @click="sub.statusFilter = tab.value; fetchSubmissions()"
          >{{ tab.label }}</button>
        </div>
        <span class="count-badge">{{ sub.items.length }} fact{{ sub.items.length !== 1 ? 's' : '' }}</span>
      </div>

      <div v-if="sub.loading" class="state-msg">Loading…</div>
      <div v-else-if="sub.items.length === 0" class="state-msg empty">No submissions found.</div>

      <ul v-else class="sub-list">
        <li v-for="fact in sub.items" :key="fact.id" class="sub-card">
          <div class="sub-body">
            <p class="sub-statement">{{ fact.statement }}</p>
            <div class="sub-meta">
              <span v-for="tag in fact.tags" :key="tag" class="tag-chip">{{ tag }}</span>
              <span v-if="fact.confidence != null" class="conf-pill">{{ Math.round(fact.confidence * 100) }}%</span>
            </div>
          </div>
          <span :class="['status-pill', fact.status]">{{ STATUS_LABELS[fact.status] || fact.status }}</span>
        </li>
      </ul>
    </template>

    <!-- Create modal -->
    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal">
          <h2>New Fact</h2>
          <form @submit.prevent="submitCreateFact">
            <label class="form-label">Statement</label>
            <textarea v-model="newFact.statement" rows="3" class="form-textarea" placeholder="State the biological fact clearly…" required></textarea>
            <label class="form-label">Tags (comma-separated)</label>
            <input v-model="newFactTagsRaw" type="text" class="form-input" placeholder="e.g. metabolism, DEB, energy" />
            <label class="form-label">Confidence</label>
            <input v-model.number="newFact.confidence" type="range" min="0" max="1" step="0.05" class="form-range" />
            <span class="range-value">{{ Math.round((newFact.confidence ?? 0) * 100) }}%</span>
            <div class="modal-actions">
              <button type="button" class="btn-secondary" @click="showCreateModal = false">Cancel</button>
              <button type="submit" class="btn-primary" :disabled="createLoading">{{ createLoading ? 'Saving…' : 'Create' }}</button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import api from '@/utils/api'
import { useNotificationsStore } from '@/stores/notifications'

const notifs = useNotificationsStore()

type TabKey = 'sf' | 'kbfacts' | 'submissions'
const TABS: { key: TabKey; label: string }[] = [
  { key: 'sf', label: 'Stylized Facts' },
  { key: 'kbfacts', label: 'KB Facts' },
  { key: 'submissions', label: 'Submissions' },
]
const activeTab = ref<TabKey>('sf')

const SF_CATEGORIES = [
  { value: 'biological_experiments_and_data_patterns', label: 'Biological Experiments & Data' },
  { value: 'dynamic_properties_and_equilibrium_states', label: 'Dynamic Properties & Equilibrium' },
  { value: 'ecological_physiological_proportions_and_relationships', label: 'Ecological & Physiological Proportions' },
  { value: 'integrative_aspects_and_emergent_properties', label: 'Integrative & Emergent Properties' },
  { value: 'metabolism_and_environment', label: 'Metabolism & Environment' },
  { value: 'microbiological_and_parasitological_aspects', label: 'Microbiological & Parasitological' },
  { value: 'molecular_and_cellular_foundations', label: 'Molecular & Cellular Foundations' },
  { value: 'reproductive_strategy', label: 'Reproductive Strategy' },
  { value: 'temporal_characteristics_of_development_and_growth', label: 'Development & Growth Timing' },
  { value: 'thermoregulation_and_biophysical_constraints', label: 'Thermoregulation & Biophysics' },
  { value: 'tin_klanjscek_new_facts', label: 'Tin Klanjšček New Facts' },
  { value: 'toxicology_and_ecotoxicology', label: 'Toxicology & Ecotoxicology' },
  { value: 'universal_laws_of_biological_organization', label: 'Universal Laws of Biology' },
]

function formatCategory(cat: string): string {
  const found = SF_CATEGORIES.find((c) => c.value === cat)
  return found ? found.label : cat.replace(/_/g, ' ')
}

function formatDate(iso: string): string {
  try { return new Date(iso).toLocaleDateString() } catch { return '' }
}

// ── Stylized Facts state ─────────────────────────────────────────────────

interface SfItem {
  id: string
  sf_number: number
  statement: string
  category: string
  status: string
  created_at?: string
}

const sf = reactive({
  items: [] as SfItem[],
  total: 0,
  loading: false,
  page: 1,
  pageSize: 50,
  search: '',
  category: '',
  expandedId: null as string | null,
})

const sfTotalPages = computed(() => Math.max(1, Math.ceil(sf.total / sf.pageSize)))
const sfRangeStart = computed(() => sf.total === 0 ? 0 : (sf.page - 1) * sf.pageSize + 1)
const sfRangeEnd = computed(() => Math.min(sf.page * sf.pageSize, sf.total))

let sfDebTimer: ReturnType<typeof setTimeout>
function sfDebouncedFetch() {
  clearTimeout(sfDebTimer)
  sfDebTimer = setTimeout(() => { sf.page = 1; fetchSf() }, 350)
}
function sfResetFetch() { sf.page = 1; fetchSf() }
function sfGoTo(p: number) {
  const c = Math.max(1, Math.min(p, sfTotalPages.value))
  if (c === sf.page) return
  sf.page = c; fetchSf()
}

async function fetchSf() {
  sf.loading = true
  sf.expandedId = null
  try {
    const params = new URLSearchParams()
    if (sf.search) params.set('search', sf.search)
    if (sf.category) params.set('category', sf.category)
    params.set('limit', String(sf.pageSize))
    params.set('skip', String((sf.page - 1) * sf.pageSize))
    const { data } = await api.get(`/kb/stylized-facts/?${params}`)
    sf.items = data.items ?? []
    sf.total = data.total ?? 0
  } catch { /* interceptor shows error */ } finally {
    sf.loading = false
  }
}

// ── KB Facts state ───────────────────────────────────────────────────────

interface KfItem {
  id: string
  content: string
  document_id?: string
  page_number?: number
  confidence?: number
  tags?: string[]
  general_domain?: string
  status?: string
  created_at?: string
}

const kf = reactive({
  items: [] as KfItem[],
  total: 0,
  loading: false,
  page: 1,
  pageSize: 50,
  search: '',
  domain: '',
  expandedId: null as string | null,
})

const kfTotalPages = computed(() => Math.max(1, Math.ceil(kf.total / kf.pageSize)))
const kfRangeStart = computed(() => kf.total === 0 ? 0 : (kf.page - 1) * kf.pageSize + 1)
const kfRangeEnd = computed(() => Math.min(kf.page * kf.pageSize, kf.total))

let kfDebTimer: ReturnType<typeof setTimeout>
function kfDebouncedFetch() {
  clearTimeout(kfDebTimer)
  kfDebTimer = setTimeout(() => { kf.page = 1; fetchKf() }, 350)
}
function kfResetFetch() { kf.page = 1; fetchKf() }
function kfGoTo(p: number) {
  const c = Math.max(1, Math.min(p, kfTotalPages.value))
  if (c === kf.page) return
  kf.page = c; fetchKf()
}

async function fetchKf() {
  kf.loading = true
  kf.expandedId = null
  try {
    const params = new URLSearchParams()
    if (kf.search) params.set('search', kf.search)
    if (kf.domain) params.set('domain', kf.domain)
    params.set('limit', String(kf.pageSize))
    params.set('skip', String((kf.page - 1) * kf.pageSize))
    const { data } = await api.get(`/kb/facts/?${params}`)
    kf.items = data.items ?? []
    kf.total = data.total ?? 0
  } catch { /* interceptor shows error */ } finally {
    kf.loading = false
  }
}

// ── Submissions state ────────────────────────────────────────────────────

interface SubFact {
  id: string
  statement: string
  confidence?: number
  tags: string[]
  status: string
}

const STATUS_TABS = [
  { label: 'All', value: '' },
  { label: 'Pending', value: 'pending_review' },
  { label: 'Published', value: 'published' },
  { label: 'Rejected', value: 'rejected' },
]
const STATUS_LABELS: Record<string, string> = {
  pending_review: 'Pending', published: 'Published', rejected: 'Rejected', suggestion: 'Suggestion',
}

const sub = reactive({
  items: [] as SubFact[],
  loading: false,
  search: '',
  statusFilter: '',
})

let subDebTimer: ReturnType<typeof setTimeout>
function subDebouncedFetch() {
  clearTimeout(subDebTimer)
  subDebTimer = setTimeout(fetchSubmissions, 350)
}

async function fetchSubmissions() {
  sub.loading = true
  try {
    const params = new URLSearchParams({ limit: '200' })
    if (sub.statusFilter) params.set('status_filter', sub.statusFilter)
    const { data } = await api.get(`/facts/?${params}`)
    const all = (data as any[]).map((f: any) => ({ ...f, id: f._id || f.id }))
    sub.items = sub.search
      ? all.filter((f) => f.statement?.toLowerCase().includes(sub.search.toLowerCase()))
      : all
  } finally {
    sub.loading = false
  }
}

// ── Create modal ─────────────────────────────────────────────────────────

const showCreateModal = ref(false)
const createLoading = ref(false)
const newFact = ref({ statement: '', confidence: 0.8 })
const newFactTagsRaw = ref('')

async function submitCreateFact() {
  createLoading.value = true
  try {
    const tags = newFactTagsRaw.value.split(',').map((t) => t.trim()).filter(Boolean)
    await api.post('/facts/', { ...newFact.value, tags })
    notifs.success('Fact created')
    showCreateModal.value = false
    newFact.value = { statement: '', confidence: 0.8 }
    newFactTagsRaw.value = ''
    await fetchSubmissions()
  } finally {
    createLoading.value = false
  }
}

// ── Init ─────────────────────────────────────────────────────────────────

onMounted(() => {
  fetchSf()
})

watch(activeTab, (tab) => {
  if (tab === 'sf' && sf.items.length === 0) fetchSf()
  if (tab === 'kbfacts' && kf.items.length === 0) fetchKf()
  if (tab === 'submissions' && sub.items.length === 0) fetchSubmissions()
})
</script>

<style scoped>
.facts-view {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  height: 100%;
  min-height: 0;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  flex-shrink: 0;
}
.header-left { display: flex; flex-direction: column; gap: 0.1rem; }
.page-header h1 { font-size: 1.4rem; font-weight: 700; color: #111827; line-height: 1.2; }
.subtitle { font-size: 0.8rem; color: #9ca3af; }

/* Tab bar */
.tab-bar {
  display: flex;
  gap: 0.25rem;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}
.tab-btn {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  color: #6b7280;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
  margin-bottom: -1px;
}
.tab-btn:hover { color: #374151; }
.tab-btn.active { color: #2563eb; border-bottom-color: #2563eb; font-weight: 600; }

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

.count-badge { font-size: 0.78rem; color: #6b7280; white-space: nowrap; margin-left: auto; }

/* Status tabs (submissions) */
.status-tabs { display: flex; gap: 0.25rem; }
.status-tab {
  background: none; border: 1px solid #e5e7eb;
  border-radius: 9999px; padding: 0.25rem 0.75rem;
  font-size: 0.78rem; cursor: pointer; color: #6b7280;
}
.status-tab.active { background: #3b82f6; color: white; border-color: #3b82f6; }

/* State */
.state-msg { text-align: center; padding: 3rem; color: #9ca3af; font-size: 0.9rem; }
.state-msg.empty { color: #6b7280; }

/* Table */
.table-wrap {
  flex: 1;
  overflow-y: auto;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  min-height: 0;
}
.fact-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.fact-table thead th {
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
.fact-row {
  cursor: pointer;
  transition: background 0.1s;
}
.fact-row:hover { background: #f9fafb; }
.fact-row.expanded { background: #eff6ff; }
.fact-row td {
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: top;
}

/* Stylized facts columns */
.col-num { width: 48px; text-align: right; }
.col-statement { min-width: 300px; }
.col-cat { width: 220px; }

/* KB facts columns */
.col-content { min-width: 340px; }
.col-conf { width: 70px; }
.col-domain { width: 120px; }
.col-tags { width: 160px; }

/* Text helpers */
.clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.text-muted { color: #9ca3af; font-size: 0.8rem; }

/* Chips */
.cat-chip {
  display: inline-block;
  font-size: 0.7rem;
  background: #e0e7ff;
  color: #3730a3;
  border-radius: 4px;
  padding: 0.1rem 0.4rem;
  white-space: nowrap;
}
.domain-chip {
  display: inline-block;
  font-size: 0.7rem;
  background: #d1fae5;
  color: #065f46;
  border-radius: 4px;
  padding: 0.1rem 0.4rem;
}
.tag-chip {
  display: inline-block;
  font-size: 0.68rem;
  background: #f3f4f6;
  color: #4b5563;
  border-radius: 4px;
  padding: 0.1rem 0.35rem;
  margin-right: 0.2rem;
  margin-bottom: 0.15rem;
}
.conf-pill {
  display: inline-block;
  font-size: 0.72rem;
  background: #ede9fe;
  color: #7c3aed;
  border-radius: 4px;
  padding: 0.1rem 0.35rem;
}

/* Expanded rows */
.expanded-row td {
  background: #f8faff;
  border-bottom: 1px solid #dbeafe;
  padding: 0;
}
.expanded-content {
  padding: 0.65rem 1rem 0.65rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.expanded-text { font-size: 0.85rem; color: #111827; line-height: 1.6; }
.expanded-meta { display: flex; gap: 0.75rem; flex-wrap: wrap; }
.meta-item { font-size: 0.75rem; color: #6b7280; }

/* Pagination */
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  padding: 0.4rem 0.25rem;
  gap: 0.75rem;
}
.pagination-left, .pagination-right { min-width: 120px; }
.pagination-right { text-align: right; }
.pagination-center { display: flex; align-items: center; gap: 0.35rem; }

.page-size-select {
  border: 1px solid #d1d5db; border-radius: 6px;
  padding: 0.3rem 0.4rem; font-size: 0.78rem;
  background: white; cursor: pointer; outline: none; color: #374151;
}
.page-btn {
  background: white; border: 1px solid #d1d5db; border-radius: 5px;
  padding: 0.25rem 0.55rem; font-size: 0.85rem; cursor: pointer;
  color: #374151; line-height: 1; transition: background 0.1s, border-color 0.1s;
}
.page-btn:hover:not(:disabled) { background: #f3f4f6; border-color: #9ca3af; }
.page-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.page-info { display: flex; align-items: center; gap: 0.35rem; font-size: 0.82rem; color: #374151; white-space: nowrap; }
.page-input { width: 52px; border: 1px solid #d1d5db; border-radius: 5px; padding: 0.25rem 0.4rem; font-size: 0.82rem; text-align: center; outline: none; }
.page-input:focus { border-color: #3b82f6; }
.page-range { font-size: 0.78rem; color: #6b7280; white-space: nowrap; }

/* Submissions list */
.sub-list { list-style: none; display: flex; flex-direction: column; gap: 0.5rem; overflow-y: auto; flex: 1; min-height: 0; }
.sub-card {
  background: white; border: 1px solid #e5e7eb; border-radius: 8px;
  padding: 0.75rem 1rem; display: flex; align-items: flex-start; gap: 1rem;
}
.sub-body { flex: 1; min-width: 0; }
.sub-statement { font-size: 0.9rem; color: #111827; line-height: 1.5; margin-bottom: 0.35rem; }
.sub-meta { display: flex; flex-wrap: wrap; gap: 0.3rem; }

.status-pill { font-size: 0.72rem; border-radius: 9999px; padding: 0.15rem 0.5rem; font-weight: 500; white-space: nowrap; flex-shrink: 0; }
.status-pill.pending_review { background: #fef9c3; color: #713f12; }
.status-pill.published { background: #dcfce7; color: #166534; }
.status-pill.rejected { background: #fee2e2; color: #991b1b; }
.status-pill.suggestion { background: #dbeafe; color: #1e40af; }

/* Buttons */
.btn-primary {
  background: #3b82f6; color: white; border: none;
  border-radius: 6px; padding: 0.45rem 1rem; font-size: 0.875rem; cursor: pointer;
}
.btn-primary:hover:not(:disabled) { background: #2563eb; }
.btn-primary:disabled { background: #93c5fd; cursor: not-allowed; }
.btn-secondary {
  background: white; color: #374151; border: 1px solid #d1d5db;
  border-radius: 6px; padding: 0.4rem 1rem; font-size: 0.875rem; cursor: pointer;
}
.btn-secondary:hover { background: #f9fafb; }

/* Modal */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: white; border-radius: 10px; padding: 1.5rem; width: 100%; max-width: 480px; box-shadow: 0 8px 24px rgba(0,0,0,0.15); display: flex; flex-direction: column; gap: 0.75rem; }
.modal h2 { font-size: 1.1rem; font-weight: 700; color: #111827; }
.form-label { font-size: 0.82rem; font-weight: 500; color: #374151; display: block; margin-bottom: 0.2rem; }
.form-textarea, .form-input { width: 100%; border: 1px solid #d1d5db; border-radius: 6px; padding: 0.5rem 0.75rem; font-family: inherit; font-size: 0.875rem; box-sizing: border-box; }
.form-textarea:focus, .form-input:focus { outline: none; border-color: #3b82f6; }
.form-textarea { resize: vertical; }
.form-range { width: 100%; }
.range-value { font-size: 0.82rem; color: #6b7280; }
.modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 0.5rem; }
</style>
