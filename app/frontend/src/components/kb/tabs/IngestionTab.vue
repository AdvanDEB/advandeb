<template>
  <div class="tab-content ingestion-tab" role="tabpanel" aria-label="Ingestion">

    <!-- LEFT PANEL: Sources -->
    <div class="ing-panel ing-left">
      <div class="ing-panel-header">
        <span class="ing-panel-title">Sources</span>
        <div class="ing-source-tabs">
          <button
            type="button"
            :class="['ing-tab-btn', { active: sourceTab === 'upload' }]"
            :aria-pressed="sourceTab === 'upload'"
            @click="sourceTab = 'upload'"
          >Local Upload</button>
          <button
            type="button"
            :class="['ing-tab-btn', { active: sourceTab === 'remote' }]"
            :aria-pressed="sourceTab === 'remote'"
            @click="sourceTab = 'remote'; if (!sources.length) loadSources()"
          >File Explorer</button>
        </div>
      </div>

      <!-- ── Upload tab ───────────────────────────────────── -->
      <div v-if="sourceTab === 'upload'" class="ing-panel-body">
        <!-- Drop zone. The whole zone is the one control that opens the file
             picker, so it is the button; "Browse files" is only its label. -->
        <div
          :class="['drop-zone', { 'drop-zone--over': dropOver }]"
          role="button"
          tabindex="0"
          aria-label="Choose PDF files to upload, or drag and drop them here"
          @dragover.prevent="dropOver = true"
          @dragleave.prevent="dropOver = false"
          @drop.prevent="onDrop"
          @click="fileInputEl?.click()"
          @keydown.enter.prevent="fileInputEl?.click()"
          @keydown.space.prevent="fileInputEl?.click()"
        >
          <input
            ref="fileInputEl"
            type="file"
            multiple
            accept=".pdf"
            style="display:none"
            @change="onFileInputChange"
          />
          <div class="drop-icon" aria-hidden="true">📄</div>
          <p class="drop-label">Drag &amp; drop files here</p>
          <p class="drop-sub">PDF files only</p>
          <span class="btn sm" aria-hidden="true">Browse files</span>
        </div>

        <!-- Staged file list -->
        <div v-if="stagedFiles.length" class="staged-list">
          <div class="staged-header">
            <span class="ing-sublabel">Staged ({{ stagedFiles.length }})</span>
            <button type="button" class="btn xs" @click="stagedFiles = []">Clear all</button>
          </div>
          <ul class="staged-ul">
            <li v-for="(f, i) in stagedFiles" :key="i" class="staged-item">
              <span class="staged-name">{{ f.name }}</span>
              <span class="staged-size dim">{{ formatBytes(f.size) }}</span>
              <button class="staged-remove" type="button" @click="stagedFiles.splice(i, 1)"
                      :title="`Remove ${f.name}`" :aria-label="`Remove ${f.name}`">✕</button>
            </li>
          </ul>
        </div>
        <div v-else class="drop-empty dim">No files staged yet</div>

        <div class="ing-panel-footer">
          <button
            type="button"
            class="btn primary"
            :disabled="stagedFiles.length === 0 || uploadRunning"
            @click="uploadAndRun"
          >{{ uploadRunning ? 'Starting…' : 'Start Ingestion' }}</button>
        </div>
      </div>

      <!-- ── File Explorer tab ────────────────────────────── -->
      <div v-else class="ing-panel-body ing-panel-body--explorer">
        <div class="explorer-scroll">
          <div class="remote-toolbar">
            <button type="button" class="btn sm" @click="loadSources">{{ sources.length ? 'Refresh' : 'Load Sources' }}</button>
          </div>

          <div v-if="!sources.length" class="drop-empty dim">No sources — click "Load Sources"</div>
          <ul v-else class="folder-list">
            <li v-for="s in sources" :key="s.path" class="folder-item">
              <div class="folder-row">
                <input
                  type="checkbox"
                  class="cb"
                  :aria-label="`Select folder ${s.name}`"
                  :checked="selectedFolders.has(s.path)"
                  @change="toggleFolder({ path: s.path, name: s.name, files: [], subdirs: [] })"
                />
                <button
                  type="button"
                  class="folder-expand-btn"
                  :aria-expanded="expandedFolders.has(s.path)"
                  :aria-label="`${expandedFolders.has(s.path) ? 'Collapse' : 'Expand'} ${s.name}`"
                  @click="toggleExpand(s.path)"
                >
                  {{ expandedFolders.has(s.path) ? '▾' : '▸' }}
                </button>
                <span class="folder-name">{{ s.name }}</span>
                <span class="folder-count dim">{{ s.pdf_count }} PDF{{ s.pdf_count !== 1 ? 's' : '' }}</span>
              </div>
              <template v-if="expandedFolders.has(s.path)">
                <div v-if="!folderFiles[s.path]" class="dim file-loading">Loading…</div>
                <FolderTree
                  v-else
                  :node="(folderFiles[s.path] as FolderNode)"
                  :selected-files="selectedFiles"
                  :selected-folders="selectedFolders"
                  @toggle-file="toggleFile"
                  @toggle-folder="toggleFolder"
                />
              </template>
            </li>
          </ul>
        </div>

        <div class="ing-panel-footer">
          <button
            type="button"
            class="btn primary"
            :disabled="(selectedFolders.size === 0 && selectedFiles.size === 0)"
            @click="scanAndRun"
          >Scan &amp; Start Ingestion</button>
        </div>
      </div>
    </div>

    <!-- Divider -->
    <div class="ing-divider" />

    <!-- RIGHT PANEL: Batch Management -->
    <div class="ing-panel ing-right">
      <div class="ing-panel-header">
        <span class="ing-panel-title">Ingestion Batches</span>
        <button type="button" class="btn sm" @click="loadBatches">Refresh</button>
      </div>

      <div class="ing-panel-body">
        <div v-if="!batches.length" class="empty-state">No ingestion batches yet</div>
        <div v-else class="table-scroll">
          <table class="data-table batch-table">
            <thead>
              <tr>
                <th>Batch ID</th>
                <th>Progress</th>
                <th>Status</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <!-- The whole row opens the batch for a pointer; the ID button is
                   the keyboard route to the same thing. -->
              <tr
                v-for="b in batches"
                :key="b._id"
                :class="['batch-row', { 'batch-row--selected': selectedBatchId === b._id }]"
                @click="loadJobsForBatch(b._id)"
              >
                <td class="mono">
                  <button
                    type="button"
                    class="batch-open-btn"
                    :aria-pressed="selectedBatchId === b._id"
                    :aria-label="`Show jobs for batch ${b._id.slice(-8)}`"
                    @click.stop="loadJobsForBatch(b._id)"
                  >{{ b._id.slice(-8) }}</button>
                </td>
                <td class="batch-progress-cell">
                  <template v-if="batchProgress[b._id] != null">
                    <div class="progress-bar">
                      <div class="progress-fill" :style="{ width: `${batchProgress[b._id]}%` }" />
                    </div>
                    <span class="progress-label">{{ batchProgress[b._id] }}%</span>
                  </template>
                  <span v-else class="dim">—</span>
                  <span v-if="b.num_files" class="batch-doc-count">{{ b.num_files }} doc{{ b.num_files === 1 ? '' : 's' }}</span>
                </td>
                <td>
                  <span class="status-pill" :class="`status-${b.status}`">
                    <span v-if="b.status === 'running'" class="spin-dot" />
                    {{ b.status }}
                  </span>
                </td>
                <td>{{ formatDate(b.created_at, '—') }}</td>
                <td class="actions-cell">
                  <button type="button" class="btn xs" @click.stop="runBatch(b._id)" :disabled="b.status === 'running'">Run</button>
                  <button
                    v-if="b.status === 'running'"
                    type="button"
                    class="btn xs danger"
                    :disabled="stoppingBatch.has(b._id)"
                    @click.stop="stopBatch(b._id)"
                  >{{ stoppingBatch.has(b._id) ? '…' : 'Stop' }}</button>
                  <button
                    type="button"
                    class="btn xs danger"
                    :disabled="b.status === 'running' || deletingBatch.has(b._id)"
                    @click.stop="deleteBatch(b._id)"
                  >{{ deletingBatch.has(b._id) ? '…' : 'Delete' }}</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Job details for selected batch -->
        <div v-if="selectedBatchJobs.length" class="jobs-section">
          <h3 class="subsection-title">Jobs — batch <span class="mono">{{ selectedBatchId?.slice(-8) }}</span></h3>
          <div class="table-scroll">
            <table class="data-table">
              <thead>
                <tr><th>File</th><th>Status</th><th>Stage</th><th>Progress</th></tr>
              </thead>
              <tbody>
                <tr v-for="j in selectedBatchJobs" :key="j._id">
                  <td class="mono small">{{ j.source_path_or_url?.split('/').pop() }}</td>
                  <td>
                    <span class="status-pill" :class="`status-${j.status}`">{{ j.status }}</span>
                    <span v-if="j.already_processed" class="already-pill" title="Already ingested">cached</span>
                  </td>
                  <td class="dim">{{ j.stage || '—' }}</td>
                  <td>
                    <div class="progress-cell">
                      <div class="progress-bar">
                        <div class="progress-fill" :style="{ width: `${j.status === 'completed' ? 100 : (j.progress ?? 0)}%` }" />
                      </div>
                      <span class="progress-label">{{ j.status === 'completed' ? '100' : (j.progress ?? 0) }}%</span>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import FolderTree from '@/components/kb/FolderTree.vue'
