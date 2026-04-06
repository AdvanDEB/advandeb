<template>
  <div class="kb-view">
    <!-- Top bar -->
    <header class="kb-header">
      <div class="header-left">
        <router-link to="/" class="back-link" title="Back to app">←</router-link>
        <span class="header-title">Knowledge Builder</span>
      </div>
      <nav class="tab-nav">
        <button
          v-for="tab in TABS"
          :key="tab.id"
          :class="['tab-btn', { active: activeTab === tab.id }]"
          @click="activeTab = tab.id"
        >{{ tab.label }}</button>
      </nav>
      <div class="header-right">
        <span v-if="loading" class="loading-chip">Loading…</span>
        <span v-if="error" class="error-chip" title="Click to dismiss" @click="error = ''">{{ error }}</span>
        <button
          v-if="authStore.hasRole('administrator')"
          class="header-btn danger"
          :disabled="resetting"
          @click="confirmReset"
        >{{ resetting ? 'Resetting…' : 'Reset DB' }}</button>
      </div>
    </header>

    <!-- TAB: Graph -->
    <div v-show="activeTab === 'graph'" class="tab-content graph-tab">
      <SchemaPanel
        v-model="selectedSchema"
        :schemas="schemas"
        :stats-by-schema="statsBySchema"
        :selected-stats="selectedStats"
        :type-counts="typeCounts"
        :hidden-types="hiddenTypes"
        :hidden-edge-types="hiddenEdgeTypes"
        :rebuilding="rebuilding"
        @rebuild="handleRebuild"
        @fit-view="canvasRef?.fitView()"
        @toggle-type="toggleType"
        @toggle-edge-type="toggleEdgeType"
      />

      <div class="graph-center">
        <div v-if="!selectedSchema" class="graph-empty">
          Select a graph schema to visualise
        </div>
        <div v-else-if="graphLoading" class="graph-empty">
          Loading graph data…
        </div>
        <CosmographCanvas
          v-else
          ref="canvasRef"
          :nodes="nodes"
          :edges="edges"
          :hidden-types="hiddenTypes"
          :hidden-edge-types="hiddenEdgeTypes"
          @node-click="handleNodeClick"
          @background-click="selectedNode = null"
        />
        <div class="graph-status-bar">
          <span>{{ fmtNum(nodes.length) }} nodes · {{ fmtNum(edges.length) }} edges</span>
          <span v-if="selectedSchema" class="schema-tag">{{ selectedSchema.name }}</span>
        </div>
      </div>

      <NodeInspector
        :node="selectedNode"
        :loading="graphLoading"
        @close="selectedNode = null"
        @expand="handleExpand"
      />
    </div>

    <!-- TAB: Ingestion -->
    <div v-show="activeTab === 'ingestion'" class="tab-content ingestion-tab">

      <!-- LEFT PANEL: Sources -->
      <div class="ing-panel ing-left">
        <div class="ing-panel-header">
          <span class="ing-panel-title">Sources</span>
          <div class="ing-source-tabs">
            <button
              :class="['ing-tab-btn', { active: sourceTab === 'upload' }]"
              @click="sourceTab = 'upload'"
            >Local Upload</button>
            <button
              :class="['ing-tab-btn', { active: sourceTab === 'remote' }]"
              @click="sourceTab = 'remote'; if (!sources.length) loadSources()"
            >File Explorer</button>
          </div>
        </div>

        <!-- ── Upload tab ───────────────────────────────────── -->
        <div v-if="sourceTab === 'upload'" class="ing-panel-body">
          <!-- Drop zone -->
          <div
            :class="['drop-zone', { 'drop-zone--over': dropOver }]"
            @dragover.prevent="dropOver = true"
            @dragleave.prevent="dropOver = false"
            @drop.prevent="onDrop"
            @click="fileInputEl?.click()"
          >
            <input
              ref="fileInputEl"
              type="file"
              multiple
              accept=".pdf"
              style="display:none"
              @change="onFileInputChange"
            />
            <div class="drop-icon">📄</div>
            <p class="drop-label">Drag &amp; drop files here</p>
            <p class="drop-sub">PDF files only</p>
            <button class="btn sm" @click.stop="fileInputEl?.click()">Browse files</button>
          </div>

          <!-- Staged file list -->
          <div v-if="stagedFiles.length" class="staged-list">
            <div class="staged-header">
              <span class="ing-sublabel">Staged ({{ stagedFiles.length }})</span>
              <button class="btn xs" @click="stagedFiles = []">Clear all</button>
            </div>
            <ul class="staged-ul">
              <li v-for="(f, i) in stagedFiles" :key="i" class="staged-item">
                <span class="staged-name">{{ f.name }}</span>
                <span class="staged-size dim">{{ fmtSize(f.size) }}</span>
                <button class="staged-remove" @click="stagedFiles.splice(i, 1)" title="Remove">✕</button>
              </li>
            </ul>
          </div>
          <div v-else class="drop-empty dim">No files staged yet</div>

          <div class="ing-panel-footer">
            <button
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
              <button class="btn sm" @click="loadSources">{{ sources.length ? 'Refresh' : 'Load Sources' }}</button>
            </div>

            <div v-if="!sources.length" class="drop-empty dim">No sources — click "Load Sources"</div>
            <ul v-else class="folder-list">
              <li v-for="s in sources" :key="s.path" class="folder-item">
                <div class="folder-row">
                  <input
                    type="checkbox"
                    class="cb"
                    :checked="selectedFolders.has(s.path)"
                    @change="toggleFolder({ path: s.path, name: s.name, files: [], subdirs: [] })"
                  />
                  <button class="folder-expand-btn" @click="toggleExpand(s.path)">
                    {{ expandedFolders.has(s.path) ? '▾' : '▸' }}
                  </button>
                  <span class="folder-name">{{ s.name }}</span>
                  <span class="folder-count dim">{{ s.pdf_count }} PDF{{ s.pdf_count !== 1 ? 's' : '' }}</span>
                </div>
                <template v-if="expandedFolders.has(s.path)">
                  <div v-if="!folderFiles[s.path]" class="dim file-loading">Loading…</div>
                  <FolderTree
                    v-else
                    :node="(folderFiles[s.path] as any)"
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
          <button class="btn sm" @click="loadBatches">Refresh</button>
        </div>

        <div class="ing-panel-body">
          <div v-if="!batches.length" class="empty-state">No ingestion batches yet</div>
          <table v-else class="data-table batch-table">
            <thead>
              <tr>
                <th>Batch ID</th>
                <th>Domain</th>
                <th>Status</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="b in batches"
                :key="b._id"
                :class="['batch-row', { 'batch-row--selected': selectedBatchId === b._id }]"
                @click="loadJobsForBatch(b._id)"
              >
                <td class="mono">{{ b._id.slice(-8) }}</td>
                <td class="dim">{{ b.general_domain || '—' }}</td>
                <td>
                  <span class="status-pill" :class="`status-${b.status}`">
                    <span v-if="b.status === 'running'" class="spin-dot" />
                    {{ b.status }}
                  </span>
                </td>
                <td>{{ fmtDate(b.created_at) }}</td>
                <td class="actions-cell">
                   <button class="btn xs" @click.stop="runBatch(b._id)" :disabled="b.status === 'running'">Run</button>
                   <button
                     v-if="b.status === 'running'"
                     class="btn xs danger"
                     :disabled="stoppingBatch.has(b._id)"
                     @click.stop="stopBatch(b._id)"
                   >{{ stoppingBatch.has(b._id) ? '…' : 'Stop' }}</button>
                   <button
                     class="btn xs danger"
                     :disabled="b.status === 'running' || deletingBatch.has(b._id)"
                     @click.stop="deleteBatch(b._id)"
                   >{{ deletingBatch.has(b._id) ? '…' : 'Delete' }}</button>
                 </td>
              </tr>
            </tbody>
          </table>

          <!-- Job details for selected batch -->
          <div v-if="selectedBatchJobs.length" class="jobs-section">
            <h3 class="subsection-title">Jobs — batch <span class="mono">{{ selectedBatchId?.slice(-8) }}</span></h3>
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

    <!-- TAB: Database -->
    <div v-show="activeTab === 'database'" class="tab-content database-tab">
      <div class="tab-inner">
        <div class="section-header">
          <h2>MongoDB Collections</h2>
          <button class="btn primary" @click="loadCollections">Refresh</button>
        </div>
        <div class="collections-grid">
          <div
            v-for="c in collections"
            :key="c.name"
            :class="['coll-card', { active: selectedCollection === c.name }]"
            @click="loadCollectionDocs(c.name)"
          >
            <span class="coll-name">{{ c.name }}</span>
            <span class="coll-count">{{ fmtNum(c.count) }}</span>
          </div>
        </div>

        <div v-if="collectionDocs.length">
          <h3 class="subsection-title">{{ selectedCollection }} <span class="dim">(first 20)</span></h3>
          <div class="doc-list">
            <pre v-for="(doc, i) in collectionDocs" :key="i" class="doc-pre">{{ JSON.stringify(doc, null, 2).slice(0, 500) }}</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB: KG Builder -->
    <div v-show="activeTab === 'kg'" class="tab-content kg-tab">
      <div class="tab-inner">
        <div class="section-header">
          <h2>KG Builder — Document–Taxon Linking</h2>
        </div>
        <div v-if="kgStats" class="kg-stats">
          <div class="stat-card">
            <span class="stat-label">Document–Taxon relations</span>
            <span class="stat-value">{{ kgStats.total ?? 0 }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Suggested</span>
            <span class="stat-value">{{ kgStats.suggested ?? 0 }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Confirmed</span>
            <span class="stat-value">{{ kgStats.confirmed ?? 0 }}</span>
          </div>
        </div>
        <div class="kg-actions">
          <button class="btn primary" @click="runKgLink(false)">Link Documents (keyword)</button>
          <button class="btn" @click="loadKgStats">Refresh stats</button>
        </div>
        <p class="dim small">
          Keyword linking scans document titles for taxon names and creates suggested document–taxon relations.
          Confirm or reject them in the relation list below, then rebuild the knowledge_graph schema.
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import CosmographCanvas from '@/components/kb/CosmographCanvas.vue'
import NodeInspector from '@/components/kb/NodeInspector.vue'
import SchemaPanel from '@/components/kb/SchemaPanel.vue'
import FolderTree from '@/components/kb/FolderTree.vue'
import type { FolderNode } from '@/components/kb/FolderTree.vue'
import {
  fetchSchemas, fetchStats, fetchTypeCounts,
  expandNode, rebuildSchema, resetKnowledgeBase,
  fetchNodeTypesPaged, fetchAllEdges,
  fetchCollections, fetchCollectionDocs as _fetchCollectionDocs,
  fetchBatches as _fetchBatches, fetchJobs,
  runBatch as _runBatch, deleteBatch as _deleteBatch, stopBatch as _stopBatch,
  fetchSources as _fetchSources, scanFolders, fetchFolderFiles,
  fetchKgStats as _fetchKgStats, linkDocuments,
  uploadPdf,
} from '@/utils/kbApi'
import type {
  GraphSchema, GraphNode, GraphEdge, GraphStats, TypeCounts,
  IngestionBatch, IngestionJob, CollectionInfo, KgStats, SourceEntry,
} from '@/utils/kbApi'

const authStore = useAuthStore()

// ---- Tabs -------------------------------------------------------------------

const TABS = [
  { id: 'graph', label: 'Graph' },
  { id: 'ingestion', label: 'Ingestion' },
  { id: 'database', label: 'Database' },
  { id: 'kg', label: 'KG Builder' },
]
const activeTab = ref<string>('graph')

// ---- Global state -----------------------------------------------------------

const loading  = ref(false)
const error    = ref('')
const resetting = ref(false)

function setError(e: unknown) {
  error.value = e instanceof Error ? e.message : String(e)
}

// ---- Graph tab state --------------------------------------------------------

const schemas         = ref<GraphSchema[]>([])
const selectedSchema  = ref<GraphSchema | null>(null)
const nodes           = ref<GraphNode[]>([])
const edges           = ref<GraphEdge[]>([])
const graphLoading    = ref(false)
const rebuilding      = ref(false)
const selectedNode    = ref<GraphNode | null>(null)
const hiddenTypes     = ref<Set<string>>(new Set())
const hiddenEdgeTypes = ref<Set<string>>(new Set())
const statsBySchema   = ref<Record<string, GraphStats>>({})
const selectedStats   = ref<GraphStats | null>(null)
const typeCounts      = ref<TypeCounts | null>(null)
const loadedNodeIds   = ref<string[]>([])
const canvasRef       = ref<InstanceType<typeof CosmographCanvas> | null>(null)

async function loadSchemas() {
  try {
    const list = await fetchSchemas()
    schemas.value = list
    // Load stats for each schema in background
    for (const s of list) {
      fetchStats(s._id).then(st => { statsBySchema.value = { ...statsBySchema.value, [s._id]: st } }).catch(() => {})
    }
  } catch (e) { setError(e) }
}

watch(selectedSchema, async (schema) => {
  if (!schema) return
  graphLoading.value = true
  nodes.value = []
  edges.value = []
  selectedNode.value = null
  loadedNodeIds.value = []
  typeCounts.value = null
  try {
    const [stats, types] = await Promise.all([
      fetchStats(schema._id),
      fetchTypeCounts(schema._id),
    ])
    selectedStats.value = stats
    typeCounts.value = types

    // Load all nodes page-by-page across every type
    const PAGE = 500
    const allNodes: GraphNode[] = []
    const loadedSet = new Set<string>()
    for (const [type, count] of Object.entries(types.node_types)) {
      const pages = Math.ceil((count as number) / PAGE)
      for (let p = 0; p < pages; p++) {
        const result = await fetchNodeTypesPaged(schema._id, type, p, PAGE)
        for (const n of result.nodes) {
          if (!loadedSet.has(n._id)) {
            allNodes.push(n)
            loadedSet.add(n._id)
          }
        }
      }
    }
    nodes.value = allNodes
    loadedNodeIds.value = [...loadedSet]

    // Fetch all edges in one shot
    edges.value = await fetchAllEdges(schema._id)
  } catch (e) { setError(e) }
  finally { graphLoading.value = false }
})

async function loadMoreNodes() {
  // All nodes and edges are loaded on initial schema selection.
  // This function is kept as a no-op to avoid breaking any callers.
}

async function handleRebuild() {
  if (!selectedSchema.value) return
  rebuilding.value = true
  try {
    await rebuildSchema(selectedSchema.value._id)
    // Re-load after a short delay to allow the rebuild to kick off
    setTimeout(() => {
      if (!selectedSchema.value) { rebuilding.value = false; return }
      fetchStats(selectedSchema.value._id)
        .then(stats => {
          selectedStats.value = stats
          if (selectedSchema.value)
            statsBySchema.value = { ...statsBySchema.value, [selectedSchema.value._id]: stats }
        })
        .catch(e => setError(e))
        .finally(() => { rebuilding.value = false })
    }, 2000)
  } catch (e) {
    setError(e)
    rebuilding.value = false
  }
}

function handleNodeClick(node: GraphNode) {
  selectedNode.value = node
}

async function handleExpand(node: GraphNode) {
  if (!selectedSchema.value) return
  graphLoading.value = true
  try {
    const data = await expandNode(selectedSchema.value._id, node._id, loadedNodeIds.value)
    const newNodes = data.nodes.filter(n => !loadedNodeIds.value.includes(n._id))
    // Deduplicate incoming edges against what's already in the graph
    const existingEdgeIds = new Set(edges.value.map(e => e._id))
    const newEdges = data.edges.filter(e => !existingEdgeIds.has(e._id))
    nodes.value = [...nodes.value, ...newNodes]
    edges.value = [...edges.value, ...newEdges]
    loadedNodeIds.value = [...loadedNodeIds.value, ...newNodes.map(n => n._id)]
  } catch (e) { setError(e) }
  finally { graphLoading.value = false }
}

function toggleType(type: string) {
  const next = new Set(hiddenTypes.value)
  if (next.has(type)) next.delete(type)
  else next.add(type)
  hiddenTypes.value = next
}

function toggleEdgeType(type: string) {
  const next = new Set(hiddenEdgeTypes.value)
  if (next.has(type)) next.delete(type)
  else next.add(type)
  hiddenEdgeTypes.value = next
}

async function confirmReset() {
  if (!confirm('This will delete all documents, chunks, facts, graph nodes, and ingestion jobs. taxonomy_nodes and stylized_facts are kept. Continue?')) return
  resetting.value = true
  try {
    const result = await resetKnowledgeBase()
    alert(`Reset complete. Deleted: ${JSON.stringify(result.deleted)}`)
    nodes.value = []
    edges.value = []
    selectedNode.value = null
    await loadSchemas()
  } catch (e) { setError(e) }
  finally { resetting.value = false }
}

// ---- Ingestion tab ----------------------------------------------------------

const batches         = ref<IngestionBatch[]>([])
const selectedBatchId = ref<string | null>(null)
const selectedBatchJobs = ref<IngestionJob[]>([])
const sources         = ref<SourceEntry[]>([])

// Source panel sub-tab
const sourceTab = ref<'upload' | 'remote'>('upload')

// Upload / drag-drop state
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
    error.value = 'Only PDF files are supported for upload. Please add PDF files.'
    return
  }
  if (pdfs.length < stagedFiles.value.length) {
    // Non-PDFs silently skipped — note in error bar
    const skipped = stagedFiles.value.length - pdfs.length
    error.value = `${skipped} non-PDF file(s) skipped — only PDFs are supported.`
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

// Folder/file selection state
const expandedFolders = ref<Set<string>>(new Set())
const folderFiles     = ref<Record<string, FolderNode | null>>({})
const selectedFolders = ref<Set<string>>(new Set())
const selectedFiles   = ref<Set<string>>(new Set())

async function loadBatches() {
  try { batches.value = await _fetchBatches(50) } catch (e) { setError(e) }
}

// Auto-poll while any batch is running
let _batchPollTimer: ReturnType<typeof setInterval> | null = null

function startBatchPolling() {
  if (_batchPollTimer) return
  _batchPollTimer = setInterval(async () => {
    await loadBatches()
    if (selectedBatchId.value) await loadJobsForBatch(selectedBatchId.value)
    const hasRunning = batches.value.some(b => b.status === 'running' || b.status === 'queued')
    if (!hasRunning) stopBatchPolling()
  }, 3000)
}

function stopBatchPolling() {
  if (_batchPollTimer) { clearInterval(_batchPollTimer); _batchPollTimer = null }
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
        const res = (await fetchFolderFiles(folderPath) as any)
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

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function scanAndRun() {
  const folders = Array.from(selectedFolders.value)
  const files   = Array.from(selectedFiles.value)
  if (!folders.length && !files.length) {
    alert('Select at least one folder or file first.')
    return
  }
  try {
    const batch = await scanFolders(folders, files)
    await _runBatch(batch.batch_id)
    await loadBatches()
  } catch (e) { setError(e) }
}

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
  if (!confirm('Delete this batch and all its jobs?')) return
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

// ---- Database tab -----------------------------------------------------------

const collections      = ref<CollectionInfo[]>([])
const selectedCollection = ref<string | null>(null)
const collectionDocs   = ref<unknown[]>([])

async function loadCollections() {
  try { collections.value = await fetchCollections() } catch (e) { setError(e) }
}

async function loadCollectionDocs(name: string) {
  selectedCollection.value = name
  try { collectionDocs.value = await _fetchCollectionDocs(name) } catch (e) { setError(e) }
}

// ---- KG Builder tab ---------------------------------------------------------

const kgStats = ref<KgStats | null>(null)

async function loadKgStats() {
  try { kgStats.value = await _fetchKgStats() } catch (e) { setError(e) }
}

async function runKgLink(overwrite: boolean) {
  try { await linkDocuments(1000, overwrite); await loadKgStats() } catch (e) { setError(e) }
}

// ---- Helpers ----------------------------------------------------------------

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k'
  return String(n)
}

function fmtDate(s?: string): string {
  if (!s) return '—'
  return new Date(s).toLocaleDateString()
}

// ---- Init -------------------------------------------------------------------

onMounted(async () => {
  await loadSchemas()
  if (activeTab.value === 'database') await loadCollections()
  if (activeTab.value === 'ingestion') await loadBatches()
})

watch(activeTab, async (tab) => {
  if (tab === 'database' && !collections.value.length) await loadCollections()
  if (tab === 'ingestion') await loadBatches()
  if (tab === 'kg' && !kgStats.value) await loadKgStats()
})

onUnmounted(() => stopBatchPolling())
</script>

<style scoped>
.kb-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #0f172a;
  color: #e2e8f0;
  font-family: system-ui, sans-serif;
  overflow: hidden;
}

/* ---- Header ---------------------------------------------------------------- */
.kb-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0 1rem;
  height: 44px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  flex-shrink: 0;
}

