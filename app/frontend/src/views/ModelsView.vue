<template>
  <div class="models-view">
    <!-- ── Header ── -->
    <header class="page-header">
      <div class="header-left">
        <h1>Models</h1>
        <span class="subtitle">tDEB — transport-network energy budgets</span>
      </div>

      <input
        v-if="network"
        v-model="modelName"
        class="model-name"
        spellcheck="false"
        aria-label="Model name"
        @blur="commitRename"
        @keydown.enter="($event.target as HTMLInputElement).blur()"
        @keydown.esc="resetName"
      />

      <div class="header-actions">
        <button class="btn-ghost" @click="openPicker">＋ New / Open</button>
        <button class="btn-ghost" :disabled="!network" @click="exportJson">↓ Export</button>
        <button class="btn-ghost" @click="importJson">↑ Import</button>
        <button class="btn-ghost" :disabled="!result?.success" @click="exportLatex">
          LaTeX
        </button>
      </div>
    </header>

    <p v-if="loadError" class="banner error">{{ loadError }}</p>

    <!-- ── Workspace ── -->
    <div class="workspace">
      <section class="panel panel-editor">
        <header class="panel-head">
          <h2>Transport network</h2>
          <div class="panel-actions">
            <button class="btn-sm btn-accent" :disabled="!network" @click="showAddNode = true">
              ＋ Compartment
            </button>
            <button
              class="btn-sm"
              :class="{ active: edgeMode }"
              :disabled="!network || nodeCount < 2"
              @click="edgeMode = !edgeMode"
            >
              ↗ Channel
            </button>
          </div>
        </header>

        <NetworkCanvas
          ref="canvasRef"
          :nodes="nodes"
          :edges="edges"
          :selected="selected"
          :edge-mode="edgeMode"
          @select-node="selectNode"
          @select-edge="selectEdge"
          @deselect="selected = null"
          @move-node="onNodeMove"
          @move-node-end="onNodeMoveEnd"
          @connect="onConnect"
        />
      </section>

      <section class="panel panel-side">
        <nav class="tab-bar">
          <button
            v-for="tab in TABS"
            :key="tab.id"
            class="tab"
            :class="{ active: activeTab === tab.id }"
            @click="activeTab = tab.id"
          >{{ tab.label }}</button>
        </nav>

        <div class="tab-body">
          <ElementInspector
            v-show="activeTab === 'params'"
            :node="selectedNode"
            :edge="selectedEdge"
            :nodes="nodes"
            :equations="equations"
            :formula-error="formulaError"
            @update-node="onUpdateNode"
            @update-edge="onUpdateEdge"
            @delete="deleteSelected"
          />

          <SimulationPanel
            v-show="activeTab === 'simulation'"
            ref="simPanelRef"
            :nodes="nodes"
            :running="running"
            :streaming="streaming"
            :progress="progress"
            :progress-label="progressLabel"
            :error-message="simError"
            :result="result"
            @run="runBatch"
            @stream="runStream"
            @stop="stopStream"
          />

          <ResultsPanel
            v-show="activeTab === 'results'"
            ref="resultsRef"
            :result="result"
            :nodes="nodes"
            :edges="edges"
          />

          <EquationsPanel
            v-show="activeTab === 'equations'"
            ref="equationsRef"
            :equations="equations"
            :nodes="nodes"
            :edges="edges"
            @saved="onEquationsSaved"
          />
        </div>
      </section>
    </div>

    <TemplatePicker
      v-if="showPicker"
      :templates="templates"
      :saved-models="savedModels"
      :loading="pickerLoading"
      :error="pickerError"
      @close="showPicker = false"
      @create="createFromTemplate"
      @open="openModel"
      @delete="removeModel"
    />

    <AddNodeDialog
      v-if="showAddNode"
      @close="showAddNode = false"
      @add="onAddNode"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AddNodeDialog from '@/components/tdeb/AddNodeDialog.vue'
import ElementInspector from '@/components/tdeb/ElementInspector.vue'
import EquationsPanel from '@/components/tdeb/EquationsPanel.vue'
import NetworkCanvas from '@/components/tdeb/NetworkCanvas.vue'
import ResultsPanel from '@/components/tdeb/ResultsPanel.vue'
import SimulationPanel from '@/components/tdeb/SimulationPanel.vue'
import TemplatePicker from '@/components/tdeb/TemplatePicker.vue'
import { useNotificationsStore } from '@/stores/notifications'
import * as tdeb from '@/utils/tdebApi'
import type {
  EquationDocument, NodeTypeId, SimulationRequest, SimulationResult,
  StreamSnapshot, TDebEdge, TDebEdgeParams, TDebModelSummary, TDebNetwork,
  TDebNode, TDebTemplate, TransportTypeId,
} from '@/utils/tdebApi'
import { nodeColor } from '@/utils/tdebConstants'
import { buildLatexBundle } from '@/utils/tdebLatex'