import type { FolderNode } from '@/components/kb/FolderTree.vue'
import {
  fetchBatches as _fetchBatches, fetchJobs,
  runBatch as _runBatch, deleteBatch as _deleteBatch, stopBatch as _stopBatch,
  fetchSources as _fetchSources, scanFolders, fetchFolderFiles,
  uploadPdf,
} from '@/utils/kbApi'
import type { IngestionBatch, IngestionJob, SourceEntry } from '@/utils/kbApi'
import { useKnowledgeBuilderStore } from '@/stores/knowledgeBuilder'
import { useDialogStore } from '@/stores/dialog'
import { formatBytes, formatDate } from '@/utils/format'

const kb = useKnowledgeBuilderStore()
const { activeTab } = storeToRefs(kb)
const { setError } = kb
const dialog = useDialogStore()

const batches         = ref<IngestionBatch[]>([])
const selectedBatchId = ref<string | null>(null)
const selectedBatchJobs = ref<IngestionJob[]>([])
const sources         = ref<SourceEntry[]>([])

// Source panel sub-tab
const sourceTab = ref<'upload' | 'remote'>('upload')

// ---- Upload / drag-drop -------------------------------------------------------

const stagedFiles   = ref<File[]>([])
const dropOver      = ref(false)
const uploadRunning = ref(false)
const fileInputEl   = ref<HTMLInputElement | null>(null)

