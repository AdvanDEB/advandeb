<template>
  <div class="graph-container">
    <div ref="graphWrapper" class="graph-wrapper"></div>
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
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { vizAPI } from '@/utils/kbApi'
import { VirtualGraph } from '@/utils/virtualGraph'

// ── Node colors ────────────────────────────────────────────────────────────────
const NODE_COLORS = {
  document:      '#e74c3c',
  fact:          '#e67e22',
  stylized_fact: '#4a90e2',
  chunk:         '#94a3b8',
  concept:       '#16a085',
  agent:         '#f39c12',
  taxon:         '#27ae60',
  species:       '#8e44ad',
  genus:         '#9b59b6',
  family:        '#1abc9c',
  order:         '#2ecc71',
  class:         '#27ae60',
  phylum:        '#16a085',
  kingdom:       '#0e6655',
  superkingdom:  '#0a3d2e',
  default:       '#7f8c8d',
}

// ── Edge colors ────────────────────────────────────────────────────────────────
const EDGE_COLORS = {
  extracted_from: '#95a5a6',
  supports:       '#27ae60',
  opposes:        '#e74c3c',
  is_child_of:    '#d1d5db',
  studies:        '#9b59b6',
  cites:          '#3498db',
  regulates:      '#f39c12',
  depends_on:     '#e67e22',
  exhibited_by:   '#f59e0b',
  has_chunk:      '#b0bec5',
  default:        '#cccccc',
}

export const ALL_NODE_TYPES = Object.keys(NODE_COLORS).filter(k => k !== 'default')
export const ALL_EDGE_TYPES = Object.keys(EDGE_COLORS).filter(k => k !== 'default')
export { NODE_COLORS, EDGE_COLORS }

// Pre-parse edge color hex strings once so weightedColor() never calls parseInt at runtime
const EDGE_COLORS_RGB = Object.fromEntries(
  Object.entries(EDGE_COLORS).map(([k, hex]) => [k, [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ]])
)

// ── Cluster color palette (12 visually distinct colors) ────────────────────────
const CLUSTER_PALETTE = [
  '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
  '#1abc9c', '#e67e22', '#34495e', '#e91e63', '#00bcd4',
  '#8bc34a', '#ff5722',
]

export function clusterColor(clusterId) {
  if (clusterId === null || clusterId === undefined) return NODE_COLORS.default
  const key = String(clusterId)
  let hash = 0
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0
  return CLUSTER_PALETTE[hash % CLUSTER_PALETTE.length]
}

export function getClustersFromNodes(nodes) {
  const clusters = new Map()
  for (const n of nodes) {
    const cid = n.cluster_id ?? n.properties?.cluster_id ?? null
    if (cid !== null && cid !== undefined) {
      if (!clusters.has(cid)) clusters.set(cid, { id: cid, color: clusterColor(cid) })
    }
  }
  return [...clusters.values()]
}

// ── Shared sprite texture for 3D renderer ─────────────────────────────────────
// Created once, reused for all nodes → one GPU texture upload total
let _spriteTexture = null
function getSpriteTexture(THREE) {
  if (_spriteTexture) return _spriteTexture
  const canvas = document.createElement('canvas')
  canvas.width = 64; canvas.height = 64
  const ctx = canvas.getContext('2d')
  const grad = ctx.createRadialGradient(32, 32, 0, 32, 32, 30)
  grad.addColorStop(0, 'rgba(255,255,255,1)')
  grad.addColorStop(0.7, 'rgba(255,255,255,0.95)')
  grad.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = grad
  ctx.beginPath()
  ctx.arc(32, 32, 30, 0, Math.PI * 2)
  ctx.fill()
  _spriteTexture = new THREE.CanvasTexture(canvas)
  return _spriteTexture
}