const TABS = [
  { id: 'params', label: 'Parameters' },
  { id: 'simulation', label: 'Simulation' },
  { id: 'results', label: 'Results' },
  { id: 'equations', label: 'Equations' },
] as const
type TabId = typeof TABS[number]['id']

const notifications = useNotificationsStore()

const canvasRef = ref<InstanceType<typeof NetworkCanvas> | null>(null)
const simPanelRef = ref<InstanceType<typeof SimulationPanel> | null>(null)
const resultsRef = ref<InstanceType<typeof ResultsPanel> | null>(null)
const equationsRef = ref<InstanceType<typeof EquationsPanel> | null>(null)

const modelId = ref<string | null>(null)
const network = ref<TDebNetwork | null>(null)
const equations = ref<EquationDocument | null>(null)
const templates = ref<TDebTemplate[]>([])
const savedModels = ref<TDebModelSummary[]>([])

const modelName = ref('')
const activeTab = ref<TabId>('params')
const selected = ref<{ type: 'node' | 'edge'; id: string } | null>(null)
const edgeMode = ref(false)
const showPicker = ref(false)
const showAddNode = ref(false)
const pickerLoading = ref(false)
const pickerError = ref('')
const loadError = ref('')
const formulaError = ref('')

const running = ref(false)
const streaming = ref(false)
const progress = ref<number | null>(null)
const progressLabel = ref('')
const simError = ref('')
const result = ref<SimulationResult | null>(null)

let socket: WebSocket | null = null
let movePersistTimer: number | null = null

const nodes = computed(() => network.value?.nodes ?? {})
const edges = computed(() => network.value?.edges ?? {})
const nodeCount = computed(() => Object.keys(nodes.value).length)

const selectedNode = computed(() =>
  selected.value?.type === 'node' ? nodes.value[selected.value.id] ?? null : null)
const selectedEdge = computed(() =>
  selected.value?.type === 'edge' ? edges.value[selected.value.id] ?? null : null)

function errorMessage(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const detail = (err as { response?: { data?: { detail?: unknown } } })
      .response?.data?.detail
    if (typeof detail === 'string') return detail
  }
  return err instanceof Error ? err.message : fallback
}

// ─── Loading ─────────────────────────────────────────────────────────

async function refreshPickerData() {
  pickerLoading.value = true
  pickerError.value = ''
  try {
    const [t, m] = await Promise.all([tdeb.listTemplates(), tdeb.listModels()])
    templates.value = t
    savedModels.value = m
  } catch (err) {
    pickerError.value = errorMessage(err, 'Could not load templates.')
  } finally {
    pickerLoading.value = false
  }
}

function openPicker() {
  showPicker.value = true
  refreshPickerData()
}

function adoptNetwork(net: TDebNetwork, id: string) {
  modelId.value = id
  network.value = net
  modelName.value = net.name
  selected.value = null
  edgeMode.value = false
  result.value = null
  simError.value = ''
  progress.value = null
  // Wait for the canvas to render the new nodes before framing them.
  requestAnimationFrame(() => canvasRef.value?.fitToView())
}

async function createFromTemplate(templateId: string | null) {
  showPicker.value = false
  loadError.value = ''
  try {
    const net = templateId
      ? await tdeb.createModel({ template: templateId })
      : await tdeb.createModel({ name: 'New model' })
    adoptNetwork(net, net.id)
  } catch (err) {
    loadError.value = errorMessage(err, 'Could not create the model.')
  }
}

async function openModel(id: string) {
  showPicker.value = false
  loadError.value = ''
  try {
    adoptNetwork(await tdeb.getModel(id), id)
  } catch (err) {
    loadError.value = errorMessage(err, 'Could not open the model.')
  }
}

async function removeModel(id: string) {
  if (!window.confirm('Delete this model permanently?')) return
  try {
    await tdeb.deleteModel(id)
    savedModels.value = savedModels.value.filter(m => m.id !== id)
    if (modelId.value === id) {
      modelId.value = null
      network.value = null
      modelName.value = ''
    }
  } catch (err) {
    notifications.error(errorMessage(err, 'Could not delete the model.'))
  }
}