function onDrop(e: DragEvent) {
  dropOver.value = false
  const files = Array.from(e.dataTransfer?.files ?? [])
  addStagedFiles(files)
}

function onFileInputChange(e: Event) {
  const files = Array.from((e.target as HTMLInputElement).files ?? [])
  addStagedFiles(files)
  // reset input so the same file can be re-added after removal
  ;(e.target as HTMLInputElement).value = ''
}

function addStagedFiles(files: File[]) {
  const existing = new Set(stagedFiles.value.map(f => f.name + f.size))
  for (const f of files) {
    if (!existing.has(f.name + f.size)) stagedFiles.value.push(f)
  }
}

async function uploadAndRun() {
  if (!stagedFiles.value.length) return
  const pdfs = stagedFiles.value.filter(f => f.name.toLowerCase().endsWith('.pdf'))
  if (!pdfs.length) {
    kb.error = 'Only PDF files are supported for upload. Please add PDF files.'
    return
  }
  if (pdfs.length < stagedFiles.value.length) {
    // Non-PDFs silently skipped — note in error bar
    const skipped = stagedFiles.value.length - pdfs.length
    kb.error = `${skipped} non-PDF file(s) skipped — only PDFs are supported.`
  }
  uploadRunning.value = true
  const results: string[] = []
  try {
    for (const file of pdfs) {
      const res = await uploadPdf(file)
      results.push(res.batch_id)
    }
    stagedFiles.value = []
    await loadBatches()
    // Auto-select the last batch so its jobs appear immediately
    if (results.length) await loadJobsForBatch(results[results.length - 1])
  } catch (e) { setError(e) }
  finally { uploadRunning.value = false }
}

