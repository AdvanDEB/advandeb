<template>
  <div class="wiki-graph">
    <div class="panel">
      <p class="hint">{{ ui.graphHint }}</p>
      <label v-for="s in sections" :key="s" class="row">
        <input v-model="shown" type="checkbox" :value="s">
        <span class="sw" :style="{ background: SECTION_COLOR[s] }" />
        {{ sectionLabel(s, lang) }}
      </label>
      <label class="row labels">
        <input v-model="allLabels" type="checkbox">
        {{ ui.showLabels }}
      </label>
    </div>

    <svg
      ref="svgEl"
      :viewBox="`${view.x} ${view.y} ${view.w} ${view.h}`"
      role="img"
      :aria-label="ui.graph"
      @wheel.prevent="zoom"
      @pointerdown="startPan"
      @pointermove="pan"
      @pointerup="endPan"
      @pointerleave="endPan"
    >
      <g class="edges">
        <line
          v-for="(e, i) in visibleEdges"
          :key="i"
          :x1="e[0].x" :y1="e[0].y" :x2="e[1].x" :y2="e[1].y"
          :class="{ hi: hovered && (e[0].id === hovered || e[1].id === hovered) }"
        />
      </g>
      <g
        v-for="n in visibleNodes"
        :key="n.id"
        class="node"
        :class="{ dim: hovered && !neighbours.has(n.id) }"
        @click="emit('open', n.id)"
        @mouseenter="hovered = n.id"
        @mouseleave="hovered = null"
      >
        <circle :cx="n.x" :cy="n.y" :r="radius(n)" :fill="SECTION_COLOR[n.section] ?? '#9ca3af'">
          <title>{{ titles[n.id] }}</title>
        </circle>
        <text
          v-if="allLabels || n.degree >= labelDegree || hovered === n.id"
          :x="n.x + radius(n) + 3" :y="n.y + 4"
        >{{ titles[n.id] }}</text>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3'
import type { SimulationLinkDatum, SimulationNodeDatum } from 'd3'
import type { WikiGraph, WikiLang } from '@/utils/wikiApi'
import { SECTION_COLOR, UI, sectionLabel } from '@/utils/wikiText'

interface Node extends SimulationNodeDatum {
  id: string
  section: string
  degree: number
  x: number
  y: number
}

const props = defineProps<{
  graph: WikiGraph
  lang: WikiLang
  /** id → title in the current language */
  titles: Record<string, string>
}>()
const emit = defineEmits<{ open: [id: string] }>()

const ui = computed(() => UI[props.lang])
const nodes = shallowRef<Node[]>([])
const byId = computed(() => new Map(nodes.value.map(n => [n.id, n])))
const sections = computed(() => [...new Set(props.graph.nodes.map(n => n.section))])
// The journal links to everything that happened that day; it is a hub that
// pulls the picture together into one knot, so it starts hidden.
const shown = ref<string[]>([])
const allLabels = ref(false)
const hovered = ref<string | null>(null)
const view = ref({ x: -500, y: -400, w: 1000, h: 800 })
const svgEl = ref<SVGSVGElement | null>(null)

function layout(g: WikiGraph) {
  const ns: Node[] = g.nodes.map(n => ({ ...n, x: 0, y: 0 }))
  const links: SimulationLinkDatum<Node>[] = g.edges.map(([s, t]) => ({ source: s, target: t }))
  // Run to rest up front: 200 nodes settle in well under a frame budget's
  // worth of ticks, and a still picture is easier to read than a jiggling one.
  forceSimulation(ns)
    .force('link', forceLink<Node, SimulationLinkDatum<Node>>(links).id(d => d.id).distance(70).strength(0.25))
    .force('charge', forceManyBody<Node>().strength(-160))
    .force('collide', forceCollide<Node>().radius(d => radius(d) + 4))
    .force('x', forceX<Node>().strength(0.04))
    .force('y', forceY<Node>().strength(0.04))
    .stop()
    .tick(320)
  nodes.value = ns
  shown.value = sections.value.filter(s => s !== 'journal')
  fit()
}

