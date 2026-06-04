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
        transform: tooltip.flipX ? 'translate(calc(-100% - 14px), -50%)' : 'translate(14px, -50%)'
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

export interface DisplayConfig {
  nodeSizeScale: number      // 0.5 – 3.0
  linkWidthScale: number     // 0.5 – 3.0
  linkParticles: boolean
  linkParticleCount: number  // 1 – 6
  linkParticleSpeed: number  // 0.5 – 2.0
  repulsion: number          // 0.1 – 10
  linkDistance: number       // 1 – 100
  gravity: number            // 0 – 1.0
  searchQuery: string
}

const DEFAULT_DISPLAY: DisplayConfig = {
  nodeSizeScale: 0.5,
  linkWidthScale: 0.5,
  linkParticles: false,
  linkParticleCount: 2,
  linkParticleSpeed: 1,
  repulsion: 4.0,
  linkDistance: 60,
  gravity: 1,
  searchQuery: '',
}

const initError = ref<string | null>(null)
const tooltip = ref({ visible: false, label: '', x: 0, y: 0, flipX: false })

const props = defineProps<{
  bundle?: GraphRenderBundle | null
  nodes?: GraphNode[]
  edges?: GraphEdge[]
  hiddenTypes?: Set<string>
  hiddenEdgeTypes?: Set<string>
  display?: Partial<DisplayConfig>
}>()

const emit = defineEmits<{
  (e: 'nodeClick', node: GraphNode): void
  (e: 'backgroundClick'): void
}>()

const containerEl = ref<HTMLDivElement | null>(null)
let graph: Graph | null = null

let _cachedNodeIds: string[] = []
let _cachedHoverLabels: string[] = []
let _cachedNodeSummaries: GraphRenderNodeSummary[] = []
let _idToVisibleIndex = new Map<string, number>()
let _selectedIndex: number | null = null
// Live positions scraped from the running simulation (cosmos space)
const _livePositions = new Map<string, [number, number]>()

function getNodeColor(nodeType: string): [number, number, number, number] {
  return NODE_TYPE_COLORS[nodeType] ?? DEFAULT_NODE_COLOR
}

function getEdgeColor(edgeType: string, props_: Record<string, unknown>): [number, number, number, number] {
  if (edgeType === 'cites' && props_?.internal === false) {
    return [140/255, 140/255, 160/255, 0.22]  // faded gray for external citations
  }
  return EDGE_TYPE_COLORS[edgeType] ?? DEFAULT_EDGE_COLOR
}

function getNodeSize(degree: number | undefined, scale = 1): number {
  const d = degree ?? 0
  return Math.min(28, (2.5 + Math.log2(d + 1) * 3)) * scale
}

function hasValid2dCoords(node: GraphNode): node is GraphNode & { x2d: number; y2d: number } {
  return Number.isFinite(node.x2d) && Number.isFinite(node.y2d)
}

function buildGraphData(
  nodes: GraphNode[],
  edges: GraphEdge[],
  hiddenTypes?: Set<string>,
  hiddenEdgeTypes?: Set<string>,
  sizeScale = 1,
  widthScale = 1,
) {
  const visibleNodes = hiddenTypes?.size
    ? nodes.filter(n => !hiddenTypes.has(n.node_type))
    : nodes

  const idToIndex = new Map<string, number>()
  visibleNodes.forEach((n, i) => idToIndex.set(n._id, i))

  const count = visibleNodes.length
  const positions = new Float32Array(count * 2)
  const colors    = new Float32Array(count * 4)
  const sizes     = new Float32Array(count)

  for (let i = 0; i < count; i++) {
    const n = visibleNodes[i]
    if (hasValid2dCoords(n)) {
      positions[i * 2]     = n.x2d
      positions[i * 2 + 1] = n.y2d
    } else {
      const angle = i * 2.399963
      const radius = 50 * Math.sqrt(i + 1)
      positions[i * 2]     = Math.cos(angle) * radius
      positions[i * 2 + 1] = Math.sin(angle) * radius
    }
    const [r, g, b, a] = getNodeColor(n.node_type)
    colors[i * 4]     = r
    colors[i * 4 + 1] = g
    colors[i * 4 + 2] = b
    colors[i * 4 + 3] = a
    sizes[i] = getNodeSize(n.degree, sizeScale)
  }

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
    linkWidths[i] = Math.max(1, (e.weight ?? 1) * 3.5 * widthScale)
  }

  return { visibleNodes, positions, colors, sizes, linkArr, linkColors, linkWidths }
}

