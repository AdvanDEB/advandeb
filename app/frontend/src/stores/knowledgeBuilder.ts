/**
 * State shared by the Knowledge Builder shell (views/KnowledgeBuilderView.vue)
 * and its tabs (components/kb/tabs/*).
 *
 * Only what more than one component needs lives here:
 *   - the active tab: the Suggestions queue card jumps to KG Builder, and the
 *     KG review hotkeys act only while that tab is shown;
 *   - the header's loading/error chip;
 *   - the graph: Reset DB in the header clears it and reloads the schema list,
 *     so the artifact loader, and the web worker it owns, live here too.
 * Everything else is local to the tab that uses it.
 *
 * The view calls reset() on unmount, so leaving /kb drops the (large) graph
 * bundle and the next visit starts fresh — as it did when this state was local
 * to the view.
 */
import { defineStore } from 'pinia'
import { nextTick, ref, shallowRef, watch } from 'vue'
import { fetchArtifactStatus, fetchGraphArtifact, fetchSchemas } from '@/utils/kbApi'
import type { GraphNode, GraphSchema, GraphStats, TypeCounts } from '@/utils/kbApi'
import type { GraphRenderBundle } from '@/types/graphArtifact'
import { formatCount } from '@/utils/format'
import GraphArtifactWorker from '@/workers/graphArtifactWorker?worker'

export type KbTab = 'graph' | 'ingestion' | 'database' | 'kg' | 'suggestions'

export type GraphLoadMode = 'schema' | 'refresh'

/** Progress of the current graph load, rendered by the Graph tab. */
export interface GraphLoadState {
  active: boolean
  mode: GraphLoadMode | null
  message: string
  detail: string
  completed: number
  total: number | null
  indeterminate: boolean
  overlay: boolean
}

const IDLE_GRAPH_LOAD: GraphLoadState = {
  active: false,
  mode: null,
  message: '',
  detail: '',
  completed: 0,
  total: null,
  indeterminate: false,
  overlay: false,
}