async function commitRename() {
  const next = modelName.value.trim()
  if (!modelId.value || !network.value) return
  if (!next || next === network.value.name) {
    modelName.value = network.value.name
    return
  }
  try {
    const updated = await tdeb.renameModel(modelId.value, next)
    network.value.name = updated.name
    modelName.value = updated.name
  } catch (err) {
    modelName.value = network.value.name
    notifications.error(errorMessage(err, 'Could not rename the model.'))
  }
}

function resetName() {
  if (network.value) modelName.value = network.value.name
}

// ─── Selection & editing ─────────────────────────────────────────────

function selectNode(id: string) {
  selected.value = { type: 'node', id }
  formulaError.value = ''
  activeTab.value = 'params'
}

function selectEdge(id: string) {
  selected.value = { type: 'edge', id }
  formulaError.value = ''
  activeTab.value = 'params'
}

/** Local-only during the drag, so the canvas stays at pointer speed. */
function onNodeMove({ id, x, y }: { id: string; x: number; y: number }) {
  const node = network.value?.nodes[id]
  if (!node) return
  node.x = x
  node.y = y
}

/**
 * Persist a node's position once the drag ends, debounced so a flurry of quick
 * repositions collapses into a single write.
 */
function onNodeMoveEnd({ id, x, y }: { id: string; x: number; y: number }) {
  if (!modelId.value) return
  if (movePersistTimer !== null) window.clearTimeout(movePersistTimer)
  movePersistTimer = window.setTimeout(() => {
    movePersistTimer = null
    tdeb.updateNode(modelId.value!, id, { x, y }).catch(() => {
      // A dropped position update is cosmetic; the next edit will carry it.
    })
  }, 250)
}

async function onAddNode(payload: {
  name: string; node_type: NodeTypeId; initial_value: number
}) {
  showAddNode.value = false
  if (!modelId.value) return
  try {
    // Drop new compartments into open space near the middle of the canvas.
    const node = await tdeb.addNode(modelId.value, {
      ...payload,
      x: 200 + Math.random() * 380,
      y: 120 + Math.random() * 280,
      color: nodeColor(payload.node_type),
    })
    if (network.value) network.value.nodes[node.id] = node
    selectNode(node.id)
  } catch (err) {
    notifications.error(errorMessage(err, 'Could not add the compartment.'))
  }
}

async function onConnect({ sourceId, targetId }: { sourceId: string; targetId: string }) {
  edgeMode.value = false
  if (!modelId.value) return
  try {
    const edge = await tdeb.addEdge(modelId.value, {
      source_id: sourceId,
      target_id: targetId,
      name: 'transport',
      transport_type: 'linear',
    })
    if (network.value) network.value.edges[edge.id] = edge
    selectEdge(edge.id)
  } catch (err) {
    notifications.error(errorMessage(err, 'Could not create the channel.'))
  }
}

async function onUpdateNode(payload: {
  name: string; node_type: NodeTypeId; initial_value: number; value: number
  color: string; params: Partial<TDebNode['params']>
}) {
  if (!modelId.value || !selectedNode.value) return
  try {
    const updated = await tdeb.updateNode(modelId.value, selectedNode.value.id, payload)
    if (network.value) network.value.nodes[updated.id] = updated
  } catch (err) {
    notifications.error(errorMessage(err, 'Could not update the compartment.'))
  }
}

async function onUpdateEdge(payload: {
  name: string; transport_type: TransportTypeId; params: Partial<TDebEdgeParams>
}) {
  if (!modelId.value || !selectedEdge.value) return
  try {
    const updated: TDebEdge = await tdeb.updateEdge(
      modelId.value, selectedEdge.value.id, payload,
    )
    if (network.value) network.value.edges[updated.id] = updated
    formulaError.value = updated.formula_error ?? ''
  } catch (err) {
    notifications.error(errorMessage(err, 'Could not update the channel.'))
  }
}

async function deleteSelected() {
  if (!modelId.value || !selected.value || !network.value) return
  const { type, id } = selected.value
  try {
    if (type === 'node') {
      await tdeb.deleteNode(modelId.value, id)
      // The server removes attached channels too; mirror that locally.
      for (const [eid, edge] of Object.entries(network.value.edges)) {
        if (edge.source_id === id || edge.target_id === id) {
          delete network.value.edges[eid]
        }
      }
      delete network.value.nodes[id]
    } else {
      await tdeb.deleteEdge(modelId.value, id)
      delete network.value.edges[id]
    }
    selected.value = null
  } catch (err) {
    notifications.error(errorMessage(err, 'Could not delete the element.'))
  }
}