// ---- Scrape current node positions from cosmos ------------------------------

function scrapeLivePositions() {
  if (!graph || !props.bundle) return
  const b = props.bundle
  const raw = graph.getPointPositions()
  if (!raw) return
  for (let i = 0; i < b.nodeIds.length; i++) {
    const x = raw[i * 2]
    const y = raw[i * 2 + 1]
    if (Number.isFinite(x) && Number.isFinite(y)) {
      _livePositions.set(b.nodeIds[i], [x, y])
    }
  }
}

// ---- Build filtered typed arrays from bundle --------------------------------

function buildBundleData(
  b: NonNullable<typeof props.bundle>,
  hiddenTypes: Set<string> | undefined,
  hiddenEdgeTypes: Set<string> | undefined,
  sizeScale: number,
  widthScale: number,
  searchQuery: string,
  preservePositions: boolean,
) {
  // Filter nodes
  const visibleIndices: number[] = []
  for (let i = 0; i < b.nodeCount; i++) {
    if (!hiddenTypes?.has(b.nodeTypes[i])) visibleIndices.push(i)
  }

  const count = visibleIndices.length
  const positions = new Float32Array(count * 2)
  const colors    = new Float32Array(count * 4)
  const sizes     = new Float32Array(count)
  const newNodeIds: string[] = new Array(count)
  const newHoverLabels: string[] = new Array(count)
  const newNodeSummaries: GraphRenderNodeSummary[] = new Array(count)
  // mapping from old bundle index → new filtered index (for edge remapping)
  const oldToNew = new Map<number, number>()

  const q = searchQuery.trim().toLowerCase()

  for (let ni = 0; ni < count; ni++) {
    const oi = visibleIndices[ni]
    oldToNew.set(oi, ni)
    const nodeId = b.nodeIds[oi]
    newNodeIds[ni] = nodeId
    newHoverLabels[ni] = b.hoverLabels[oi]
    newNodeSummaries[ni] = b.nodeSummaries[oi]

    // Position: use live position if preserving, else recompute the same spiral
    // used in the worker (oi = original bundle index → same angle/radius)
    if (preservePositions && _livePositions.has(nodeId)) {
      const [lx, ly] = _livePositions.get(nodeId)!
      positions[ni * 2]     = lx
      positions[ni * 2 + 1] = ly
    } else {
      const angle = oi * 2.399963
      const radius = Math.sqrt(oi + 1)
      positions[ni * 2]     = Math.cos(angle) * radius
      positions[ni * 2 + 1] = Math.sin(angle) * radius
    }

    // Color — copy from bundle, then dim if not matching search
    const baseAlpha = b.pointColors[oi * 4 + 3]
    const alpha = q
      ? (newHoverLabels[ni].toLowerCase().includes(q) ? baseAlpha : 0.07)
      : baseAlpha
    colors[ni * 4]     = b.pointColors[oi * 4]
    colors[ni * 4 + 1] = b.pointColors[oi * 4 + 1]
    colors[ni * 4 + 2] = b.pointColors[oi * 4 + 2]
    colors[ni * 4 + 3] = alpha

    sizes[ni] = b.pointSizes[oi] * sizeScale
  }

  // Filter edges — both endpoints must be visible, edge type must not be hidden
  const edgeCount = b.edgeCount
  const filteredLinkIndices: number[] = []
  const filteredLinkColors: number[] = []
  const filteredLinkWidths: number[] = []

  for (let ei = 0; ei < edgeCount; ei++) {
    const srcOld = b.linkIndices[ei * 2]
    const tgtOld = b.linkIndices[ei * 2 + 1]
    if (!oldToNew.has(srcOld) || !oldToNew.has(tgtOld)) continue
    if (hiddenEdgeTypes?.has(b.edgeTypes[ei])) continue
    filteredLinkIndices.push(oldToNew.get(srcOld)!, oldToNew.get(tgtOld)!)
    filteredLinkColors.push(
      b.linkColors[ei * 4],
      b.linkColors[ei * 4 + 1],
      b.linkColors[ei * 4 + 2],
      b.linkColors[ei * 4 + 3],
    )
    filteredLinkWidths.push(b.linkWidths[ei] * widthScale)
  }

  const linkIndices = new Float32Array(filteredLinkIndices)
  const linkColors  = new Float32Array(filteredLinkColors)
  const linkWidths  = new Float32Array(filteredLinkWidths)

  return { count, positions, colors, sizes, linkIndices, linkColors, linkWidths, newNodeIds, newHoverLabels, newNodeSummaries }
}

