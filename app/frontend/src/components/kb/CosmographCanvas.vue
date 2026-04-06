<template>
  <div ref="containerEl" class="cosmo-canvas">
    <div v-if="initError" class="cosmo-error">
      <span>WebGL unavailable: {{ initError }}</span>
    </div>
    <!-- Hover tooltip -->
    <div
      v-if="tooltip.visible"
      class="cosmo-tooltip"
      :style="{
        left: tooltip.x + 'px',
        top: tooltip.y + 'px',
        transform: tooltip.flipX ? 'translate(calc(-100% - 12px), -50%)' : 'translate(12px, -50%)'
      }"
    >{{ tooltip.label }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { Graph } from '@cosmos.gl/graph'
import type { GraphNode, GraphEdge } from '@/utils/kbApi'
import {
  NODE_TYPE_COLORS, DEFAULT_NODE_COLOR,
  EDGE_TYPE_COLORS, DEFAULT_EDGE_COLOR,
} from '@/utils/kbColors'

const initError = ref<string | null>(null)

// Tooltip state
const tooltip = ref({ visible: false, label: '', x: 0, y: 0, flipX: false })

const props = defineProps<{
  nodes: GraphNode[]
  edges: GraphEdge[]
  hiddenTypes?: Set<string>
  hiddenEdgeTypes?: Set<string>
}>()

const emit = defineEmits<{
  (e: 'nodeClick', node: GraphNode): void
  (e: 'backgroundClick'): void
}>()

const containerEl = ref<HTMLDivElement | null>(null)
let graph: Graph | null = null

// Cache of the most-recently rendered visible node array.
// Used by the onClick handler to map index → node without rebuilding.
let _cachedVisibleNodes: GraphNode[] = []
// Reverse map: node _id → visible index (kept in sync with _cachedVisibleNodes)
let _idToVisibleIndex = new Map<string, number>()

function getNodeColor(nodeType: string): [number, number, number, number] {
  return NODE_TYPE_COLORS[nodeType] ?? DEFAULT_NODE_COLOR
}

function getEdgeColor(edgeType: string, props_: Record<string, unknown>): [number, number, number, number] {
  if (edgeType === 'cites' && props_?.internal === false) {
    return [150/255, 150/255, 150/255, 0.31]  // faded gray for external citations
  }
  return EDGE_TYPE_COLORS[edgeType] ?? DEFAULT_EDGE_COLOR
}

function getNodeSize(degree: number | undefined): number {
  const d = degree ?? 0
  return Math.min(20, 2 + Math.log2(d + 1) * 2.5)
}

// ---- Build typed arrays from nodes/edges ------------------------------------

function buildGraphData(nodes: GraphNode[], edges: GraphEdge[], hiddenTypes?: Set<string>, hiddenEdgeTypes?: Set<string>) {
  const visibleNodes = hiddenTypes?.size
    ? nodes.filter(n => !hiddenTypes.has(n.node_type))
    : nodes

  // Build index map: node _id → array index
  const idToIndex = new Map<string, number>()
  visibleNodes.forEach((n, i) => idToIndex.set(n._id, i))

  const count = visibleNodes.length

  const positions = new Float32Array(count * 2)
  const colors    = new Float32Array(count * 4)
  const sizes     = new Float32Array(count)

  for (let i = 0; i < count; i++) {
    const n = visibleNodes[i]
    // Use pre-computed layout if available; for nodes without coords use a
    // stable deterministic spread based on index so they don't jump on
    // re-render (e.g. after type filter toggle).
    if (n.x2d !== undefined && n.y2d !== undefined) {
      positions[i * 2]     = n.x2d
      positions[i * 2 + 1] = n.y2d
    } else {
      // Deterministic spiral placement for new nodes (no random jitter)
      const angle = i * 2.399963  // golden angle
      const radius = 50 * Math.sqrt(i + 1)
      positions[i * 2]     = Math.cos(angle) * radius
      positions[i * 2 + 1] = Math.sin(angle) * radius
    }
    const [r, g, b, a] = getNodeColor(n.node_type)
    colors[i * 4]     = r
    colors[i * 4 + 1] = g
    colors[i * 4 + 2] = b
    colors[i * 4 + 3] = a
    sizes[i] = getNodeSize(n.degree)
  }

  // Build edges using index mapping, filtering hidden edge types
  const validEdges = edges.filter(
    e => idToIndex.has(e.source_node_id) && idToIndex.has(e.target_node_id)
      && !(hiddenEdgeTypes?.has(e.edge_type)),
  )

  const linkArr    = new Float32Array(validEdges.length * 2)
  const linkColors = new Float32Array(validEdges.length * 4)
  const linkWidths = new Float32Array(validEdges.length)

  for (let i = 0; i < validEdges.length; i++) {
    const e = validEdges[i]
    linkArr[i * 2]     = idToIndex.get(e.source_node_id)!
    linkArr[i * 2 + 1] = idToIndex.get(e.target_node_id)!
    const [r, g, b, a] = getEdgeColor(e.edge_type, e.properties)
    linkColors[i * 4]     = r
    linkColors[i * 4 + 1] = g
    linkColors[i * 4 + 2] = b
    linkColors[i * 4 + 3] = a
    linkWidths[i] = Math.max(1.5, (e.weight ?? 1) * 4.5)
  }

  return { visibleNodes, positions, colors, sizes, linkArr, linkColors, linkWidths }
}

// ---- Lifecycle --------------------------------------------------------------

let _fitViewTimer: ReturnType<typeof setTimeout> | null = null
let _resizeObserver: ResizeObserver | null = null

function initGraph() {
  if (!containerEl.value) return
  try {
    graph = new Graph(containerEl.value, {
      backgroundColor: '#0f172a',
      // Better force-directed layout parameters to spread nodes evenly
      simulationGravity: 0.1,
      simulationRepulsion: 1.5,
      simulationRepulsionTheta: 1.15,
      simulationFriction: 0.85,
      simulationLinkSpring: 0.5,
      simulationLinkDistance: 30,
      simulationDecay: 2000,
      simulationCenter: 0.1,
      pointSizeScale: 1,
      scalePointsOnZoom: true,
      // fitViewOnInit fires once after the first render(); subsequent data
      // pushes call fitView() manually below.
      fitViewOnInit: true,
      fitViewDelay: 500,
        onClick: (index, _pos, _ev) => {
          if (index === undefined) {
            emit('backgroundClick')
          } else {
            // Use the cached visible-node list — no rebuild needed
            if (index < _cachedVisibleNodes.length) {
              emit('nodeClick', _cachedVisibleNodes[index])
            }
          }
        },
        onMouseMove: (index, _pos, ev) => {
          if (index === undefined || index >= _cachedVisibleNodes.length) {
            tooltip.value.visible = false
            return
          }
          const rect = containerEl.value!.getBoundingClientRect()
          const x = ev.clientX - rect.left
          const y = ev.clientY - rect.top
          const label = _cachedVisibleNodes[index].label ?? ''
          // Flip to left side when within 340px of the right edge
          const flipX = x > rect.width - 340
          tooltip.value = { visible: true, label, x, y, flipX }
        },
    })
    pushData()

    // Resize observer: re-render when the container changes dimensions so
    // cosmos re-samples the canvas size on the next frame.
    _resizeObserver = new ResizeObserver(() => {
      graph?.render()
    })
    _resizeObserver.observe(containerEl.value)
    containerEl.value.addEventListener('mouseleave', () => { tooltip.value.visible = false })
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e ?? 'WebGL initialisation failed')
    initError.value = msg
    console.error('[CosmographCanvas] Graph init failed:', e)
  }
}

