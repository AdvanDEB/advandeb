<template>
  <div ref="wrapEl" class="canvas-wrap" :class="{ 'edge-mode': edgeMode }">
    <svg ref="svgEl" class="network-canvas"></svg>

    <p v-if="isEmpty" class="canvas-hint">
      Pick a template or add compartments to start building a transport network
    </p>

    <div v-if="edgeMode" class="edge-mode-hint">
      🔗 Click the <strong>source</strong> compartment, then the <strong>target</strong>
      · <kbd>Esc</kbd> to cancel
    </div>

    <div class="canvas-toolbar">
      <button class="canvas-btn" title="Zoom in" @click="zoomBy(1.3)">＋</button>
      <button class="canvas-btn" title="Zoom out" @click="zoomBy(1 / 1.3)">－</button>
      <button class="canvas-btn" title="Fit to view" @click="fitToView">⤢</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as d3 from 'd3'
import type { TDebEdge, TDebNode } from '@/utils/tdebApi'
import { nodeColor, nodeRadius } from '@/utils/tdebConstants'

const props = defineProps<{
  nodes: Record<string, TDebNode>
  edges: Record<string, TDebEdge>
  selected: { type: 'node' | 'edge'; id: string } | null
  edgeMode: boolean
}>()

const emit = defineEmits<{
  (e: 'select-node', id: string): void
  (e: 'select-edge', id: string): void
  (e: 'deselect'): void
  /** Fired continuously while dragging; the parent decides when to persist. */
  (e: 'move-node', payload: { id: string; x: number; y: number }): void
  (e: 'move-node-end', payload: { id: string; x: number; y: number }): void
  (e: 'connect', payload: { sourceId: string; targetId: string }): void
}>()

const wrapEl = ref<HTMLElement | null>(null)
const svgEl = ref<SVGSVGElement | null>(null)

const isEmpty = computed(() => Object.keys(props.nodes).length === 0)

type Svg = d3.Selection<SVGSVGElement, unknown, null, undefined>
type G = d3.Selection<SVGGElement, unknown, null, undefined>

let svg: Svg | null = null
let rootG: G | null = null
let linkGroup: G | null = null
let nodeGroup: G | null = null
let zoomBehavior: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null
let resizeObserver: ResizeObserver | null = null

/** First endpoint chosen while in edge-drawing mode. */
let pendingSource: string | null = null

// D3 mutates the datum objects it binds, so bind copies rather than the props
// themselves — writing straight into props would mutate parent state from a
// drag handler and desync the inspector.
interface CanvasNode { id: string; name: string; node_type: string; value: number; x: number; y: number }
interface CanvasEdge { id: string; name: string; source_id: string; target_id: string }

function canvasNodes(): CanvasNode[] {
  return Object.values(props.nodes).map(n => ({
    id: n.id, name: n.name, node_type: n.node_type, value: n.value, x: n.x, y: n.y,
  }))
}

function canvasEdges(): CanvasEdge[] {
  return Object.values(props.edges).map(e => ({
    id: e.id, name: e.name, source_id: e.source_id, target_id: e.target_id,
  }))
}

function nodePos(id: string): { x: number; y: number } {
  const n = props.nodes[id]
  return n ? { x: n.x, y: n.y } : { x: 0, y: 0 }
}

/**
 * Shorten a line so its head stops at the target circle's edge.
 *
 * Without this the arrow marker is hidden underneath the target node, and a
 * fixed marker `refX` cannot work because node radius varies by type.
 */
function edgeGeometry(d: CanvasEdge) {
  const s = nodePos(d.source_id)
  const t = nodePos(d.target_id)
  const dx = t.x - s.x
  const dy = t.y - s.y
  const dist = Math.hypot(dx, dy) || 1
  const targetR = nodeRadius(props.nodes[d.target_id]?.node_type ?? 'custom') + 9
  const sourceR = nodeRadius(props.nodes[d.source_id]?.node_type ?? 'custom')
  return {
    x1: s.x + (dx / dist) * sourceR,
    y1: s.y + (dy / dist) * sourceR,
    x2: t.x - (dx / dist) * targetR,
    y2: t.y - (dy / dist) * targetR,
    mx: (s.x + t.x) / 2,
    my: (s.y + t.y) / 2,
  }
}