// ---- Lifecycle --------------------------------------------------------------

let _fitViewTimer: ReturnType<typeof setTimeout> | null = null
let _resizeObserver: ResizeObserver | null = null
// Whether we've auto-fitted the view after the first layout settle (per dataset).
let _didInitialFit = false

function getDisplayConfig(): Required<DisplayConfig> {
  return { ...DEFAULT_DISPLAY, ...props.display }
}

function initGraph() {
  if (!containerEl.value) return
  const d = getDisplayConfig()
  try {
    graph = new Graph(containerEl.value, {
      backgroundColor: '#0a0b0f',
      // Cosmos defaults are well-tuned; we only tweak a few for Obsidian feel.
      // decay=4000 → simulation settles in ~4s then stops drifting
      simulationDecay: 3000,
      simulationGravity: d.gravity,       // default 0.25 — pulls clusters toward center
      simulationCenter: 0,                // disable separate center force (gravity handles centering)
      simulationRepulsion: d.repulsion,   // default 1 — spread nodes apart
      simulationRepulsionTheta: 1.15,
      simulationFriction: 0.85,
      simulationLinkSpring: 1,            // default 1 — links act as springs
      simulationLinkDistance: d.linkDistance, // default 10
      pointSizeScale: 1,
      scalePointsOnZoom: true,
      // Don't fit on init — data/layout isn't settled yet (sim runs ~3s).
      // We fit once the simulation first settles via onSimulationEnd below.
      fitViewOnInit: false,
      // Obsidian-style rings
      renderHoveredPointRing: true,
      hoveredPointRingColor: '#ffffff55',
      focusedPointRingColor: '#ffffffcc',
      // Dim unconnected nodes on selection
      pointGreyoutOpacity: 0.06,
      linkGreyoutOpacity: 0.04,
      hoveredPointCursor: 'pointer',
      // Scrape live positions every tick so we can preserve layout on filter changes
      onSimulationTick: () => { scrapeLivePositions() },
      onSimulationEnd: () => {
        // Auto-fit once, after the very first time the layout settles, so the
        // graph lands inside the viewport without a manual "Fit view" click.
        if (!_didInitialFit) {
          _didInitialFit = true
          graph?.fitView(400)
        }
      },
      onClick: (index, _pos, _ev) => {
        if (index === undefined) {
          _selectedIndex = null
          graph?.unselectPoints()
          graph?.setConfig({ focusedPointIndex: undefined })
          emit('backgroundClick')
        } else {
          if (index < _cachedNodeSummaries.length) {
            _selectedIndex = index
            graph?.selectPointByIndex(index, true)
            graph?.setConfig({ focusedPointIndex: index })
            const s = _cachedNodeSummaries[index]
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
        const flipX = x > rect.width - 360
        tooltip.value = { visible: true, label, x, y, flipX }
      },
    })
    pushData()

    _resizeObserver = new ResizeObserver(() => { graph?.render() })
    _resizeObserver.observe(containerEl.value)
    containerEl.value.addEventListener('mouseleave', () => { tooltip.value.visible = false })
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e ?? 'WebGL initialisation failed')
    initError.value = msg
    console.error('[CosmographCanvas] Graph init failed:', e)
  }
}

function pushData(preservePositions = false, alpha = 1) {
  if (!graph) return
  const d = getDisplayConfig()
  try {
    if (props.bundle) {
      const b = props.bundle
      const { positions, colors, sizes, linkIndices, linkColors, linkWidths, newNodeIds, newHoverLabels, newNodeSummaries } =
        buildBundleData(b, props.hiddenTypes, props.hiddenEdgeTypes, d.nodeSizeScale, d.linkWidthScale, d.searchQuery, preservePositions)

      console.log('[CosmographCanvas] pushData bundle', {
        preservePositions, alpha,
        nodeCount: newNodeIds.length,
        edgeCount: linkIndices.length / 2,
        pos0: [positions[0], positions[1]],
        pos1: [positions[2], positions[3]],
        livePositionsSize: _livePositions.size,
      })

      _cachedNodeIds = newNodeIds
      _cachedHoverLabels = newHoverLabels
      _cachedNodeSummaries = newNodeSummaries
      _idToVisibleIndex = new Map(newNodeIds.map((id, i) => [id, i]))

      // Pass `preservePositions` as shouldSkipRescale — when true, cosmos won't
      // normalize/rescale positions, so live positions are used as-is.
      graph.setPointPositions(positions, preservePositions)
      graph.setPointColors(colors)
      graph.setPointSizes(sizes)
      graph.setLinks(linkIndices)
      graph.setLinkColors(linkColors)
      graph.setLinkWidths(linkWidths)

      if (alpha > 0) graph.start(alpha)
      graph.render()
      return
    }

    // Legacy raw-node path
    const rawNodes = props.nodes ?? []
    const rawEdges = props.edges ?? []
    const { visibleNodes, positions, colors, sizes, linkArr, linkColors, linkWidths } =
      buildGraphData(rawNodes, rawEdges, props.hiddenTypes, props.hiddenEdgeTypes, d.nodeSizeScale, d.linkWidthScale)

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
      supports: n.supports ?? 0,
      opposes: n.opposes ?? 0,
    }))
    _idToVisibleIndex = new Map(visibleNodes.map((n, i) => [n._id, i]))

    const q = d.searchQuery.trim().toLowerCase()
    if (q) {
      for (let i = 0; i < _cachedHoverLabels.length; i++) {
        if (!_cachedHoverLabels[i].toLowerCase().includes(q)) colors[i * 4 + 3] = 0.07
      }
    }

    graph.setPointPositions(positions, preservePositions)
    graph.setPointColors(colors)
    graph.setPointSizes(sizes)
    graph.setLinks(linkArr)
    graph.setLinkColors(linkColors)
    graph.setLinkWidths(linkWidths)

    if (alpha > 0) graph.start(alpha)
    graph.render()
  } catch (e: unknown) {
    console.error('[CosmographCanvas] pushData failed:', e)
  }
}