function fit() {
  if (!nodes.value.length) return
  const xs = nodes.value.map(n => n.x)
  const ys = nodes.value.map(n => n.y)
  const pad = 60
  view.value = {
    x: Math.min(...xs) - pad, y: Math.min(...ys) - pad,
    w: Math.max(...xs) - Math.min(...xs) + 2 * pad, h: Math.max(...ys) - Math.min(...ys) + 2 * pad,
  }
}

watch(() => props.graph, layout, { immediate: true })

const visibleNodes = computed(() => nodes.value.filter(n => shown.value.includes(n.section)))
const visibleEdges = computed(() => {
  const on = new Set(visibleNodes.value.map(n => n.id))
  return props.graph.edges
    .filter(([a, b]) => on.has(a) && on.has(b))
    .map(([a, b]) => [byId.value.get(a)!, byId.value.get(b)!] as const)
})
const labelDegree = computed(() => {
  const d = visibleNodes.value.map(n => n.degree).sort((a, b) => b - a)
  return d[Math.min(24, d.length - 1)] ?? 0
})
const neighbours = computed(() => {
  const s = new Set<string>()
  if (!hovered.value) return s
  s.add(hovered.value)
  for (const [a, b] of props.graph.edges) {
    if (a === hovered.value) s.add(b)
    if (b === hovered.value) s.add(a)
  }
  return s
})

function radius(n: { degree: number }) {
  return 3 + Math.sqrt(n.degree) * 1.4
}

function scale() {
  const r = svgEl.value?.getBoundingClientRect()
  return r && r.width ? Math.max(view.value.w / r.width, view.value.h / r.height) : 1
}

function zoom(e: WheelEvent) {
  const r = svgEl.value?.getBoundingClientRect()
  if (!r) return
  const k = e.deltaY > 0 ? 1.12 : 1 / 1.12
  const s = scale()
  const mx = view.value.x + (e.clientX - r.left) * s
  const my = view.value.y + (e.clientY - r.top) * s
  view.value = { x: mx - (mx - view.value.x) * k, y: my - (my - view.value.y) * k, w: view.value.w * k, h: view.value.h * k }
}

let drag: { x: number; y: number; vx: number; vy: number } | null = null
function startPan(e: PointerEvent) {
  if ((e.target as Element).tagName !== 'svg') return
  drag = { x: e.clientX, y: e.clientY, vx: view.value.x, vy: view.value.y }
  svgEl.value?.setPointerCapture(e.pointerId)
}
function pan(e: PointerEvent) {
  if (!drag) return
  const s = scale()
  view.value = { ...view.value, x: drag.vx - (e.clientX - drag.x) * s, y: drag.vy - (e.clientY - drag.y) * s }
}
function endPan() {
  drag = null
}
</script>

<style scoped>
.wiki-graph {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
}

svg {
  flex: 1;
  width: 100%;
  height: 100%;
  min-height: 420px;
  cursor: grab;
  background: var(--app-bg-2);
}
svg:active { cursor: grabbing; }

.panel {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 1;
  max-width: 260px;
  padding: 10px 12px;
  background: var(--app-bg);
  border: 1px solid var(--app-line);
  border-radius: var(--app-radius-lg);
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
  font-size: 0.8rem;
}
.hint { margin: 0 0 8px; color: var(--app-ink-3); }
.row { display: flex; align-items: center; gap: 6px; padding: 1px 0; cursor: pointer; }
.row.labels { margin-top: 6px; }
.sw { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }

.edges line { stroke: var(--app-ink-4); stroke-opacity: 0.35; }
.edges line.hi { stroke: var(--app-primary-strong); stroke-opacity: 0.9; }
.node { cursor: pointer; }
.node circle { stroke: var(--app-bg); stroke-width: 1.5px; }
.node text {
  font-size: 11px;
  fill: var(--app-ink-2);
  pointer-events: none;
  paint-order: stroke;
  stroke: var(--app-bg-2);
  stroke-width: 3px;
}
.node.dim { opacity: 0.12; }
</style>