// ─── setup ───────────────────────────────────────────────────────────

function initSvg() {
  if (!svgEl.value || !wrapEl.value) return

  svg = d3.select(svgEl.value)
  svg.selectAll('*').remove()

  const defs = svg.append('defs')

  for (const [id, fill] of [['tdeb-arrow', '#94a3b8'], ['tdeb-arrow-active', '#3b82f6']]) {
    defs.append('marker')
      .attr('id', id)
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 8)
      .attr('refY', 0)
      .attr('markerWidth', 7)
      .attr('markerHeight', 7)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L8,0L0,4')
      .attr('fill', fill)
  }

  rootG = svg.append('g').attr('class', 'canvas-group')
  linkGroup = rootG.append('g').attr('class', 'links')
  nodeGroup = rootG.append('g').attr('class', 'nodes')

  zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.2, 4])
    .on('zoom', (event) => { rootG?.attr('transform', event.transform.toString()) })

  svg.call(zoomBehavior)

  svg.on('click', (event: MouseEvent) => {
    if (event.target === svgEl.value) {
      cancelPendingEdge()
      emit('deselect')
    }
  })

  syncSize()
  render()
}

function syncSize() {
  if (!svg || !wrapEl.value) return
  svg.attr('width', wrapEl.value.clientWidth).attr('height', wrapEl.value.clientHeight)
}

// ─── render ──────────────────────────────────────────────────────────

function render() {
  if (!linkGroup || !nodeGroup) return

  const edges = canvasEdges()
  const nodes = canvasNodes()

  // ── edges ──
  const edgeSel = linkGroup.selectAll<SVGGElement, CanvasEdge>('.edge-group')
    .data(edges, d => d.id)

  edgeSel.exit().remove()

  const edgeEnter = edgeSel.enter().append('g').attr('class', 'edge-group')
  // A transparent wide line under the visible one: a 2px stroke is very hard to
  // hit with a mouse, so this gives the edge a usable click target.
  edgeEnter.append('line').attr('class', 'edge-hit')
  edgeEnter.append('line').attr('class', 'edge-line')
  edgeEnter.append('text').attr('class', 'edge-label')

  const edgeMerge = edgeEnter.merge(edgeSel)

  const isSelectedEdge = (d: CanvasEdge) =>
    props.selected?.type === 'edge' && props.selected.id === d.id

  edgeMerge.selectAll<SVGLineElement, CanvasEdge>('.edge-hit,.edge-line')
    .attr('x1', d => edgeGeometry(d).x1)
    .attr('y1', d => edgeGeometry(d).y1)
    .attr('x2', d => edgeGeometry(d).x2)
    .attr('y2', d => edgeGeometry(d).y2)

  edgeMerge.select<SVGLineElement>('.edge-line')
    .classed('selected', isSelectedEdge)
    .attr('marker-end', d => isSelectedEdge(d) ? 'url(#tdeb-arrow-active)' : 'url(#tdeb-arrow)')

  edgeMerge.select<SVGLineElement>('.edge-hit')
    .on('click', (event: MouseEvent, d) => {
      event.stopPropagation()
      if (!props.edgeMode) emit('select-edge', d.id)
    })

  edgeMerge.select<SVGTextElement>('.edge-label')
    .attr('x', d => edgeGeometry(d).mx)
    .attr('y', d => edgeGeometry(d).my - 8)
    .classed('selected', isSelectedEdge)
    .text(d => d.name)

  // ── nodes ──
  const nodeSel = nodeGroup.selectAll<SVGGElement, CanvasNode>('.node-group')
    .data(nodes, d => d.id)

  nodeSel.exit().remove()

  const nodeEnter = nodeSel.enter().append('g').attr('class', 'node-group')
  nodeEnter.append('circle').attr('class', 'node-halo')
  nodeEnter.append('circle').attr('class', 'node-circle')
  nodeEnter.append('text').attr('class', 'node-label')
  nodeEnter.append('text').attr('class', 'node-value')

  const nodeMerge = nodeEnter.merge(nodeSel)

  const drag = d3.drag<SVGGElement, CanvasNode>()
    .filter(() => !props.edgeMode)   // dragging would fight edge-drawing
    .clickDistance(4)                // let small movements still count as clicks
    .on('start', function () { d3.select(this).raise() })
    .on('drag', (event, d) => {
      d.x = event.x
      d.y = event.y
      emit('move-node', { id: d.id, x: event.x, y: event.y })
    })
    .on('end', (event, d) => {
      emit('move-node-end', { id: d.id, x: d.x, y: d.y })
    })

  nodeMerge
    .attr('transform', d => `translate(${d.x},${d.y})`)
    .call(drag)
    // In edge mode the zoom behaviour would swallow the mousedown and the click
    // event would never fire, so stop it before it reaches the svg.
    .on('mousedown.edgemode', (event: MouseEvent) => {
      if (props.edgeMode) event.stopPropagation()
    })
    .on('click', (event: MouseEvent, d) => {
      event.stopPropagation()
      if (props.edgeMode) handleEdgeModeClick(d.id)
      else emit('select-node', d.id)
    })

  const isSelectedNode = (d: CanvasNode) =>
    props.selected?.type === 'node' && props.selected.id === d.id

  nodeMerge.select<SVGCircleElement>('.node-circle')
    .attr('r', d => nodeRadius(d.node_type))
    .attr('fill', d => nodeColor(d.node_type))
    .classed('selected', isSelectedNode)
    .classed('edge-source', d => d.id === pendingSource)

  nodeMerge.select<SVGCircleElement>('.node-halo')
    .attr('r', d => nodeRadius(d.node_type) + 6)
    .attr('fill', d => nodeColor(d.node_type))

  nodeMerge.select<SVGTextElement>('.node-label')
    .attr('dy', d => -nodeRadius(d.node_type) - 9)
    .text(d => d.name)

  nodeMerge.select<SVGTextElement>('.node-value')
    .attr('dy', 4)
    .text(d => Number.isFinite(d.value) ? formatValue(d.value) : '')
}