function scheduleFitView(delay: number) {
  if (_fitViewTimer !== null) clearTimeout(_fitViewTimer)
  _fitViewTimer = setTimeout(() => {
    graph?.fitView(400)
    _fitViewTimer = null
  }, delay)
}

// Update sim config when display controls change without pushing full data
function applySimConfig() {
  if (!graph) return
  const d = getDisplayConfig()
  graph.setConfig({
    simulationRepulsion: d.repulsion,
    simulationLinkDistance: d.linkDistance,
    simulationGravity: d.gravity,
  })
  graph.start(0.3)
}

onMounted(() => { initGraph() })

onUnmounted(() => {
  if (_fitViewTimer !== null) { clearTimeout(_fitViewTimer); _fitViewTimer = null }
  _resizeObserver?.disconnect()
  _resizeObserver = null
  graph?.destroy()
  graph = null
})

watch(
  () => [props.bundle, props.nodes, props.edges, props.hiddenTypes, props.hiddenEdgeTypes, props.display] as const,
  (newVal, oldVal) => {
    if (!graph) return
    const dataChanged = oldVal
      ? newVal[0] !== oldVal[0] || newVal[1] !== oldVal[1] || newVal[2] !== oldVal[2]
      : true
    const filterChanged = oldVal
      ? newVal[3] !== oldVal[3] || newVal[4] !== oldVal[4]
      : false
    const searchChanged = oldVal
      ? (newVal[5]?.searchQuery ?? '') !== (oldVal[5]?.searchQuery ?? '')
      : false
    const simParamChanged = oldVal
      ? (newVal[5]?.repulsion !== oldVal[5]?.repulsion ||
         newVal[5]?.linkDistance !== oldVal[5]?.linkDistance ||
         newVal[5]?.gravity !== oldVal[5]?.gravity)
      : false
    const visualChanged = oldVal
      ? (newVal[5]?.nodeSizeScale !== oldVal[5]?.nodeSizeScale ||
         newVal[5]?.linkWidthScale !== oldVal[5]?.linkWidthScale)
      : false

    if (dataChanged) {
      _selectedIndex = null
      _livePositions.clear()
      _didInitialFit = false  // re-fit once the new dataset's layout settles
      graph.unselectPoints()
      graph.setConfig({ focusedPointIndex: undefined })
      pushData(false, 1)
    } else if (filterChanged || searchChanged) {
      // Scrape current positions before rebuilding filtered arrays
      scrapeLivePositions()
      pushData(true, 0.1)
    } else if (simParamChanged) {
      applySimConfig()
    } else if (visualChanged) {
      scrapeLivePositions()
      pushData(true, 0)  // alpha=0 → update buffers only, no sim restart
    }
  },
  { deep: false },
)