export default {
  name: 'GraphCanvas',
  props: {
    schemaId:  { type: String,  default: '' },
    is3D:      { type: Boolean, default: false },
    colorMode:  { type: String,  default: 'type' },  // 'type' | 'cluster'
    minWeight:  { type: Number,  default: 0 },        // confidence threshold 0–1
  },
  emits: ['node-selected', 'node-deselected', 'stats-updated', 'schemas-loaded', 'graph-types-updated'],
  setup(props, { emit }) {
    const graphWrapper = ref(null)
    const loading      = ref(false)
    const loadingMsg   = ref('Loading\u2026')

    let G = null
    let focusedNodeId = null
    let neighborSet = new Set()
    let currentSearchQuery = ''
    const hiddenNodeTypes = new Set()
    const hiddenEdgeTypes = new Set()
    const hiddenClusters  = new Set()

    // Zoom level tracked for LOD (2D only)
    let currentZoom = 1

    // VirtualGraph manager
    const vGraph = new VirtualGraph()

    let resizeObserver = null

    // ── Lifecycle ──────────────────────────────────────────────────────────────

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

      await nextTick()
      await createGraph(props.is3D)

      resizeObserver = new ResizeObserver(() => {
        if (G && graphWrapper.value) {
          G.width(graphWrapper.value.clientWidth).height(graphWrapper.value.clientHeight)
        }
      })
      resizeObserver.observe(graphWrapper.value)
    })

    onBeforeUnmount(() => {
      resizeObserver?.disconnect()
      if (G) {
        G.pauseAnimation()
        G = null
      }
    })

    // ── Graph instance creation ────────────────────────────────────────────────

    async function createGraph(is3D) {
      if (!graphWrapper.value) return
      currentZoom = 1

      if (G) {
        G.pauseAnimation()
        G = null
      }
      graphWrapper.value.innerHTML = ''

      const w = graphWrapper.value.clientWidth || 800
      const h = graphWrapper.value.clientHeight || 600

      if (is3D) {
        await create3DGraph(w, h)
      } else {
        await create2DGraph(w, h)
      }
    }

    async function create3DGraph(w, h) {
      const [{ default: ForceGraph3D }, THREE] = await Promise.all([
        import('3d-force-graph'),
        import('three'),
      ])

      G = ForceGraph3D()(graphWrapper.value)
        .width(w).height(h)
        .backgroundColor('#0d0f1a')
        .showNavInfo(false)
        .nodeThreeObject(node => makeNodeSprite3D(node, THREE))
        .nodeThreeObjectExtend(false)
        .nodeId('id')
        .nodeLabel(nodeLabelFn)
        .nodeVisibility(nodeVisibilityFn)
        .linkDirectionalArrowLength(0)
        .linkSource('source')
        .linkTarget('target')
        .linkColor(linkColorFn)
        .linkWidth(0)
        .linkOpacity(0.6)
        .linkVisibility(linkVisibilityFn)
        // Disable physics — positions are precomputed on backend
        .d3Force('link', null)
        .d3Force('charge', null)
        .d3Force('center', null)
        .cooldownTicks(0)
        .onNodeClick(node => handleNodeClick(node))
        .onBackgroundClick(() => handleBackgroundClick())
        .graphData({ nodes: [], links: [] })
    }

    async function create2DGraph(w, h) {
      const { default: ForceGraph2D } = await import('force-graph')

      G = ForceGraph2D()(graphWrapper.value)
        .width(w).height(h)
        .backgroundColor('#0d0f1a')
        .nodeId('id')
        .nodeLabel(nodeLabelFn)
        .nodeColor(nodeColorFn)
        .nodeVal(node => Math.max(1, node.__val || 1))
        .nodeVisibility(nodeVisibilityFn)
        .linkSource('source')
        .linkTarget('target')
        .linkColor(linkColorFn)
        .linkWidth(1)
        .linkVisibility(linkVisibilityFn)
        // Disable physics — positions are precomputed on backend
        .d3Force('link', null)
        .d3Force('charge', null)
        .d3Force('center', null)
        .cooldownTicks(0)
        .onNodeClick(node => handleNodeClick(node))
        .onBackgroundClick(() => handleBackgroundClick())
        .onZoom(({ k }) => { currentZoom = k })
        .graphData({ nodes: [], links: [] })
    }

    // ── Sprite factory for 3D ──────────────────────────────────────────────────

    function makeNodeSprite3D(node, THREE) {
      const mat = new THREE.SpriteMaterial({
        map:         getSpriteTexture(THREE),
        color:       new THREE.Color(node.__color || computeNodeColor(node)),
        transparent: true,
        depthWrite:  false,
      })
      node.__material = mat
      const sprite = new THREE.Sprite(mat)
      const s = Math.max(3, Math.cbrt(node.__val || 1) * 5)
      sprite.scale.set(s, s, 1)
      return sprite
    }

    // ── Node/link accessor functions ──────────────────────────────────────────

    // Fast rgba builder using pre-parsed RGB — no parseInt at runtime
    function weightedColor(edgeType, weight) {
      const [r, g, b] = EDGE_COLORS_RGB[edgeType] || EDGE_COLORS_RGB.default
      const alpha = Math.max(0.12, Math.min(0.9, weight * 0.85 + 0.05))
      return `rgba(${r},${g},${b},${alpha})`
    }

    function nodeLabelFn(n) {
      return (
        '<div style="color:#e0e0e0;font-size:12px;background:rgba(13,15,26,.92);' +
        'padding:3px 8px;border-radius:4px;pointer-events:none">' +
        n.label + ' <em style="color:#7a9ab8">[' + n.nodeType + ']</em></div>'
      )
    }

    // ── Per-frame accessors: trivial property reads (called 60× per second per node/link)
    function nodeColorFn(node) { return node.__color || NODE_COLORS.default }
    function linkColorFn(link) { return link.__color || EDGE_COLORS.default }

    // ── Compute functions: called once in refreshVisual() when state changes
    function computeNodeColor(node) {
      const base = props.colorMode === 'cluster'
        ? clusterColor(node.cluster_id ?? node.properties?.cluster_id ?? null)
        : (NODE_COLORS[node.nodeType] || NODE_COLORS.default)
      if (focusedNodeId !== null) {
        if (node.id === focusedNodeId) return base
        if (neighborSet.has(node.id)) return base
        return '#111520'
      }
      if (currentSearchQuery) {
        const q = currentSearchQuery.toLowerCase()
        return (node.label || '').toLowerCase().includes(q) ? base : '#111520'
      }
      return base
    }

    function computeLinkColor(link) {
      const edgeType = link.edgeType || 'default'
      const w = link.weight ?? 1.0
      if (focusedNodeId !== null) {
        const s = typeof link.source === 'object' ? link.source.id : link.source
        const t = typeof link.target === 'object' ? link.target.id : link.target
        if (s === focusedNodeId || t === focusedNodeId) return weightedColor(edgeType, w)
        return '#111520'
      }
      return weightedColor(edgeType, w)
    }

    function nodeVisibilityFn(node) {
      if (hiddenNodeTypes.has(node.nodeType)) return false
      const cid = node.cluster_id ?? node.properties?.cluster_id ?? null
      if (cid !== null && hiddenClusters.has(cid)) return false
      // Zoom-based LOD (2D only): hide lower-importance types when zoomed out
      if (!props.is3D) {
        if (currentZoom < 0.4 && (node.nodeType === 'document' || node.nodeType === 'chunk')) return false
        if (currentZoom < 0.15 && node.nodeType === 'fact') return false
      }
      return true
    }

    function linkVisibilityFn(link) {
      if (hiddenEdgeTypes.has(link.edgeType)) return false
      if (props.minWeight > 0 && (link.weight ?? 1.0) < props.minWeight) return false
      return true
    }

    function refreshVisual() {
      if (!G) return
      // Pre-cache colors on node/link objects so per-frame accessors are O(1) reads.
      // This runs only when state changes (click, filter, search), not every frame.
      const { nodes, links } = G.graphData()
      nodes.forEach(node => {
        node.__color = computeNodeColor(node)
        if (node.__material) node.__material.color.set(node.__color)  // 3D sprite tint
      })
      links.forEach(link => { link.__color = computeLinkColor(link) })

      if (props.is3D) {
        G.nodeVisibility(nodeVisibilityFn)
          .linkColor(linkColorFn)
          .linkVisibility(linkVisibilityFn)
      } else {
        G.nodeColor(nodeColorFn)
          .nodeVisibility(nodeVisibilityFn)
          .linkColor(linkColorFn)
          .linkVisibility(linkVisibilityFn)
      }
    }

    // ── Click handlers ─────────────────────────────────────────────────────────

    function handleNodeClick(node) {
      // Focus mode: dim non-neighbors
      focusedNodeId = node.id
      neighborSet = new Set()
      if (G) {
        G.graphData().links.forEach(l => {
          const s = typeof l.source === 'object' ? l.source.id : l.source
          const t = typeof l.target === 'object' ? l.target.id : l.target
          if (s === node.id) neighborSet.add(t)
          if (t === node.id) neighborSet.add(s)
        })
      }
      refreshVisual()
      emit('node-selected', {
        id:               node.id,
        label:            node.label,
        nodeType:         node.nodeType,
        entityCollection: node.entityCollection,
        properties:       node.properties || {},
        cluster_id:       node.cluster_id ?? null,
        __degree:         node.__degree ?? null,
      })
    }

    function handleBackgroundClick() {
      if (focusedNodeId !== null) {
        focusedNodeId = null
        neighborSet = new Set()
        refreshVisual()
        emit('node-deselected')
      }
    }

    // ── Load graph data ────────────────────────────────────────────────────────

    async function loadGraph(schemaId) {
      if (!schemaId) return
      if (!G) {
        await nextTick()
        if (!G) return
      }

      hiddenNodeTypes.clear()
      hiddenEdgeTypes.clear()
      hiddenClusters.clear()
      currentSearchQuery = ''
      focusedNodeId = null
      neighborSet = new Set()

      vGraph.clear()

      loading.value = true
      loadingMsg.value = 'Fetching graph\u2026'

      try {
        const res = await vizAPI.getSchemaGraph(schemaId)
        const { nodes, edges } = res.data

        loadingMsg.value = 'Building graph (' + nodes.length + ' nodes, ' + edges.length + ' edges)\u2026'
        await nextTick()

        // Map API shape (_id, node_type, entity_collection) → VNode (id, nodeType, ...)
        const mappedNodes = nodes.map(n => ({
          ...n,
          id:               n._id || n.id,
          nodeType:         n.node_type || n.nodeType || 'default',
          entityCollection: n.entity_collection || n.entityCollection,
          cluster_id:       n.cluster_id ?? null,
          // Pin nodes at backend-computed confidence-weighted positions
          fx: n.x ?? 0,
          fy: n.y ?? 0,
          fz: 0,
        }))
        const mappedEdges = edges.map(e => ({
          ...e,
          source:   e.source_node_id || e.source,
          target:   e.target_node_id || e.target,
          edgeType: e.edge_type || e.edgeType || 'default',
        }))

        vGraph.addNodes(mappedNodes)
        vGraph.addEdges(mappedEdges)

        const presentNodeTypes = new Set()
        const presentEdgeTypes = new Set()
        for (const n of vGraph.nodes.values()) presentNodeTypes.add(n.nodeType)
        for (const e of vGraph.edges.values()) presentEdgeTypes.add(e.edgeType)

        emit('graph-types-updated', {
          nodeTypes: [...presentNodeTypes].sort(),
          edgeTypes: [...presentEdgeTypes].sort(),
        })

        if (G) {
          G.graphData(vGraph.toGraphData())
          refreshVisual()
        }

        emit('stats-updated', { nodes: vGraph.nodes.size, edges: vGraph.edges.size, partial: false })
      } catch (e) {
        console.error('Failed to load graph:', e)
        loadingMsg.value = 'Error loading graph'
      } finally {
        loading.value = false
      }
    }

    // ── Public API ─────────────────────────────────────────────────────────────

    function applySearch(query) {
      currentSearchQuery = query
      refreshVisual()
    }

    function setNodeTypeVisible(type, visible) {
      if (visible) hiddenNodeTypes.delete(type)
      else hiddenNodeTypes.add(type)
      refreshVisual()
    }

    function setEdgeTypeVisible(type, visible) {
      if (visible) hiddenEdgeTypes.delete(type)
      else hiddenEdgeTypes.add(type)
      refreshVisual()
    }

    async function expandType(nodeType) {
      if (!props.schemaId) return
      const loadedIds = [...vGraph.nodes.keys()]
      try {
        const res = await vizAPI.expandType(props.schemaId, nodeType, loadedIds)
        const mappedNodes = res.data.nodes.map(n => ({
          ...n,
          id:               n._id || n.id,
          nodeType:         n.node_type || n.nodeType || 'default',
          entityCollection: n.entity_collection || n.entityCollection,
          cluster_id:       n.cluster_id ?? null,
        }))
        const mappedEdges = res.data.edges.map(e => ({
          ...e,
          source:   e.source_node_id || e.source,
          target:   e.target_node_id || e.target,
          edgeType: e.edge_type || e.edgeType || 'default',
        }))
        vGraph.addNodes(mappedNodes)
        vGraph.addEdges(mappedEdges)
        if (G) {
          G.graphData(vGraph.toGraphData())
          refreshVisual()
        }
        emit('stats-updated', { nodes: vGraph.nodes.size, edges: vGraph.edges.size, partial: false })
      } catch (e) {
        console.error('Failed to expand type:', e)
      }
    }

    // ── Cluster visibility (Task 2) ────────────────────────────────────────────

    function setClusterVisible(clusterId, visible) {
      if (visible) hiddenClusters.delete(clusterId)
      else hiddenClusters.add(clusterId)
      refreshVisual()
    }

    function getClusters() {
      return getClustersFromNodes([...vGraph.nodes.values()])
    }

    // ── Expand node by ID (Task 4) ─────────────────────────────────────────────

    async function expandNodeById(nodeId) {
      if (!props.schemaId) return
      const loadedIds = [...vGraph.nodes.keys()]
      try {
        const res = await vizAPI.expandNode(props.schemaId, nodeId, loadedIds)
        const { nodes: newNodes, edges: newEdges } = res.data
        const mappedNodes = newNodes.map(n => ({
          ...n,
          id:               n._id || n.id,
          nodeType:         n.node_type || n.nodeType || 'default',
          entityCollection: n.entity_collection || n.entityCollection,
          cluster_id:       n.cluster_id ?? null,
        }))
        const mappedEdges = newEdges.map(e => ({
          ...e,
          source:   e.source_node_id || e.source,
          target:   e.target_node_id || e.target,
          edgeType: e.edge_type || e.edgeType || 'default',
        }))
        vGraph.addNodes(mappedNodes)
        vGraph.addEdges(mappedEdges)
        vGraph.markExpanded(nodeId)
        if (G) {
          G.graphData(vGraph.toGraphData())
          refreshVisual()
        }
        emit('stats-updated', { nodes: vGraph.nodes.size, edges: vGraph.edges.size, partial: false })
      } catch (e) {
        console.error('expandNodeById failed:', e)
      }
    }

    // ── Watchers ──────────────────────────────────────────────────────────────

    watch(() => props.schemaId,  id => { if (id) loadGraph(id) })
    watch(() => props.colorMode, () => refreshVisual())
    watch(() => props.minWeight, () => refreshVisual())
    watch(() => props.is3D, async () => {
      const currentData = vGraph.toGraphData()
      await createGraph(props.is3D)
      if (currentData.nodes.length && G) {
        G.graphData(currentData)
        refreshVisual()
      }
    })

    return {
      graphWrapper, loading, loadingMsg,
      applySearch, expandType,
      setNodeTypeVisible, setEdgeTypeVisible,
      setClusterVisible, getClusters,
      expandNodeById,
    }
  },
}
</script>

<style scoped>
.graph-container {
  width: 100%;
  height: 100%;
  position: relative;
  background: #0d0f1a;
  overflow: hidden;
}

.graph-wrapper {
  position: absolute;
  inset: 0;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(13, 15, 26, 0.82);
  z-index: 5;
  gap: 16px;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #2a2f3e;
  border-top-color: #4a90e2;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.loading-text { color: #9aa; font-size: 14px; }

.empty-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #3a4050;
  font-size: 16px;
}
</style>