export const useKnowledgeBuilderStore = defineStore('knowledgeBuilder', () => {
  // ---- Shell ----------------------------------------------------------------

  const activeTab = ref<KbTab>('graph')
  const loading = ref(false)
  const error = ref('')

  function setError(e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  }

  // ---- Graph ----------------------------------------------------------------

  const schemas        = ref<GraphSchema[]>([])
  const selectedSchema = ref<GraphSchema | null>(null)
  const statsBySchema  = ref<Record<string, GraphStats>>({})
  const selectedStats  = ref<GraphStats | null>(null)
  const typeCounts     = ref<TypeCounts | null>(null)
  /**
   * Shallow on purpose: the bundle holds typed arrays and one summary per node
   * from the worker, and a deep ref would wrap every element in a proxy. It is
   * only ever replaced as a whole (the canvas watches it by identity), never
   * mutated in place.
   */
  const graphBundle    = shallowRef<GraphRenderBundle | null>(null)
  const selectedNode   = ref<GraphNode | null>(null)
  const graphLoading   = ref(false)
  const graphLoad      = ref<GraphLoadState>({ ...IDLE_GRAPH_LOAD })

  // Bumped by every load (and by reset); a load whose token is stale stops
  // and writes nothing.
  let graphLoadToken = 0

  function beginGraphLoad(options: {
    mode: GraphLoadMode
    message: string
    detail?: string
    total?: number | null
    indeterminate?: boolean
    overlay?: boolean
  }) {
    graphLoading.value = true
    graphLoad.value = {
      ...IDLE_GRAPH_LOAD,
      active: true,
      mode: options.mode,
      message: options.message,
      detail: options.detail ?? '',
      total: options.total ?? null,
      indeterminate: options.indeterminate ?? false,
      overlay: options.overlay ?? false,
    }
  }

  function updateGraphLoad(options: Partial<Omit<GraphLoadState, 'active' | 'mode'>> & { mode?: GraphLoadMode | null }) {
    if (!graphLoad.value.active) return
    graphLoad.value = {
      ...graphLoad.value,
      ...options,
    }
  }

  function endGraphLoad() {
    graphLoading.value = false
    graphLoad.value = { ...IDLE_GRAPH_LOAD }
  }

  // Active worker — terminated on schema switch so stale bundles are dropped
  let artifactWorker: Worker | null = null

  function terminateWorker() {
    if (artifactWorker) { artifactWorker.terminate(); artifactWorker = null }
  }

  async function loadGraph(
    schema: GraphSchema | null,
    options: { mode?: GraphLoadMode } = {},
  ): Promise<boolean> {
    if (!schema) return false
    const requestToken = ++graphLoadToken
    const schemaId = schema._id
    const mode = options.mode ?? 'schema'
    const overlay = mode === 'schema' || graphBundle.value === null

    if (mode === 'schema') {
      selectedNode.value = null
      terminateWorker()
    }

    beginGraphLoad({
      mode,
      message: mode === 'refresh' ? 'Refreshing graph…' : 'Loading graph…',
      detail: 'Fetching artifact',
      total: 3,
      overlay,
    })

    let success = false
    try {
      // Step 1 — check artifact status; if not ready, trigger rebuild
      updateGraphLoad({ completed: 1, message: 'Checking artifact…', detail: schema.name })
      let status = await fetchArtifactStatus(schemaId)
      if (requestToken !== graphLoadToken) return false

      if (status.status === 'missing' || status.status === 'building') {
        // Artifact not ready yet — show indeterminate progress and poll
        updateGraphLoad({
          completed: 1,
          message: status.status === 'building' ? 'Artifact is building…' : 'Artifact missing — queuing build…',
          detail: 'Please wait',
          indeterminate: true,
          overlay: true,
        })
        // Poll until ready or failed
        let pollStatus = status.status
        while (pollStatus === 'building' || pollStatus === 'missing') {
          await new Promise(r => setTimeout(r, 2000))
          if (requestToken !== graphLoadToken) return false
          status = await fetchArtifactStatus(schemaId)
          if (requestToken !== graphLoadToken) return false
          pollStatus = status.status as typeof pollStatus
        }
        if (pollStatus === 'failed') {
          setError(new Error(`Graph artifact for "${schema.name}" failed to build`))
          return false
        }
        updateGraphLoad({ indeterminate: false })
      }

      // Step 2 — download artifact
      updateGraphLoad({ completed: 2, message: 'Downloading graph data…', detail: schema.name, indeterminate: false })
      const artifact = await fetchGraphArtifact(schemaId, status.build_id)
      if (requestToken !== graphLoadToken) return false

      // Step 3 — parse in worker, build render bundle.
      // Indeterminate: the worker reports no intermediate progress, and a bar
      // parked at 100% while the tab is busy reads as a hang.
      updateGraphLoad({
        completed: 3,
        message: 'Building render buffers…',
        detail: `${formatCount(artifact.nodes.length)} nodes · ${formatCount(artifact.edges.length)} edges`,
        indeterminate: true,
      })

      const bundle = await new Promise<GraphRenderBundle>((resolve, reject) => {
        terminateWorker()
        const worker = new GraphArtifactWorker()
        artifactWorker = worker
        worker.onmessage = (ev) => {
          artifactWorker = null
          if (ev.data.type === 'ready') resolve(ev.data.bundle)
          else reject(new Error(ev.data.error ?? 'Worker error'))
          worker.terminate()
        }
        worker.onerror = (e) => {
          artifactWorker = null
          reject(new Error(e.message ?? 'Worker crashed'))
          worker.terminate()
        }
        worker.postMessage({ type: 'build-render-bundle', artifact })
      })

      if (requestToken !== graphLoadToken) return false

      // Atomically swap buffers
      selectedStats.value = {
        node_count: bundle.nodeCount,
        nodes: bundle.nodeCount,
        edge_count: bundle.edgeCount,
        edges: bundle.edgeCount,
        density: bundle.stats.density,
      }
      typeCounts.value = bundle.typeCounts
      statsBySchema.value = { ...statsBySchema.value, [schemaId]: selectedStats.value }
      graphBundle.value = bundle

      updateGraphLoad({
        detail: `${formatCount(bundle.nodeCount)} nodes · ${formatCount(bundle.edgeCount)} edges ready`,
      })

      await nextTick()
      success = true
    } catch (e) {
      if (requestToken === graphLoadToken) setError(e)
    } finally {
      if (requestToken === graphLoadToken) endGraphLoad()
    }

    return success
  }

  watch(selectedSchema, (schema, previousSchema) => {
    if (schema?._id !== previousSchema?._id) {
      selectedNode.value = null
    }
    loadGraph(schema, { mode: 'schema' })
  })

  async function refreshGraph() {
    await loadGraph(selectedSchema.value, { mode: 'refresh' })
  }

  async function loadSchemas() {
    try {
      const list = await fetchSchemas()
      schemas.value = list
      // Seed statsBySchema from artifact meta embedded in schema list
      for (const schema of list) {
        if (schema.artifact && (schema.artifact.status === 'ready' || schema.artifact.status === 'stale')) {
          statsBySchema.value = {
            ...statsBySchema.value,
            [schema._id]: {
              node_count: schema.artifact.node_count,
              nodes: schema.artifact.node_count,
              edge_count: schema.artifact.edge_count,
              edges: schema.artifact.edge_count,
              density: schema.artifact.density,
            },
          }
        }
      }
      if (!selectedSchema.value && list.length > 0) selectedSchema.value = list[0]
    } catch (e) { setError(e) }
  }

  // ---- Lifecycle ------------------------------------------------------------

  /** Back to the state of a first visit; any in-flight graph load is orphaned. */
  function reset() {
    graphLoadToken++
    terminateWorker()
    activeTab.value = 'graph'
    loading.value = false
    error.value = ''
    schemas.value = []
    selectedSchema.value = null
    statsBySchema.value = {}
    selectedStats.value = null
    typeCounts.value = null
    graphBundle.value = null
    selectedNode.value = null
    graphLoading.value = false
    graphLoad.value = { ...IDLE_GRAPH_LOAD }
  }

  return {
    activeTab, loading, error, setError,
    schemas, selectedSchema, statsBySchema, selectedStats, typeCounts,
    graphBundle, selectedNode, graphLoading, graphLoad,
    loadSchemas, loadGraph, refreshGraph, terminateWorker,
    reset,
  }
})
