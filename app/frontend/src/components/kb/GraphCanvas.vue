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
import { vizAPI } from '@/utils/kbApi'

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
  emits: ['node-selected', 'node-deselected', 'stats-updated', 'schemas-loaded'],
  setup(props, { emit }) {
    const container = ref(null)
    const loading = ref(false)
    const loadingMsg = ref('Loading…')

    let sigmaInstance = null
    let graph = null
    let currentSearchQuery = ''
    let currentDegreeGravity = 0
    let focusedNode = null   // node ID currently in focus mode, or null

    onMounted(async () => {
      try {
        let res = await vizAPI.listSchemas()
        let schemas = res.data
        if (!schemas.length) {
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
      focusedNode = null
      currentDegreeGravity = 0
      currentSearchQuery = ''

      loading.value = true
      loadingMsg.value = 'Fetching graph data…'

      try {
        const res = await vizAPI.getSchemaGraph(schemaId)
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
            } catch (_) {}
          }
        }

        if (graph.order > 0) {
          loadingMsg.value = 'Running layout…'
          await nextTick()
          applyLayoutToGraph(graph, props.layout, 0)
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
          activateFocusMode(node)
        })

        sigmaInstance.on('clickStage', () => {
          if (focusedNode !== null) {
            clearFocusMode()
            emit('node-deselected')
          }
        })

        emit('stats-updated', { nodes: graph.order, edges: graph.size })
      } catch (e) {
        console.error('Failed to load graph:', e)
        loadingMsg.value = 'Error loading graph'
      } finally {
        loading.value = false
      }
    }

    // ─── Focus mode ───────────────────────────────────────────────────────────

    function activateFocusMode(nodeId) {
      focusedNode = nodeId
      applyReducers()

      // Animate camera to the focal node
      const display = sigmaInstance.getNodeDisplayData(nodeId)
      if (display) {
        sigmaInstance.getCamera().animate(
          { x: display.x, y: display.y, ratio: 0.15 },
          { duration: 500 }
        )
      }
    }

    function clearFocusMode() {
      focusedNode = null
      applyReducers()
      // Zoom back out to full graph
      sigmaInstance.getCamera().animate(
        { ratio: 1 },
        { duration: 400 }
      )
    }

    // ─── Unified reducer ──────────────────────────────────────────────────────
    // Priority: focus mode > search. Both can coexist: if focus is active,
    // search only highlights among the focused neighborhood.

    function applyReducers() {
      if (!sigmaInstance || !graph) return

      if (focusedNode !== null) {
        const neighbors = new Set(graph.neighbors(focusedNode))
        const q = currentSearchQuery ? currentSearchQuery.toLowerCase() : null

        // Within the neighborhood, further filter by search query if active
        const highlightedNeighbors = q
          ? new Set([...neighbors].filter(n => {
              const label = graph.getNodeAttribute(n, 'label') || ''
              return label.toLowerCase().includes(q)
            }))
          : neighbors

        sigmaInstance.setSetting('nodeReducer', (node, data) => {
          if (node === focusedNode) {
            return { ...data, size: data.size * 2.5, zIndex: 3, highlighted: true, color: data.color }
          }
          if (highlightedNeighbors.has(node)) {
            return { ...data, zIndex: 2, highlighted: true }
          }
          if (neighbors.has(node) && q) {
            // neighbor but doesn't match search → faded but slightly visible
            return { ...data, color: '#b0b0b0', size: data.size * 0.6, label: null, zIndex: 1 }
          }
          return { ...data, color: '#d8d8d8', size: data.size * 0.3, label: null, zIndex: 0 }
        })

        sigmaInstance.setSetting('edgeReducer', (edge, data) => {
          const src = graph.source(edge)
          const tgt = graph.target(edge)
          if (src === focusedNode || tgt === focusedNode) {
            // Color the edge by the neighbor's node color
            const neighborId = src === focusedNode ? tgt : src
            const neighborColor = graph.getNodeAttribute(neighborId, 'color') || '#4a90e2'
            return { ...data, color: neighborColor, size: 1.5, zIndex: 1 }
          }
          return { ...data, color: '#eeeeee', size: 0.3, zIndex: 0 }
        })

      } else if (currentSearchQuery) {
        const q = currentSearchQuery.toLowerCase()
        const matching = new Set()
        graph.forEachNode((node, attrs) => {
          if ((attrs.label || '').toLowerCase().includes(q)) matching.add(node)
        })

        sigmaInstance.setSetting('nodeReducer', (node, data) => {
          if (matching.has(node)) return { ...data, highlighted: true, zIndex: 1 }
          return { ...data, color: '#e0e0e0', size: data.size * 0.4, label: null, zIndex: 0 }
        })
        sigmaInstance.setSetting('edgeReducer', (edge, data) => {
          const src = graph.source(edge)
          const tgt = graph.target(edge)
          if (matching.has(src) && matching.has(tgt)) return { ...data, color: '#aaaaaa' }
          return { ...data, color: '#f0f0f0' }
        })

      } else {
        sigmaInstance.setSetting('nodeReducer', null)
        sigmaInstance.setSetting('edgeReducer', null)
      }

      sigmaInstance.refresh()
    }

    // ─── Search ───────────────────────────────────────────────────────────────

    function applySearch(query) {
      currentSearchQuery = query
      applyReducers()
    }

    // ─── Layout ───────────────────────────────────────────────────────────────

    function applyLayoutToGraph(g, layoutName, degreeGravity) {
      if (!g || g.order === 0) return

      if (layoutName === 'force' || layoutName === 'forceatlas2') {
        if (g.order > 30000) { random.assign(g); return }

        const settings = forceAtlas2.inferSettings(g)

        if (degreeGravity > 0) {
          let maxDegree = 1
          g.forEachNode((node) => {
            const d = g.degree(node)
            if (d > maxDegree) maxDegree = d
          })
          const amplifier = degreeGravity * 50
          g.forEachNode((node) => {
            const d = g.degree(node)
            g.setNodeAttribute(node, '_dw', 1 + (d / maxDegree) * amplifier)
          })
          settings.nodeWeightAttribute = '_dw'
          settings.strongGravityMode = true
          settings.gravity = 1 + degreeGravity * 4
        }

        const iterations = g.order > 10000 ? 30 : g.order > 3000 ? 60 : 100
        forceAtlas2.assign(g, { iterations, settings })

      } else if (layoutName === 'circular') {
        circular.assign(g)
      } else {
        random.assign(g)
      }
    }

    function relayout(degreeGravity) {
      if (!graph || !sigmaInstance) return
      currentDegreeGravity = degreeGravity
      applyLayoutToGraph(graph, props.layout, degreeGravity)
      // Re-apply any active reducers after layout change
      applyReducers()
      sigmaInstance.refresh()
    }

    function changeLayout(layoutName) {
      if (!graph || !sigmaInstance) return
      applyLayoutToGraph(graph, layoutName, currentDegreeGravity)
      applyReducers()
      sigmaInstance.refresh()
    }

    function nextTick() {
      return new Promise(resolve => setTimeout(resolve, 0))
    }

    watch(() => props.schemaId, (id) => { if (id) loadGraph(id) })
    watch(() => props.layout, (layout) => { changeLayout(layout) })

    return { container, loading, loadingMsg, applySearch, relayout }
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
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { color: #555; font-size: 14px; }
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