// ---- Batches ------------------------------------------------------------------

async function loadBatches() {
  try { batches.value = await _fetchBatches(50) } catch (e) { setError(e) }
}

// Auto-poll while any batch is running
let batchPollTimer: ReturnType<typeof setInterval> | null = null

function startBatchPolling() {
  if (batchPollTimer) return
  batchPollTimer = setInterval(async () => {
    await loadBatches()
    if (selectedBatchId.value) await loadJobsForBatch(selectedBatchId.value)
    const hasRunning = batches.value.some(b => b.status === 'running' || b.status === 'queued')
    if (!hasRunning) stopBatchPolling()
  }, 3000)
}

function stopBatchPolling() {
  if (batchPollTimer) { clearInterval(batchPollTimer); batchPollTimer = null }
}

watch(batches, (list) => {
  const hasRunning = list.some(b => b.status === 'running' || b.status === 'queued')
  if (hasRunning) startBatchPolling()
  else stopBatchPolling()
})

async function loadJobsForBatch(batchId: string) {
  selectedBatchId.value = batchId
  try { selectedBatchJobs.value = await fetchJobs(batchId) } catch (e) { setError(e) }
}

/**
 * Per-batch overall progress (0–100), or null when not computable.
 * For the selected batch we use actual job progress data.
 * For all others we derive from the batch status alone.
 */
const batchProgress = computed<Record<string, number | null>>(() => {
  const map: Record<string, number | null> = {}
  for (const b of batches.value) {
    if (b._id === selectedBatchId.value && selectedBatchJobs.value.length) {
      const jobs = selectedBatchJobs.value
      const total = jobs.length
      let sum = 0
      for (const j of jobs) {
        if (j.status === 'completed') sum += 100
        else sum += j.progress ?? 0
      }
      map[b._id] = Math.round(sum / total)
    } else {
      const s = b.status
      if (s === 'completed' || s === 'failed' || s === 'stopped' || s === 'mixed') {
        map[b._id] = 100
      } else if (s === 'pending' || s === 'queued') {
        map[b._id] = 0
      } else {
        map[b._id] = null  // running but no job data loaded yet
      }
    }
  }
  return map
})

async function runBatch(batchId: string) {
  try { await _runBatch(batchId); await loadBatches() } catch (e) { setError(e) }
}

const deletingBatch  = ref<Set<string>>(new Set())
const stoppingBatch  = ref<Set<string>>(new Set())

async function stopBatch(batchId: string) {
  stoppingBatch.value = new Set([...stoppingBatch.value, batchId])
  try {
    await _stopBatch(batchId)
    await loadBatches()
    if (selectedBatchId.value === batchId) await loadJobsForBatch(batchId)
  } catch (e) { setError(e) }
  finally {
    const next = new Set(stoppingBatch.value)
    next.delete(batchId)
    stoppingBatch.value = next
  }
}

async function deleteBatch(batchId: string) {
  const ok = await dialog.confirm({
    title: 'Delete this batch?',
    message: 'The batch and all its jobs will be deleted.',
    confirmLabel: 'Delete',
    tone: 'danger',
  })
  if (!ok) return
  deletingBatch.value = new Set([...deletingBatch.value, batchId])
  try {
    await _deleteBatch(batchId)
    batches.value = batches.value.filter(b => b._id !== batchId)
    if (selectedBatchId.value === batchId) {
      selectedBatchId.value = null
      selectedBatchJobs.value = []
    }
  } catch (e) { setError(e) }
  finally {
    const next = new Set(deletingBatch.value)
    next.delete(batchId)
    deletingBatch.value = next
  }
}