function pushData(autoFit = false) {
  if (!graph) return
  try {
    const { visibleNodes, positions, colors, sizes, linkArr, linkColors, linkWidths } =
      buildGraphData(props.nodes, props.edges, props.hiddenTypes, props.hiddenEdgeTypes)

    // Update cache so onClick can resolve the correct node
    _cachedVisibleNodes = visibleNodes
    _idToVisibleIndex = new Map(visibleNodes.map((n, i) => [n._id, i]))

    graph.setPointPositions(positions)
    graph.setPointColors(colors)
    graph.setPointSizes(sizes)
    graph.setLinks(linkArr)
    graph.setLinkColors(linkColors)
    graph.setLinkWidths(linkWidths)
    // render() processes pending data into GPU buffers and (re)starts the frame loop
    graph.render()

    // After a fresh data load, fit the view once the simulation has had
    // time to run.  fitViewOnInit only fires once (on the very first render
    // after Graph construction), so we need to trigger it ourselves for
    // every subsequent dataset.
    if (autoFit) {
      if (_fitViewTimer !== null) clearTimeout(_fitViewTimer)
      _fitViewTimer = setTimeout(() => {
        graph?.fitView(400)
        _fitViewTimer = null
      }, 600)
    }
  } catch (e: unknown) {
    console.error('[CosmographCanvas] pushData failed:', e)
  }
}

onMounted(() => {
  initGraph()
})

onUnmounted(() => {
  if (_fitViewTimer !== null) { clearTimeout(_fitViewTimer); _fitViewTimer = null }
  _resizeObserver?.disconnect()
  _resizeObserver = null
  graph?.destroy()
  graph = null
})

watch(
  () => [props.nodes, props.edges, props.hiddenTypes, props.hiddenEdgeTypes] as const,
  (newVal, oldVal) => {
    if (graph) {
      // Auto-fit whenever the nodes/edges arrays themselves change (new dataset).
      // For hiddenTypes/hiddenEdgeTypes-only changes (filtering) we skip auto-fit.
      const nodesChanged = oldVal ? newVal[0] !== oldVal[0] || newVal[1] !== oldVal[1] : true
      pushData(nodesChanged)
    }
  },
  { deep: false },
)

// Public: expose fitView and selectNode for parent to call
defineExpose({
  fitView: () => graph?.fitView?.(400),
  focusNode: (nodeId: string | null) => {
    if (!graph) return
    if (nodeId === null) {
      // Deselect: zoom back out to fit all nodes
      graph.fitView(500)
      return
    }
    const index = _idToVisibleIndex.get(nodeId)
    if (index === undefined) return
    // Zoom to the node: 600ms animation, scale 4 (comfortable zoom level),
    // canZoomOut=true so it zooms out if currently zoomed in more than scale 4
    graph.zoomToPointByIndex(index, 600, 4, true)
  },
})
</script>

<style scoped>
.cosmo-canvas {
  flex: 1;
  min-height: 0;
  width: 100%;
  display: block;
  background: #0f172a;
  position: relative;
}

.cosmo-canvas canvas {
  display: block;
  width: 100% !important;
  height: 100% !important;
}

.cosmo-error {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #f87171;
  font-size: 0.85rem;
  padding: 1rem;
  text-align: center;
}

.cosmo-tooltip {
  position: absolute;
  pointer-events: none;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 5px;
  padding: 0.25rem 0.6rem;
  font-size: 0.72rem;
  color: #e2e8f0;
  white-space: normal;
  max-width: 320px;
  word-break: break-word;
  line-height: 1.45;
  box-shadow: 0 4px 12px rgba(0,0,0,0.5);
  z-index: 10;
}
</style>