// ─── Simulation ──────────────────────────────────────────────────────

async function runBatch(request: SimulationRequest) {
  if (!modelId.value) return
  running.value = true
  simError.value = ''
  progress.value = null
  try {
    const res = await tdeb.simulate(modelId.value, request)
    if (!res.success) {
      simError.value = res.message || 'The solver did not converge.'
      return
    }
    result.value = res
    activeTab.value = 'results'
  } catch (err) {
    simError.value = errorMessage(err, 'Simulation failed.')
  } finally {
    running.value = false
  }
}

async function runStream(request: SimulationRequest) {
  if (!modelId.value) return

  stopStream()
  simError.value = ''
  progress.value = 0
  progressLabel.value = ''
  streaming.value = true

  await simPanelRef.value?.initLiveChart()

  // Accumulate the stream so the Results tab gets the same shape as a batch run.
  const collected: SimulationResult = {
    time: [], states: {}, fluxes: {},
    success: true, message: 'Streamed simulation', n_points: 0,
  }

  socket = tdeb.openSimulationSocket(modelId.value)

  socket.onopen = () => {
    socket?.send(JSON.stringify({
      temperature: request.temperature,
      food_density: request.food_density,
      t_end: request.t_end,
      dt_output: request.dt_output,
      method: request.method,
    }))
  }

  socket.onmessage = (event) => {
    let data: StreamSnapshot
    try {
      data = JSON.parse(event.data as string)
    } catch {
      return
    }

    if (data.error) {
      simError.value = data.error
      stopStream()
      return
    }

    if (data.done) {
      progress.value = 1
      progressLabel.value = 'Done'
      collected.n_points = collected.time.length
      if (collected.time.length) {
        result.value = collected
        activeTab.value = 'results'
      }
      stopStream()
      return
    }

    const time = data.time ?? 0
    progress.value = data.progress ?? 0
    progressLabel.value = `t = ${time.toFixed(1)} d (${Math.round((data.progress ?? 0) * 100)}%)`

    collected.time.push(time)

    const liveValues: Record<string, number> = {}
    for (const [nid, info] of Object.entries(data.nodes ?? {})) {
      ;(collected.states[info.name] ??= []).push(info.value)
      liveValues[info.name] = info.value
      // Mirror the value onto the canvas so the network animates as it solves.
      const node = network.value?.nodes[nid]
      if (node) node.value = info.value
    }
    for (const info of Object.values(data.flows ?? {})) {
      ;(collected.fluxes[info.name] ??= []).push(info.flux)
    }

    simPanelRef.value?.pushSnapshot(time, liveValues)
  }

  socket.onerror = () => {
    simError.value = 'The streaming connection failed.'
    stopStream()
  }

  socket.onclose = () => {
    streaming.value = false
    socket = null
  }
}

function stopStream() {
  if (socket) {
    socket.onmessage = null
    socket.onerror = null
    socket.onclose = null
    socket.close()
    socket = null
  }
  streaming.value = false
}

// ─── Equations ───────────────────────────────────────────────────────

async function loadEquations() {
  try {
    equations.value = await tdeb.getEquations()
  } catch (err) {
    loadError.value = errorMessage(err, 'Could not load the equation set.')
  }
}

function onEquationsSaved(doc: EquationDocument) {
  equations.value = doc
}

// ─── Import / export ─────────────────────────────────────────────────

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function safeFilename(name: string): string {
  return (name || 'tdeb_model').replace(/[^\w\-. ]+/g, '').replace(/\s+/g, '_') || 'tdeb_model'
}

async function exportJson() {
  if (!modelId.value) return
  try {
    const doc = await tdeb.exportModel(modelId.value)
    downloadBlob(
      new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }),
      `${safeFilename(doc.name)}.json`,
    )
  } catch (err) {
    notifications.error(errorMessage(err, 'Export failed.'))
  }
}

function importJson() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json,application/json'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return
    try {
      const doc = JSON.parse(await file.text())
      const net = await tdeb.createModel({ network: doc })
      adoptNetwork(net, net.id)
    } catch (err) {
      notifications.error(errorMessage(err, 'Could not import that file.'))
    }
  }
  input.click()
}

