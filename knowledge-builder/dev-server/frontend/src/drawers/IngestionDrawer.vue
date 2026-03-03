<template>
  <div class="drawer-content">
    <div class="drawer-header">
      <span class="drawer-title">≡ Batch Ingestion</span>
      <div class="tabs">
        <button
          v-for="tab in tabs"
          :key="tab"
          class="tab-btn"
          :class="{ active: activeTab === tab }"
          @click="setTab(tab)"
        >{{ tab }}</button>
      </div>
    </div>

    <!-- Sources tab -->
    <div v-if="activeTab === 'Sources'" class="tab-pane">
      <div v-if="sourcesLoading" class="status">Loading sources…</div>
      <div v-else-if="sourcesError" class="status error">{{ sourcesError }}</div>
      <div v-else>
        <div class="sources-root">Root: <code>{{ sourcesRoot }}</code></div>
        <table class="data-table">
          <thead><tr><th></th><th>Folder</th><th>PDFs</th></tr></thead>
          <tbody>
            <tr v-for="entry in sourceEntries" :key="entry.path">
              <td><input type="checkbox" v-model="selectedFolders" :value="entry.path" /></td>
              <td>{{ entry.name }}</td>
              <td>{{ entry.pdf_count }}</td>
            </tr>
          </tbody>
        </table>
        <div class="action-row">
          <button class="btn-primary" :disabled="selectedFolders.length === 0 || scanning" @click="scan">
            {{ scanning ? 'Scanning…' : 'Scan Selected' }}
          </button>
          <span v-if="scanResult" class="scan-info">
            {{ scanResult.num_files }} files found (batch {{ scanResult.batch_id.slice(-6) }})
          </span>
          <button
            v-if="scanResult"
            class="btn-primary"
            :disabled="running"
            @click="runBatch"
          >{{ running ? 'Running…' : 'Run Batch' }}</button>
          <span v-if="runResult" class="scan-info ok">{{ runResult.jobs_enqueued }} jobs enqueued</span>
        </div>
        <div v-if="actionError" class="status error">{{ actionError }}</div>
      </div>
    </div>

    <!-- Batches tab -->
    <div v-if="activeTab === 'Batches'" class="tab-pane">
      <div v-if="batchesLoading" class="status">Loading…</div>
      <table v-else class="data-table">
        <thead><tr><th>ID</th><th>Status</th><th>Folders</th><th>Created</th></tr></thead>
        <tbody>
          <tr v-for="b in batches" :key="b._id">
            <td class="mono">{{ b._id ? b._id.slice(-6) : '—' }}</td>
            <td><span class="badge" :class="b.status">{{ b.status }}</span></td>
            <td>{{ (b.folders || []).length }}</td>
            <td>{{ fmtDate(b.created_at) }}</td>
          </tr>
          <tr v-if="!batches.length"><td colspan="4" class="empty-row">No batches</td></tr>
        </tbody>
      </table>
    </div>

    <!-- Jobs tab -->
    <div v-if="activeTab === 'Jobs'" class="tab-pane">
      <div v-if="jobsLoading" class="status">Loading…</div>
      <table v-else class="data-table">
        <thead><tr><th>File</th><th>Status</th><th>Progress</th><th>Error</th></tr></thead>
        <tbody>
          <tr v-for="j in jobs" :key="j._id">
            <td class="truncate">{{ j.file_path ? j.file_path.split('/').pop() : '—' }}</td>
            <td><span class="badge" :class="j.status">{{ j.status }}</span></td>
            <td>{{ j.progress ?? '—' }}</td>
            <td class="truncate error-cell">{{ j.error || '' }}</td>
          </tr>
          <tr v-if="!jobs.length"><td colspan="4" class="empty-row">No jobs</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { ingestionAPI } from '../services/api.js'