.back-link {
  color: #64748b;
  text-decoration: none;
  font-size: 1.1rem;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
}
.back-link:hover { background: #334155; color: #e2e8f0; }

.header-title {
  font-size: 0.85rem;
  font-weight: 700;
  color: #e2e8f0;
  letter-spacing: 0.02em;
}

.tab-nav {
  display: flex;
  gap: 0.1rem;
  margin-left: 1rem;
}

.tab-btn {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 0.3rem 0.75rem;
  color: #64748b;
  font-size: 0.78rem;
  cursor: pointer;
  white-space: nowrap;
  height: 44px;
}
.tab-btn:hover { color: #cbd5e1; }
.tab-btn.active { color: #60a5fa; border-bottom-color: #3b82f6; }

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.loading-chip { font-size: 0.7rem; color: #64748b; }
.error-chip {
  font-size: 0.7rem;
  background: #7f1d1d;
  color: #fca5a5;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-btn {
  padding: 0.3rem 0.65rem;
  border-radius: 5px;
  border: 1px solid #334155;
  background: #0f172a;
  color: #cbd5e1;
  font-size: 0.72rem;
  cursor: pointer;
}
.header-btn:hover { background: #334155; }
.header-btn.danger { border-color: #7f1d1d; color: #fca5a5; }
.header-btn.danger:hover { background: #7f1d1d; }
.header-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ---- Tab content ----------------------------------------------------------- */
.tab-content { flex: 1; overflow: hidden; }

/* ---- Graph tab ------------------------------------------------------------ */
.graph-tab {
  display: flex;
  height: 100%;
}

.graph-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.graph-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #475569;
  font-size: 0.9rem;
}

.graph-status-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.3rem 0.75rem;
  background: #1e293b;
  border-top: 1px solid #334155;
  font-size: 0.7rem;
  color: #64748b;
  flex-shrink: 0;
}

.schema-tag {
  font-weight: 600;
  color: #60a5fa;
}

.sm-btn {
  margin-left: auto;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  border: 1px solid #334155;
  background: none;
  color: #94a3b8;
  font-size: 0.68rem;
  cursor: pointer;
}
.sm-btn:hover { background: #334155; }
.sm-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ---- Non-ingestion tab inner wrapper -------------------------------------- */
.tab-inner {
  padding: 1.5rem;
  max-width: 1200px;
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

.section-sublabel { font-size: 0.72rem; color: #64748b; }

/* ---- Ingestion tab — two-panel layout ------------------------------------- */
.ingestion-tab {
  display: flex;
  flex-direction: row;
  height: 100%;
  overflow: hidden;
}

@media (max-width: 768px) {
  .ingestion-tab { flex-direction: column; }
  .ing-divider   { width: 100%; height: 1px; flex-shrink: 0; }
  .ing-left, .ing-right { width: 100% !important; flex: none; height: 50%; }
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
  border-color: #3b82f6;
  background: #1e3a5f22;
}
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
.batch-table { table-layout: fixed; }
.batch-table th:nth-child(1) { width: 90px; }
.batch-table th:nth-child(2) { width: auto; }
.batch-table th:nth-child(3) { width: 90px; }
.batch-table th:nth-child(4) { width: 90px; }
.batch-table th:nth-child(5) { width: 110px; }

.batch-row--selected td { background: #1e3a5f44; }

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

.file-list { list-style: none; margin: 0.2rem 0 0 1.6rem; padding: 0; display: flex; flex-direction: column; gap: 1px; }
.file-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.2rem 0.3rem;
  border-radius: 3px;
  background: #172033;
}
.file-name { font-size: 0.78rem; color: #cbd5e1; flex: 1; }
.file-size { font-size: 0.7rem; }
.file-loading { font-size: 0.76rem; padding: 0.2rem 0.3rem; }
.cb { accent-color: #6366f1; cursor: pointer; }

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
.btn.primary { background: #1d4ed8; border-color: #3b82f6; color: white; }
.btn.primary:hover { background: #2563eb; }
.btn.danger { border-color: #7f1d1d; color: #fca5a5; }
.btn.danger:hover { background: #7f1d1d; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn.sm { padding: 0.25rem 0.55rem; font-size: 0.7rem; }
.btn.xs { padding: 0.15rem 0.4rem; font-size: 0.65rem; }

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
.progress-bar { height: 6px; background: #1e293b; border-radius: 3px; width: 100%; flex: 1; }
.progress-fill { height: 100%; background: #3b82f6; border-radius: 3px; transition: width 0.3s; }
.progress-label { font-size: 0.65rem; color: #64748b; white-space: nowrap; flex-shrink: 0; }

.empty-state { padding: 2rem; text-align: center; color: #475569; font-size: 0.85rem; }

.subsection-title { font-size: 0.85rem; font-weight: 600; color: #94a3b8; margin: 0; }

/* ---- Database tab --------------------------------------------------------- */
.collections-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.5rem;
}

.coll-card {
  padding: 0.6rem 0.75rem;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.coll-card:hover { border-color: #3b82f6; }
.coll-card.active { border-color: #60a5fa; background: #1e3a5f; }
.coll-name { font-size: 0.75rem; color: #e2e8f0; font-weight: 500; }
.coll-count { font-size: 0.7rem; color: #64748b; }

.doc-list { display: flex; flex-direction: column; gap: 0.5rem; }
.doc-pre {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 0.75rem;
  font-size: 0.65rem;
  color: #94a3b8;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---- KG Builder tab ------------------------------------------------------- */
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

/* ---- Utilities ------------------------------------------------------------- */
.mono { font-family: monospace; }
.small { font-size: 0.7rem !important; }
.dim { color: #475569; }
</style>