/** Bundle equations, the network diagram and result charts as a LaTeX zip. */
async function exportLatex() {
  if (!result.value?.success || !network.value) return
  try {
    const blob = await buildLatexBundle({
      modelName: modelName.value || 'tDEB model',
      sections: equationsRef.value?.renderedSections ?? [],
      legend: equationsRef.value?.legend ?? [],
      networkSvg: canvasRef.value?.svgElement() ?? null,
      charts: await resultsRef.value?.chartImages() ?? {
        states: null, fluxes: null, sankey: null,
      },
    })
    downloadBlob(blob, `${safeFilename(modelName.value)}_latex.zip`)
  } catch (err) {
    notifications.error(errorMessage(err, 'LaTeX export failed.'))
  }
}

// ─── Lifecycle ───────────────────────────────────────────────────────

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  if (edgeMode.value) edgeMode.value = false
  else if (showAddNode.value) showAddNode.value = false
  else if (showPicker.value) showPicker.value = false
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  await loadEquations()
  await refreshPickerData()
  // Reopen the most recent model rather than dropping the user on a blank
  // canvas; with nothing saved, offer the picker instead.
  const latest = savedModels.value[0]
  if (latest) await openModel(latest.id)
  else showPicker.value = true
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  stopStream()
  if (movePersistTimer !== null) window.clearTimeout(movePersistTimer)
})

// Re-render the equations tab whenever the model changes shape.
watch(() => activeTab.value, (tab) => {
  if (tab === 'results') requestAnimationFrame(() => window.dispatchEvent(new Event('resize')))
})
</script>

<style scoped>
.models-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 1rem 1.25rem 1.25rem;
  gap: 0.85rem;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}
.header-left { display: flex; align-items: baseline; gap: 0.6rem; }
.page-header h1 { font-size: 1.35rem; font-weight: 700; color: #111827; margin: 0; }
.subtitle { font-size: 0.78rem; color: #6b7280; }

.model-name {
  flex: 1;
  min-width: 180px;
  max-width: 420px;
  border: 1px solid transparent;
  border-radius: 5px;
  padding: 0.3rem 0.55rem;
  font-size: 0.88rem;
  font-weight: 600;
  color: #374151;
  background: transparent;
}
.model-name:hover { border-color: #e5e7eb; }
.model-name:focus { border-color: #93c5fd; background: #fff; outline: none; }

.header-actions { display: flex; gap: 0.35rem; margin-left: auto; flex-wrap: wrap; }
.btn-ghost {
  border: 1px solid #d1d5db;
  background: #fff;
  color: #4b5563;
  border-radius: 5px;
  padding: 0.32rem 0.7rem;
  font-size: 0.76rem;
  cursor: pointer;
}
.btn-ghost:hover:not(:disabled) { background: #f3f4f6; }
.btn-ghost:disabled { opacity: 0.5; cursor: default; }

.banner {
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  font-size: 0.8rem;
  margin: 0;
}
.banner.error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }

.workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 0.85rem;
}
@media (max-width: 1100px) {
  .workspace { grid-template-columns: 1fr; grid-template-rows: minmax(320px, 1fr) auto; }
}

.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}
.panel-editor { padding: 0.65rem; gap: 0.55rem; }

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.panel-head h2 {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
  margin: 0;
}
.panel-actions { display: flex; gap: 0.35rem; }
.btn-sm {
  border: 1px solid #d1d5db;
  background: #fff;
  color: #4b5563;
  border-radius: 5px;
  padding: 0.25rem 0.6rem;
  font-size: 0.73rem;
  cursor: pointer;
}
.btn-sm:hover:not(:disabled) { background: #f3f4f6; }
.btn-sm:disabled { opacity: 0.5; cursor: default; }
.btn-sm.btn-accent { background: #3b82f6; border-color: #3b82f6; color: #fff; }
.btn-sm.btn-accent:hover:not(:disabled) { background: #2563eb; }
.btn-sm.active { background: #3b82f6; border-color: #3b82f6; color: #fff; }

.panel-side { min-width: 0; }
.tab-bar {
  display: flex;
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
  flex-shrink: 0;
}
.tab {
  flex: 1;
  border: none;
  background: none;
  padding: 0.55rem 0.4rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: #6b7280;
  cursor: pointer;
  border-bottom: 2px solid transparent;
}
.tab:hover { color: #374151; }
.tab.active { color: #2563eb; border-bottom-color: #3b82f6; background: #fff; }

.tab-body { flex: 1; min-height: 0; overflow-y: auto; padding: 0.9rem; }
</style>