export default {
  name: 'IngestionDrawer',
  setup() {
    const tabs = ['Sources', 'Batches', 'Jobs']
    const activeTab = ref('Sources')

    // Sources
    const sourcesLoading = ref(false)
    const sourcesError = ref('')
    const sourcesRoot = ref('')
    const sourceEntries = ref([])
    const selectedFolders = ref([])
    const scanning = ref(false)
    const scanResult = ref(null)
    const running = ref(false)
    const runResult = ref(null)
    const actionError = ref('')

    // Batches
    const batchesLoading = ref(false)
    const batches = ref([])

    // Jobs
    const jobsLoading = ref(false)
    const jobs = ref([])

    onMounted(loadSources)

    async function setTab(tab) {
      activeTab.value = tab
      if (tab === 'Batches') loadBatches()
      else if (tab === 'Jobs') loadJobs()
    }

    async function loadSources() {
      sourcesLoading.value = true
      sourcesError.value = ''
      try {
        const res = await ingestionAPI.getSources()
        sourcesRoot.value = res.data.root || ''
        sourceEntries.value = res.data.entries || []
      } catch (e) {
        sourcesError.value = e.response?.data?.detail || e.message
      } finally {
        sourcesLoading.value = false
      }
    }

    async function scan() {
      if (!selectedFolders.value.length) return
      scanning.value = true
      scanResult.value = null
      runResult.value = null
      actionError.value = ''
      try {
        const res = await ingestionAPI.scanFolders(selectedFolders.value)
        scanResult.value = res.data
      } catch (e) {
        actionError.value = e.response?.data?.detail || e.message
      } finally {
        scanning.value = false
      }
    }

    async function runBatch() {
      if (!scanResult.value?.batch_id) return
      running.value = true
      runResult.value = null
      actionError.value = ''
      try {
        const res = await ingestionAPI.runBatch(scanResult.value.batch_id)
        runResult.value = res.data
      } catch (e) {
        actionError.value = e.response?.data?.detail || e.message
      } finally {
        running.value = false
      }
    }

    async function loadBatches() {
      batchesLoading.value = true
      try {
        const res = await ingestionAPI.getBatches(20)
        batches.value = res.data.batches || []
      } catch (_) {
        batches.value = []
      } finally {
        batchesLoading.value = false
      }
    }

    async function loadJobs() {
      jobsLoading.value = true
      try {
        const res = await ingestionAPI.getJobs({ limit: 50 })
        jobs.value = res.data.jobs || []
      } catch (_) {
        jobs.value = []
      } finally {
        jobsLoading.value = false
      }
    }

    function fmtDate(d) {
      if (!d) return '—'
      return new Date(d).toLocaleString()
    }

    return {
      tabs, activeTab, setTab,
      sourcesLoading, sourcesError, sourcesRoot, sourceEntries,
      selectedFolders, scanning, scanResult, running, runResult, actionError,
      batchesLoading, batches,
      jobsLoading, jobs,
      scan, runBatch, fmtDate,
    }
  },
}
</script>

<style scoped>
.drawer-content {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.drawer-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  border-bottom: 1px solid #e0e0e0;
  background: #f8f9fa;
  flex-shrink: 0;
}

.drawer-title { font-weight: 600; font-size: 14px; }

.tabs { display: flex; gap: 4px; }

.tab-btn {
  padding: 4px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
  font-size: 12px;
}

.tab-btn.active {
  background: #4a90e2;
  color: #fff;
  border-color: #4a90e2;
}

.tab-pane {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.status { color: #666; padding: 8px 0; }
.status.error { color: #e74c3c; }

.sources-root { font-size: 12px; color: #888; margin-bottom: 8px; }

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.data-table th {
  text-align: left;
  padding: 6px 8px;
  background: #f0f0f0;
  border-bottom: 2px solid #ddd;
  font-weight: 600;
  color: #555;
}

.data-table td {
  padding: 5px 8px;
  border-bottom: 1px solid #f0f0f0;
}

.data-table tr:hover td { background: #fafafa; }

.action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.btn-primary {
  padding: 6px 14px;
  background: #4a90e2;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.btn-primary:disabled { background: #aac4e8; cursor: default; }
.btn-primary:not(:disabled):hover { background: #357abd; }

.scan-info { font-size: 12px; color: #555; }
.scan-info.ok { color: #27ae60; }

.badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

.badge.pending { background: #f0f0f0; color: #555; }
.badge.queued { background: #fff3cd; color: #856404; }
.badge.running { background: #cce5ff; color: #004085; }
.badge.completed { background: #d4edda; color: #155724; }
.badge.failed { background: #f8d7da; color: #721c24; }

.truncate { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.error-cell { color: #e74c3c; }
.empty-row { text-align: center; color: #aaa; padding: 16px !important; }
.mono { font-family: monospace; }
</style>