// ---- Remote sources (file explorer) -----------------------------------------

// Folder/file selection state
const expandedFolders = ref<Set<string>>(new Set())
const folderFiles     = ref<Record<string, FolderNode | null>>({})
const selectedFolders = ref<Set<string>>(new Set())
const selectedFiles   = ref<Set<string>>(new Set())

async function loadSources() {
  try {
    const res = await _fetchSources()
    sources.value = res?.entries ?? []
    // Reset selection when sources reload
    expandedFolders.value = new Set()
    folderFiles.value = {}
    selectedFolders.value = new Set()
    selectedFiles.value = new Set()
  } catch (e) { setError(e) }
}

async function toggleExpand(folderPath: string) {
  const next = new Set(expandedFolders.value)
  if (next.has(folderPath)) {
    next.delete(folderPath)
  } else {
    next.add(folderPath)
    if (!(folderPath in folderFiles.value)) {
      folderFiles.value = { ...folderFiles.value, [folderPath]: null }  // loading sentinel
      try {
        const res = (await fetchFolderFiles(folderPath)) as { tree?: FolderNode } | null
        folderFiles.value = { ...folderFiles.value, [folderPath]: res?.tree ?? null }
      } catch (e) {
        folderFiles.value = { ...folderFiles.value, [folderPath]: null }
        setError(e)
      }
    }
  }
  expandedFolders.value = next
}

/** Collect all file paths recursively under a FolderNode */
function allFilePaths(node: FolderNode): string[] {
  const paths = node.files.map(f => f.path)
  for (const sub of node.subdirs) paths.push(...allFilePaths(sub))
  return paths
}

/**
 * Toggle a folder node (emitted from FolderTree or the top-level checkbox).
 * Selecting a folder adds it to selectedFolders (whole-folder scan);
 * deselecting removes it and clears any individually-selected files under it.
 */
function toggleFolder(node: FolderNode) {
  const next = new Set(selectedFolders.value)
  // Files to clear: from the tree if loaded, otherwise by path prefix
  function filesToClear(): string[] {
    const treePaths = allFilePaths(node)
    if (treePaths.length > 0) return treePaths
    // Fallback: clear by path prefix
    return Array.from(selectedFiles.value).filter(
      f => f === node.path || f.startsWith(node.path + '/') || f.startsWith(node.path + '\\')
    )
  }
  if (next.has(node.path)) {
    next.delete(node.path)
    const nextFiles = new Set(selectedFiles.value)
    for (const f of filesToClear()) nextFiles.delete(f)
    selectedFiles.value = nextFiles
  } else {
    next.add(node.path)
    const nextFiles = new Set(selectedFiles.value)
    for (const f of filesToClear()) nextFiles.delete(f)
    selectedFiles.value = nextFiles
  }
  selectedFolders.value = next
}

function toggleFile(filePath: string) {
  const next = new Set(selectedFiles.value)
  if (next.has(filePath)) next.delete(filePath)
  else next.add(filePath)
  selectedFiles.value = next
}

async function scanAndRun() {
  const folders = Array.from(selectedFolders.value)
  const files   = Array.from(selectedFiles.value)
  if (!folders.length && !files.length) {
    await dialog.alert({ title: 'Nothing selected', message: 'Select at least one folder or file first.' })
    return
  }
  try {
    const batch = await scanFolders(folders, files)
    await _runBatch(batch.batch_id)
    await loadBatches()
  } catch (e) { setError(e) }
}

// ---- Lifecycle ------------------------------------------------------------------

// Batches load each time the tab is shown (it is kept alive with v-show).
watch(activeTab, (tab) => {
  if (tab === 'ingestion') loadBatches()
}, { immediate: true })

onUnmounted(stopBatchPolling)
</script>

<style scoped>
.tab-content { flex: 1; min-height: 0; overflow: hidden; }

/* ---- Two-panel layout ------------------------------------------------------- */
.ingestion-tab {
  display: flex;
  flex-direction: row;
  height: 100%;
  overflow: hidden;
}