/** Node values span many orders of magnitude, so avoid a fixed decimal count. */
function formatValue(v: number): string {
  const abs = Math.abs(v)
  if (abs === 0) return '0'
  if (abs >= 1e4 || abs < 1e-2) return v.toExponential(1)
  return v.toFixed(abs < 1 ? 3 : 1)
}

// ─── edge drawing ────────────────────────────────────────────────────

function handleEdgeModeClick(nodeId: string) {
  if (!pendingSource) {
    pendingSource = nodeId
    startRubberBand(nodeId)
    render()
    return
  }

  const sourceId = pendingSource
  cancelPendingEdge()
  if (sourceId !== nodeId) emit('connect', { sourceId, targetId: nodeId })
  render()
}

function startRubberBand(nodeId: string) {
  if (!rootG || !svg) return
  const pos = nodePos(nodeId)
  const line = rootG.append('line')
    .attr('class', 'rubber-band')
    .attr('x1', pos.x).attr('y1', pos.y)
    .attr('x2', pos.x).attr('y2', pos.y)
    .attr('pointer-events', 'none')
    .attr('marker-end', 'url(#tdeb-arrow-active)')

  svg.on('mousemove.edgemode', (event: MouseEvent) => {
    const [mx, my] = d3.pointer(event, rootG!.node()!)
    line.attr('x2', mx).attr('y2', my)
  })
}

function cancelPendingEdge() {
  pendingSource = null
  rootG?.select('.rubber-band').remove()
  svg?.on('mousemove.edgemode', null)
}

// ─── view controls ───────────────────────────────────────────────────

function zoomBy(factor: number) {
  if (!svg || !zoomBehavior) return
  svg.transition().duration(180).call(zoomBehavior.scaleBy, factor)
}

/** Frame the whole network with a margin; a no-op on an empty canvas. */
function fitToView() {
  if (!svg || !rootG || !zoomBehavior || !wrapEl.value) return
  const nodes = Object.values(props.nodes)
  if (nodes.length === 0) return

  const pad = 60
  const xs = nodes.map(n => n.x)
  const ys = nodes.map(n => n.y)
  const minX = Math.min(...xs) - pad
  const maxX = Math.max(...xs) + pad
  const minY = Math.min(...ys) - pad
  const maxY = Math.max(...ys) + pad

  const w = wrapEl.value.clientWidth
  const h = wrapEl.value.clientHeight
  const scale = Math.min(4, Math.max(0.2, Math.min(w / (maxX - minX), h / (maxY - minY))))
  const tx = w / 2 - scale * (minX + maxX) / 2
  const ty = h / 2 - scale * (minY + maxY) / 2

  svg.transition().duration(300).call(
    zoomBehavior.transform,
    d3.zoomIdentity.translate(tx, ty).scale(scale),
  )
}