defineExpose({
  fitView: () => graph?.fitView?.(400),
  focusNode: (nodeId: string | null) => {
    if (!graph) return
    if (nodeId === null) {
      _selectedIndex = null
      graph.unselectPoints()
      graph.setConfig({ focusedPointIndex: undefined })
      graph.fitView(500)
      return
    }
    const index = _idToVisibleIndex.get(nodeId)
    if (index === undefined) return
    _selectedIndex = index
    graph.selectPointByIndex(index, true)
    graph.setConfig({ focusedPointIndex: index })
    graph.zoomToPointByIndex(index, 600, 4, true)
  },
})
</script>

<style scoped>
.cosmo-canvas {
  flex: 1;
  min-height: 0;
  width: 100%;
  height: 100%;
  display: block;
  background: #0a0b0f;
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

/* Obsidian-style tooltip: dark pill with subtle glow border */
.cosmo-tooltip {
  position: absolute;
  pointer-events: none;
  background: rgba(10, 11, 20, 0.92);
  border: 1px solid rgba(120, 140, 200, 0.35);
  border-radius: 6px;
  padding: 0.28rem 0.65rem;
  font-size: 0.72rem;
  color: #d4d8e8;
  white-space: normal;
  max-width: 300px;
  word-break: break-word;
  line-height: 1.45;
  box-shadow: 0 0 12px rgba(80, 100, 220, 0.25), 0 4px 16px rgba(0,0,0,0.6);
  z-index: 10;
  backdrop-filter: blur(4px);
}
</style>