.ing-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}
.ing-left  { width: 45%; flex-shrink: 0; }
.ing-right { flex: 1; }

.ing-divider {
  width: 1px;
  flex-shrink: 0;
  background: #334155;
}

.ing-panel-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.65rem 1rem;
  border-bottom: 1px solid #334155;
  flex-shrink: 0;
  background: #1e293b;
}

.ing-panel-title {
  font-size: 0.78rem;
  font-weight: 700;
  color: #e2e8f0;
  letter-spacing: 0.02em;
}

/* Sub-tab toggle */
.ing-source-tabs {
  display: flex;
  background: #0f172a;
  border-radius: 5px;
  border: 1px solid #334155;
  overflow: hidden;
  margin-left: auto;
}
.ing-tab-btn {
  background: none;
  border: none;
  padding: 0.25rem 0.65rem;
  font-size: 0.7rem;
  color: #64748b;
  cursor: pointer;
  white-space: nowrap;
}
.ing-tab-btn:hover { color: #cbd5e1; background: #1e293b; }
.ing-tab-btn.active { background: #1e293b; color: #60a5fa; font-weight: 600; }

.ing-panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* Explorer variant: outer body does not scroll — inner .explorer-scroll does */
.ing-panel-body--explorer {
  overflow: hidden;
  padding: 0;
}

.explorer-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.ing-panel-body--explorer .ing-panel-footer {
  margin-top: 0;
  padding: 0.65rem 1rem;
}

.ing-panel-footer {
  padding-top: 0.65rem;
  border-top: 1px solid #334155;
  margin-top: auto;
  flex-shrink: 0;
}

.ing-sublabel {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #64748b;
  font-weight: 700;
}

/* ---- Drop zone ------------------------------------------------------------ */
.drop-zone {
  border: 2px dashed #334155;
  border-radius: 8px;
  padding: 1.5rem 1rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  background: #0f172a;
  text-align: center;
  flex-shrink: 0;
}
.drop-zone:hover, .drop-zone--over {
  border-color: var(--app-primary);
  background: #1e3a5f22;
}
.drop-zone:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }
.drop-icon  { font-size: 1.8rem; line-height: 1; }
.drop-label { font-size: 0.8rem; color: #cbd5e1; margin: 0; font-weight: 500; }
.drop-sub   { font-size: 0.65rem; color: #475569; margin: 0; }
.drop-empty { font-size: 0.78rem; padding: 0.4rem 0; }

/* ---- Staged file list ----------------------------------------------------- */
.staged-list { display: flex; flex-direction: column; gap: 0.35rem; }
.staged-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.staged-ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 220px;
  overflow-y: auto;
}
.staged-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.5rem;
  background: #0f172a;
  border-radius: 4px;
  border: 1px solid #1e293b;
}
.staged-name {
  flex: 1;
  font-size: 0.73rem;
  color: #cbd5e1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.staged-size {
  font-size: 0.65rem;
  white-space: nowrap;
  flex-shrink: 0;
}
.staged-remove {
  background: none;
  border: none;
  color: #475569;
  cursor: pointer;
  font-size: 0.7rem;
  padding: 0.1rem 0.25rem;
  border-radius: 3px;
  line-height: 1;
  flex-shrink: 0;
}
.staged-remove:hover { background: #7f1d1d22; color: #fca5a5; }

/* ---- Remote / File Explorer ----------------------------------------------- */
.remote-toolbar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

/* ---- Batch table ---------------------------------------------------------- */
.table-scroll { overflow-x: auto; }

.batch-table { table-layout: fixed; }
.batch-table th:nth-child(1) { width: 90px; }
.batch-table th:nth-child(2) { width: auto; }
.batch-table th:nth-child(3) { width: 90px; }
.batch-table th:nth-child(4) { width: 90px; }
.batch-table th:nth-child(5) { width: 110px; }

.batch-row--selected td { background: #1e3a5f44; }

/* The batch ID is the row's keyboard control; it looks like the plain ID. */
.batch-open-btn {
  font: inherit;
  color: inherit;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  text-align: left;
}
.batch-open-btn:hover { text-decoration: underline; }
.batch-open-btn:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; border-radius: 2px; }

/* Running spinner dot */
.spin-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  margin-right: 4px;
  animation: pulse-dot 1s ease-in-out infinite;
  vertical-align: middle;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.4; transform: scale(0.7); }
}