defineExpose({ fitToView, svgElement: () => svgEl.value })

// ─── lifecycle ───────────────────────────────────────────────────────

onMounted(() => {
  initSvg()
  if (wrapEl.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => syncSize())
    resizeObserver.observe(wrapEl.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  svg?.on('.zoom', null)
  svg?.on('mousemove.edgemode', null)
  svg?.selectAll('*').remove()
  svg = null
})

watch(() => [props.nodes, props.edges, props.selected], render, { deep: true })

watch(() => props.edgeMode, (on) => {
  if (!on) cancelPendingEdge()
  render()
})
</script>

<style scoped>
.canvas-wrap {
  position: relative;
  flex: 1;
  min-height: 320px;
  background: #0f172a;
  background-image:
    radial-gradient(circle at 1px 1px, rgba(148, 163, 184, 0.14) 1px, transparent 0);
  background-size: 28px 28px;
  border-radius: 8px;
  overflow: hidden;
}
.canvas-wrap.edge-mode { cursor: crosshair; }

.network-canvas { display: block; width: 100%; height: 100%; }

.canvas-hint,
.edge-mode-hint {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  pointer-events: none;
  font-size: 0.85rem;
}
.canvas-hint {
  top: 50%;
  transform: translate(-50%, -50%);
  color: #64748b;
  text-align: center;
  max-width: 320px;
  line-height: 1.6;
}
.edge-mode-hint {
  top: 12px;
  color: #dbeafe;
  background: rgba(59, 130, 246, 0.22);
  border: 1px solid rgba(59, 130, 246, 0.5);
  border-radius: 999px;
  padding: 0.35rem 0.9rem;
  white-space: nowrap;
}
.edge-mode-hint kbd {
  background: rgba(15, 23, 42, 0.6);
  border-radius: 3px;
  padding: 0 0.3rem;
  font-size: 0.75rem;
}

.canvas-toolbar {
  position: absolute;
  right: 10px;
  bottom: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.canvas-btn {
  width: 28px;
  height: 28px;
  border: 1px solid #334155;
  background: rgba(15, 23, 42, 0.85);
  color: #cbd5e1;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.85rem;
  line-height: 1;
}
.canvas-btn:hover { background: #1e293b; color: #fff; }

/* D3-managed elements are outside the scoped-style compiler's reach, so these
   selectors are deep-scoped rather than attribute-scoped. */
:deep(.edge-line) {
  stroke: #94a3b8;
  stroke-width: 1.8;
  transition: stroke 0.15s;
}
:deep(.edge-line.selected) { stroke: #3b82f6; stroke-width: 3; }
:deep(.edge-hit) { stroke: transparent; stroke-width: 14; cursor: pointer; }
:deep(.edge-label) {
  fill: #94a3b8;
  font-size: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  text-anchor: middle;
  pointer-events: none;
}
:deep(.edge-label.selected) { fill: #93c5fd; }

:deep(.node-group) { cursor: pointer; }
:deep(.node-halo) { opacity: 0.16; pointer-events: none; }
:deep(.node-circle) {
  stroke: rgba(15, 23, 42, 0.8);
  stroke-width: 2;
  transition: stroke 0.15s;
}
:deep(.node-circle.selected) { stroke: #fff; stroke-width: 3; }
:deep(.node-circle.edge-source) { stroke: #3b82f6; stroke-width: 4; }
:deep(.node-label) {
  fill: #e2e8f0;
  font-size: 11px;
  font-weight: 600;
  text-anchor: middle;
  pointer-events: none;
}
:deep(.node-value) {
  fill: rgba(15, 23, 42, 0.85);
  font-size: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  text-anchor: middle;
  pointer-events: none;
}
:deep(.rubber-band) {
  stroke: #3b82f6;
  stroke-width: 2;
  stroke-dasharray: 6 4;
}
</style>
