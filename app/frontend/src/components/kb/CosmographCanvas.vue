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
import type { GraphRenderBundle, GraphRenderNodeSummary } from '@/types/graphArtifact'
import {
  NODE_TYPE_COLORS, DEFAULT_NODE_COLOR,
  EDGE_TYPE_COLORS, DEFAULT_EDGE_COLOR,
} from '@/utils/kbColors'

const initError = ref<string | null>(null)

// Tooltip state
const tooltip = ref({ visible: false, label: '', x: 0, y: 0, flipX: false })

const props = defineProps<{
  // Artifact bundle path (preferred — pre-built typed arrays)
  bundle?: GraphRenderBundle | null
  // Legacy raw-node path (still used while migrating; ignored when bundle present)
  nodes?: GraphNode[]
  edges?: GraphEdge[]
  hiddenTypes?: Set<string>
  hiddenEdgeTypes?: Set<string>
}>()

const emit = defineEmits<{
  (e: 'nodeClick', node: GraphNode): void
  (e: 'backgroundClick'): void
}>()

const containerEl = ref<HTMLDivElement | null>(null)
let graph: Graph | null = null

// Cache of the most-recently rendered node list / summaries.
// Used by the onClick / onMouseMove handlers.
let _cachedNodeIds: string[] = []
let _cachedHoverLabels: string[] = []
let _cachedNodeSummaries: GraphRenderNodeSummary[] = []
// Reverse map: node id → visible index
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

function hasValid2dCoords(node: GraphNode): node is GraphNode & { x2d: number; y2d: number } {
  return Number.isFinite(node.x2d) && Number.isFinite(node.y2d)
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
    if (hasValid2dCoords(n)) {
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
    const [r, g, b, a] = getEdgeColor(e.edge_type, e.properties ?? {})
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
      // Leave more breathing room when we need a client-side fallback layout.
      simulationGravity: 0.1,
      simulationRepulsion: 2.2,
      simulationRepulsionTheta: 1.15,
      simulationFriction: 0.85,
      simulationLinkSpring: 0.5,
      simulationLinkDistance: 70,
      simulationDecay: 5000,
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
            if (index < _cachedNodeSummaries.length) {
              const s = _cachedNodeSummaries[index]
              // Emit in the GraphNode shape that the rest of the app expects
              emit('nodeClick', {
                _id: s.id,
                schema_id: '',
                node_type: s.type,
                entity_collection: s.entity_collection,
                entity_id: s.entity_id,
                label: s.label,
                properties: s.props,
                degree: s.degree,
              } satisfies GraphNode)
            }
          }
        },
        onMouseMove: (index, _pos, ev) => {
          if (index === undefined || index >= _cachedHoverLabels.length) {
            tooltip.value.visible = false
            return
          }
          const rect = containerEl.value!.getBoundingClientRect()
          const x = ev.clientX - rect.left
          const y = ev.clientY - rect.top
          const label = _cachedHoverLabels[index] ?? ''
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
    // ── Bundle path (artifact-backed, pre-built typed arrays) ─────────────
    if (props.bundle) {
      const b = props.bundle

      // Apply type visibility filters by rebuilding a visibility mask when
      // hiddenTypes is set. For now we pass the full arrays unfiltered — the
      // type-filter path for bundle mode will be added in a follow-up once
      // the artifact pipeline is stable.
      _cachedNodeIds = b.nodeIds
      _cachedHoverLabels = b.hoverLabels
      _cachedNodeSummaries = b.nodeSummaries
      _idToVisibleIndex = new Map(b.nodeIds.map((id, i) => [id, i]))

      graph.setPointPositions(b.pointPositions)
      graph.setPointColors(b.pointColors)
      graph.setPointSizes(b.pointSizes)
      graph.setLinks(b.linkIndices)
      graph.setLinkColors(b.linkColors)
      graph.setLinkWidths(b.linkWidths)

      // All artifact nodes have server-side layout coords — freeze simulation.
      graph.stop()
      graph.render(0)

      if (autoFit) {
        if (_fitViewTimer !== null) clearTimeout(_fitViewTimer)
        _fitViewTimer = setTimeout(() => {
          graph?.fitView(400)
          _fitViewTimer = null
        }, 80)
      }
      return
    }

    // ── Legacy raw-node path ───────────────────────────────────────────────
    const rawNodes = props.nodes ?? []
    const rawEdges = props.edges ?? []
    const { visibleNodes, positions, colors, sizes, linkArr, linkColors, linkWidths } =
      buildGraphData(rawNodes, rawEdges, props.hiddenTypes, props.hiddenEdgeTypes)

    _cachedNodeIds = visibleNodes.map(n => n._id)
    _cachedHoverLabels = visibleNodes.map(n => n.label ?? '')
    _cachedNodeSummaries = visibleNodes.map(n => ({
      id: n._id,
      type: n.node_type,
      label: n.label,
      degree: n.degree ?? 0,
      entity_collection: n.entity_collection,
      entity_id: n.entity_id,
      props: n.properties,
    }))
    _idToVisibleIndex = new Map(visibleNodes.map((n, i) => [n._id, i]))

    const shouldFreeze = visibleNodes.length > 0 && visibleNodes.every(hasValid2dCoords)

    graph.setPointPositions(positions)
    graph.setPointColors(colors)
    graph.setPointSizes(sizes)
    graph.setLinks(linkArr)
    graph.setLinkColors(linkColors)
    graph.setLinkWidths(linkWidths)

    if (shouldFreeze) {
      graph.stop()
      graph.render(0)
    } else {
      graph.start(1)
      graph.render()
    }

    if (autoFit) {
      if (_fitViewTimer !== null) clearTimeout(_fitViewTimer)
      _fitViewTimer = setTimeout(() => {
        graph?.fitView(400)
        _fitViewTimer = null
      }, shouldFreeze ? 80 : 600)
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
  () => [props.bundle, props.nodes, props.edges, props.hiddenTypes, props.hiddenEdgeTypes] as const,
  (newVal, oldVal) => {
    if (graph) {
      // Auto-fit whenever the bundle or the raw nodes/edges arrays change.
      // For filter-only changes (hiddenTypes/hiddenEdgeTypes) we skip auto-fit.
      const dataChanged = oldVal
        ? newVal[0] !== oldVal[0] || newVal[1] !== oldVal[1] || newVal[2] !== oldVal[2]
        : true
      pushData(dataChanged)
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
      graph.fitView(500)
      return
    }
    const index = _idToVisibleIndex.get(nodeId)
    if (index === undefined) return
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
