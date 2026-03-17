<template>
  <div ref="container" class="graph-container">
    <div v-if="loading" class="loading-overlay">
      <div class="spinner"></div>
      <div class="loading-text">{{ loadingMsg }}</div>
    </div>
    <div v-if="!loading && !schemaId" class="empty-state">
      Select a schema from the toolbar to visualize the graph
    </div>
  </div>
</template>

<script>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import Graph from 'graphology'
import Sigma from 'sigma'
import forceAtlas2 from 'graphology-layout-forceatlas2'
import circular from 'graphology-layout/circular'
import random from 'graphology-layout/random'
import { vizAPI } from '../services/api.js'

const NODE_COLORS = {
  stylized_fact: '#4a90e2',
  taxon: '#27ae60',
  fact: '#e67e22',
  document: '#e74c3c',
  species: '#8e44ad',
  concept: '#16a085',
  agent: '#f39c12',
  default: '#7f8c8d',
}

function nodeColor(nodeType) {
  return NODE_COLORS[nodeType] || NODE_COLORS.default
}

export default {
  name: 'GraphCanvas',
  props: {
    schemaId: { type: String, default: '' },
    layout: { type: String, default: 'force' },
  },
  emits: ['node-selected', 'stats-updated', 'schemas-loaded'],
  setup(props, { emit }) {
    const container = ref(null)
    const loading = ref(false)
    const loadingMsg = ref('Loading…')

    let sigmaInstance = null
    let graph = null
    let currentSearchQuery = ''

    onMounted(async () => {
      try {
        let res = await vizAPI.listSchemas()
        let schemas = res.data
        if (!schemas.length) {
          // Auto-seed built-in schema definitions on first load
          const seedRes = await vizAPI.seedSchemas()
          schemas = seedRes.data.schemas || []
        }
        emit('schemas-loaded', schemas)
      } catch (e) {
        console.error('Failed to load schemas:', e)
        emit('schemas-loaded', [])
      }
    })

    onBeforeUnmount(destroySigma)

    function destroySigma() {
      if (sigmaInstance) {
        try { sigmaInstance.kill() } catch (_) {}
        sigmaInstance = null
      }
    }

    async function loadGraph(schemaId) {
      if (!schemaId) return
      destroySigma()
      graph = null

      loading.value = true
      loadingMsg.value = 'Fetching graph data…'

      try {
        const res = await vizAPI.getSchemaGraph(schemaId, 100000)
        const { nodes, edges } = res.data

        loadingMsg.value = `Building graph (${nodes.length} nodes, ${edges.length} edges)…`
        await nextTick()

        graph = new Graph({ multi: true })

        for (const node of nodes) {
          graph.addNode(node._id, {
            label: node.label || node._id,
            nodeType: node.node_type,
            entityCollection: node.entity_collection,
            properties: node.properties || {},
            size: nodes.length > 20000 ? 2 : nodes.length > 5000 ? 3 : 4,
            color: nodeColor(node.node_type),
            x: Math.random() * 1000,
            y: Math.random() * 1000,
          })
        }

        for (const edge of edges) {
          if (graph.hasNode(edge.source_node_id) && graph.hasNode(edge.target_node_id)) {
            try {
              graph.addEdge(edge.source_node_id, edge.target_node_id, {
                edgeType: edge.edge_type,
                size: 1,
                color: '#cccccc',
              })
            } catch (_) {
              // skip duplicate edges in multi-graph (shouldn't happen but be safe)
            }
          }
        }

        if (graph.order > 0) {
          loadingMsg.value = 'Running layout…'
          await nextTick()
          applyLayoutToGraph(graph, props.layout)
        }

        loadingMsg.value = 'Rendering…'
        await nextTick()

        sigmaInstance = new Sigma(graph, container.value, {
          renderEdgeLabels: false,
          defaultEdgeColor: '#cccccc',
          labelRenderedSizeThreshold: 6,
          minCameraRatio: 0.01,
          maxCameraRatio: 10,
        })

        sigmaInstance.on('clickNode', ({ node }) => {
          const attrs = graph.getNodeAttributes(node)
          emit('node-selected', { id: node, ...attrs })
        })

        sigmaInstance.on('clickStage', () => {
          // clicking background deselects node (App handles this)
        })

        emit('stats-updated', { nodes: graph.order, edges: graph.size })
      } catch (e) {
        console.error('Failed to load graph:', e)
        loadingMsg.value = 'Error loading graph'
      } finally {
        loading.value = false
      }
    }

    function applyLayoutToGraph(g, layoutName) {
      if (!g || g.order === 0) return
      if (layoutName === 'force' || layoutName === 'forceatlas2') {
        if (g.order > 30000) {
          // Too large for synchronous force layout — use random positions
          random.assign(g)
        } else {
          const iterations = g.order > 10000 ? 30 : g.order > 3000 ? 60 : 100
          const settings = forceAtlas2.inferSettings(g)
          forceAtlas2.assign(g, { iterations, settings })
        }
      } else if (layoutName === 'circular') {
        circular.assign(g)
      } else {
        random.assign(g)
      }
    }

    function applySearch(query) {
      currentSearchQuery = query
      if (!sigmaInstance || !graph) return

      if (!query) {
        sigmaInstance.setSetting('nodeReducer', null)
        sigmaInstance.setSetting('edgeReducer', null)
      } else {
        const q = query.toLowerCase()
        const matching = new Set()
        graph.forEachNode((node, attrs) => {
          if ((attrs.label || '').toLowerCase().includes(q)) {
            matching.add(node)
          }
        })

        sigmaInstance.setSetting('nodeReducer', (node, data) => {
          if (matching.has(node)) return { ...data, highlighted: true, zIndex: 1 }
          return { ...data, color: '#e8e8e8', size: data.size * 0.6, label: null, zIndex: 0 }
        })

        sigmaInstance.setSetting('edgeReducer', (edge, data) => {
          return { ...data, color: '#eeeeee' }
        })
      }
      sigmaInstance.refresh()
    }

    function changeLayout(layoutName) {
      if (!graph || !sigmaInstance) return
      applyLayoutToGraph(graph, layoutName)
      sigmaInstance.refresh()
    }

    // Helper: yield to UI between heavy operations
    function nextTick() {
      return new Promise(resolve => setTimeout(resolve, 0))
    }

    watch(() => props.schemaId, (id) => {
      if (id) loadGraph(id)
    })

    watch(() => props.layout, (layout) => {
      changeLayout(layout)
    })

    return { container, loading, loadingMsg, applySearch }
  },
}
</script>

<style scoped>
.graph-container {
  width: 100%;
  height: 100%;
  position: relative;
  background: #f7f8fa;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(247, 248, 250, 0.85);
  z-index: 5;
  gap: 16px;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #ddd;
  border-top-color: #4a90e2;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-text {
  color: #555;
  font-size: 14px;
}

.empty-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #aaa;
  font-size: 16px;
}
</style>