.jobs-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding-top: 0.75rem;
  border-top: 1px solid #334155;
}

.folder-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.folder-item { border-radius: 4px; overflow: hidden; }
.folder-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.4rem;
  background: #0f172a;
  border-radius: 4px;
  cursor: default;
}
.folder-expand-btn {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 0 0.2rem;
  font-size: 0.75rem;
  line-height: 1;
}
.folder-name { font-size: 0.82rem; color: #e2e8f0; flex: 1; }
.folder-count { font-size: 0.72rem; }

.file-loading { font-size: 0.76rem; padding: 0.2rem 0.3rem; }
.cb { accent-color: #6366f1; cursor: pointer; }

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
.batch-row { cursor: pointer; }

.status-pill {
  font-size: 0.65rem;
  padding: 0.15rem 0.45rem;
  border-radius: 3px;
  font-weight: 600;
  white-space: nowrap;
}
.status-completed, .status-confirmed { background: #065f46; color: #6ee7b7; }
.status-pending, .status-queued { background: #1e3a5f; color: #93c5fd; }
.status-running { background: #78350f; color: #fde68a; }
.status-failed, .status-rejected { background: #7f1d1d; color: #fca5a5; }
.status-mixed { background: #4a1942; color: #d8b4fe; }
.status-stopped { background: #292524; color: #d6d3d1; }
.status-cancelled { background: #1c1917; color: #a8a29e; }

.already-pill {
  font-size: 0.6rem;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  background: #1c3a2e;
  color: #6ee7b7;
  margin-left: 0.3rem;
  white-space: nowrap;
}

.actions-cell { display: flex; gap: 0.3rem; align-items: center; }

.progress-cell { display: flex; align-items: center; gap: 0.4rem; }
.batch-progress-cell { display: flex; align-items: center; gap: 0.4rem; min-width: 100px; }
.batch-doc-count { font-size: 0.62rem; color: #475569; white-space: nowrap; flex-shrink: 0; margin-left: 0.2rem; }
.progress-bar { height: 6px; background: #1e293b; border-radius: 3px; width: 100%; flex: 1; }
.progress-fill { height: 100%; background: var(--app-primary); border-radius: 3px; transition: width 0.3s; }
.progress-label { font-size: 0.65rem; color: #64748b; white-space: nowrap; flex-shrink: 0; }

.empty-state { padding: 2rem; text-align: center; color: #475569; font-size: 0.85rem; }

.subsection-title { font-size: 0.85rem; font-weight: 600; color: #94a3b8; margin: 0; }

/* ---- Utilities ------------------------------------------------------------- */
.mono { font-family: monospace; }
.small { font-size: 0.7rem !important; }
.dim { color: #475569; }

/* ---- Narrow screens ----------------------------------------------------------
   The two panels stack. (This block used to sit above the base rules, so the
   divider's 1px width won and it vanished; it is last now.) The fixed-layout
   batch table keeps its column widths and scrolls sideways instead. */
@media (max-width: 768px) {
  .ingestion-tab { flex-direction: column; }
  .ing-divider   { width: 100%; height: 1px; }
  .ing-left      { width: 100%; height: 50%; flex: none; }
  .ing-right     { width: 100%; flex: 1; min-height: 0; }
  .ing-panel-header { flex-wrap: wrap; }
  .batch-table { min-width: 560px; }
}

/* ---- Touch ------------------------------------------------------------------ */
@media (pointer: coarse) {
  .btn,
  .ing-tab-btn,
  .folder-expand-btn,
  .staged-remove { min-height: var(--app-touch); }
  .folder-expand-btn,
  .staged-remove { min-width: var(--app-touch); }
  /* Only a label: the whole drop zone is the touch target. */
  .drop-zone .btn { min-height: 0; }
}
</style>
