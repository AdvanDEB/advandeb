<template>
  <div ref="wrap" class="wiki-graph" @keydown.esc="select(null)">
    <canvas
      ref="canvas"
      :class="{ grabbing: drag !== null, pointer: hoverId !== null && drag === null }"
      role="img"
      tabindex="0"
      :aria-label="`${ui.graph}: ${ui.shown(visibleIds.length, graph.nodes.length)}`"
      @pointerdown="onDown"
      @pointermove="onMove"
      @pointerup="onUp"
      @pointercancel="onUp"
      @pointerleave="onLeave"
      @wheel.prevent="onWheel"
      @dblclick="onDblClick"
    />

    <div class="toolbar">
      <div class="seg" role="group" :aria-label="ui.view">
        <button type="button" :aria-pressed="mode === 2" @click="setMode(2)">2D</button>
        <button type="button" :aria-pressed="mode === 3" @click="setMode(3)">3D</button>
      </div>
      <div class="find">
        <input
          v-model="findText"
          type="search"
          :placeholder="ui.findNode"
          :aria-label="ui.findNode"
          @keydown.enter.prevent="matches[0] && focusNode(matches[0].id)"
        >
        <ul v-if="matches.length" class="matches">
          <li v-for="m in matches" :key="m.id">
            <button type="button" @click="focusNode(m.id)">
              <span class="sw" :style="{ background: color(m.section) }" />{{ titles[m.id] ?? m.id }}
            </button>
          </li>
        </ul>
      </div>
      <button type="button" class="icon" :title="ui.fit" :aria-label="ui.fit" @click="fit()">⤢</button>
      <button
        type="button"
        class="icon"
        :title="paused ? ui.resume : ui.pause"
        :aria-label="paused ? ui.resume : ui.pause"
        @click="togglePause"
      >{{ paused ? '▶' : '❚❚' }}</button>
      <button type="button" class="icon" :title="ui.reheat" :aria-label="ui.reheat" @click="reheat">↻</button>
      <button
        type="button"
        class="icon"
        :title="ui.settings"
        :aria-label="ui.settings"
        :aria-pressed="settingsOpen"
        @click="settingsOpen = !settingsOpen"
      >⚙</button>
    </div>

    <aside v-if="settingsOpen" class="settings" :aria-label="ui.settings">
      <section>
        <h3>{{ ui.forces }}</h3>
        <label v-for="k in FORCE_KEYS" :key="k" class="slider">
          <span>{{ ui[k] }}</span>
          <input
            v-model.number="forces[k]"
            type="range"
            :min="FORCE_RANGES[k].min"
            :max="FORCE_RANGES[k].max"
            :step="FORCE_RANGES[k].step"
          >
          <output>{{ fmt(forces[k]) }}</output>
        </label>
        <button type="button" class="link" @click="resetForces">{{ ui.defaults }}</button>
      </section>

      <section>
        <h3>{{ ui.display }}</h3>
        <label v-for="k in DISPLAY_KEYS" :key="k" class="slider">
          <span>{{ ui[k] }}</span>
          <input
            v-model.number="display[k]"
            type="range"
            :min="DISPLAY_RANGES[k].min"
            :max="DISPLAY_RANGES[k].max"
            :step="DISPLAY_RANGES[k].step"
          >
          <output>{{ fmt(display[k]) }}</output>
        </label>
        <label v-if="mode === 3" class="check">
          <input v-model="autoRotate" type="checkbox"> {{ ui.autoRotate }}
        </label>
      </section>

      <section>
        <h3>{{ ui.filter }}</h3>
        <label v-for="s in sections" :key="s" class="check">
          <input type="checkbox" :checked="!hidden.includes(s)" @change="toggleSection(s)">
          <span class="sw" :style="{ background: color(s) }" />
          {{ sectionLabel(s, lang) }}
          <span class="n">{{ counts[s] }}</span>
        </label>
        <label class="check focus">
          <input v-model="focusOnly" type="checkbox" :disabled="!selectedId"> {{ ui.focus }}
        </label>
        <label v-if="focusOnly && selectedId" class="slider">
          <span>{{ ui.depth }}</span>
          <input v-model.number="depth" type="range" min="1" max="3" step="1">
          <output>{{ depth }}</output>
        </label>
      </section>
    </aside>

    <div v-if="selected" class="card">
      <button type="button" class="close" :aria-label="ui.deselect" :title="ui.deselect" @click="select(null)">✕</button>
      <p class="sec"><span class="sw" :style="{ background: color(selected.section) }" />{{ sectionLabel(selected.section, lang) }}</p>
      <h3>{{ titles[selected.id] ?? selected.id }}</h3>
      <p class="muted">{{ ui.links(selected.degree) }}</p>
      <button type="button" class="primary" @click="emit('open', selected.id)">{{ ui.openNote }} →</button>
      <template v-if="neighbours.length">
        <h4>{{ ui.neighbours }}</h4>
        <ul>
          <li v-for="n in neighbours" :key="n.id">
            <button type="button" @click="focusNode(n.id)">
              <span class="sw" :style="{ background: color(n.section) }" />{{ titles[n.id] ?? n.id }}
            </button>
          </li>
        </ul>
      </template>
    </div>

    <p class="hint">{{ mode === 3 ? ui.graph3d : ui.graph2d }} · {{ ui.shown(visibleIds.length, graph.nodes.length) }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { WikiGraph, WikiLang } from '@/utils/wikiApi'
import { SECTION_COLOR, UI, fold, sectionLabel } from '@/utils/wikiText'
import {
  DEFAULT_FORCES, FORCE_RANGES, ForceSim, type Dims, type ForceParams, type SimNode,
} from '@/utils/wikiForce'

const props = defineProps<{
  graph: WikiGraph
  lang: WikiLang
  /** id → title in the current language */
  titles: Record<string, string>
}>()
const emit = defineEmits<{ open: [id: string] }>()
const ui = computed(() => UI[props.lang])

// --- settings, remembered per browser --------------------------------------- //

const FORCE_KEYS = Object.keys(DEFAULT_FORCES) as (keyof ForceParams)[]
const DEFAULT_DISPLAY = { nodeSize: 1, labelCount: 24, linkOpacity: 0.35 }
type DisplayKey = keyof typeof DEFAULT_DISPLAY
const DISPLAY_KEYS = Object.keys(DEFAULT_DISPLAY) as DisplayKey[]
const DISPLAY_RANGES: Record<DisplayKey, { min: number; max: number; step: number }> = {
  nodeSize: { min: 0.4, max: 2.5, step: 0.1 },
  labelCount: { min: 0, max: 100, step: 1 },
  linkOpacity: { min: 0, max: 1, step: 0.05 },
}
const STORE_KEY = 'wiki.graph.v1'
const reducedMotion = typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

function readSaved(): Record<string, unknown> {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) ?? '{}') ?? {} } catch { return {} }
}
function numbers<K extends string>(src: unknown, keys: K[], ranges: Record<K, { min: number; max: number }>) {
  const out: Partial<Record<K, number>> = {}
  if (src && typeof src === 'object') {
    for (const k of keys) {
      const v = (src as Record<string, unknown>)[k]
      if (typeof v === 'number' && v >= ranges[k].min && v <= ranges[k].max) out[k] = v
    }
  }
  return out
}
const saved = readSaved()
const mode = ref<Dims>(saved.mode === 3 ? 3 : 2)
const forces = reactive<ForceParams>({ ...DEFAULT_FORCES, ...numbers(saved.forces, FORCE_KEYS, FORCE_RANGES) })
const display = reactive({ ...DEFAULT_DISPLAY, ...numbers(saved.display, DISPLAY_KEYS, DISPLAY_RANGES) })
// The journal links to everything that happened that day: a hub that knots
// the picture together, so it starts hidden.
const hidden = ref<string[]>(Array.isArray(saved.hidden) ? (saved.hidden as string[]) : ['journal'])
const autoRotate = ref(typeof saved.autoRotate === 'boolean' ? saved.autoRotate : !reducedMotion)
// Open by default where there is room beside the graph; on a phone it would cover half of it.
const settingsOpen = ref(typeof saved.settingsOpen === 'boolean'
  ? saved.settingsOpen
  : typeof window === 'undefined' || window.innerWidth > 900)

watch([mode, forces, display, hidden, autoRotate, settingsOpen], () => {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      mode: mode.value, forces, display, hidden: hidden.value,
      autoRotate: autoRotate.value, settingsOpen: settingsOpen.value,
    }))
  } catch { /* storage blocked: settings just do not persist */ }
}, { deep: true })

function fmt(v: number) {
  return Number.isInteger(v) ? String(v) : v.toFixed(v < 1 ? 2 : 1)
}

// --- the graph as data ------------------------------------------------------ //

const info = computed(() => new Map(props.graph.nodes.map(n => [n.id, n])))
const adjacency = computed(() => {
  const m = new Map<string, Set<string>>()
  for (const n of props.graph.nodes) m.set(n.id, new Set())
  for (const [a, b] of props.graph.edges) {
    m.get(a)?.add(b)
    m.get(b)?.add(a)
  }
  return m
})
const counts = computed(() => {
  const c: Record<string, number> = {}
  for (const n of props.graph.nodes) c[n.section] = (c[n.section] ?? 0) + 1
  return c
})
const sections = computed(() => Object.keys(counts.value).sort((a, b) => counts.value[b] - counts.value[a]))
const color = (section: string) => SECTION_COLOR[section] ?? '#9ca3af'

const selectedId = ref<string | null>(null)
const hoverId = ref<string | null>(null)
const focusOnly = ref(false)
const depth = ref(1)
const paused = ref(false)
const findText = ref('')

const visibleIds = computed(() => {
  let ids = props.graph.nodes.filter(n => !hidden.value.includes(n.section)).map(n => n.id)
  const sel = selectedId.value
  if (focusOnly.value && sel) {
    const keep = new Set([sel])
    let frontier = [sel]
    for (let d = 0; d < depth.value; d++) {
      const next: string[] = []
      for (const id of frontier) {
        for (const nb of adjacency.value.get(id) ?? []) {
          if (!keep.has(nb)) { keep.add(nb); next.push(nb) }
        }
      }
      frontier = next
    }
    ids = ids.filter(id => keep.has(id))
    if (!ids.includes(sel)) ids.push(sel)
  }
  return ids
})

const selected = computed(() => (selectedId.value ? info.value.get(selectedId.value) ?? null : null))
const neighbours = computed(() => {
  if (!selectedId.value) return []
  return [...(adjacency.value.get(selectedId.value) ?? [])]
    .map(id => info.value.get(id)!)
    .filter(Boolean)
    .sort((a, b) => b.degree - a.degree)
    .slice(0, 24)
})
const matches = computed(() => {
  const q = fold(findText.value.trim())
  if (!q) return []
  return props.graph.nodes
    .filter(n => fold(props.titles[n.id] ?? n.id).includes(q))
    .sort((a, b) => b.degree - a.degree)
    .slice(0, 8)
})

// --- simulation --------------------------------------------------------------- //

let sim: ForceSim | null = null
let edges: [SimNode, SimNode][] = []
// The camera keeps the whole layout in frame while it settles, until the
// reader takes it over (zoom, pan, drag). Framing eases towards its target.
let follow = true
let snap = true
let frames = 0
let goal2: { k: number; x: number; y: number } | null = null
let goal3: { tx: number; ty: number; tz: number; dist: number } | null = null

function radiusFor(id: string) {
  return (3 + Math.sqrt(info.value.get(id)?.degree ?? 0) * 1.4) * display.nodeSize
}

function rebuild() {
  const ids = visibleIds.value
  const keep = new Set(ids)
  const start = sim?.positions() ?? new Map()
  sim = new ForceSim(
    ids.map(id => ({ id, group: info.value.get(id)?.section ?? 'other', radius: radiusFor(id) })),
    props.graph.edges.filter(([a, b]) => keep.has(a) && keep.has(b)),
    { ...forces },
    mode.value,
    start,
  )
  edges = props.graph.edges
    .filter(([a, b]) => keep.has(a) && keep.has(b))
    .map(([a, b]) => [sim!.byId.get(a)!, sim!.byId.get(b)!])
  if (start.size) {
    sim.alpha = 0.5
  } else {
    // Settle most of the way before the first frame, so the graph does not
    // open as an exploding spiral.
    for (let i = 0; i < 160; i++) sim.tick()
    follow = true
    snap = true
  }
  kick()
}

watch(() => props.graph, () => { sim = null; rebuild() })
watch(visibleIds, (now, before) => {
  if (now.length !== before.length || now.some((id, i) => id !== before[i])) rebuild()
})
watch(forces, () => { sim?.setParams({ ...forces }); kick() })
watch(() => display.nodeSize, () => {
  if (!sim) return
  for (const n of sim.nodes) n.radius = radiusFor(n.id)
  sim.reheat(0.2)
  kick()
})
watch([() => display.labelCount, () => display.linkOpacity, () => props.titles, autoRotate], () => kick())

function setMode(d: Dims) {
  if (d === mode.value || !sim) return
  mode.value = d
  sim.setDims(d)
  for (let i = 0; i < 80; i++) sim.tick()
  follow = true
  aim()
  kick()
}
function resetForces() {
  Object.assign(forces, DEFAULT_FORCES)
}
function togglePause() {
  paused.value = !paused.value
  kick()
}
function reheat() {
  paused.value = false
  sim?.reheat(1)
  kick()
}
function toggleSection(s: string) {
  hidden.value = hidden.value.includes(s) ? hidden.value.filter(x => x !== s) : [...hidden.value, s]
}

// --- camera and drawing ------------------------------------------------------- //

const wrap = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
let ctx: CanvasRenderingContext2D | null = null
let W = 0
let H = 0
let dpr = 1
const cam2 = { k: 1, x: 0, y: 0 }
const cam3 = { yaw: 0.7, pitch: -0.35, dist: 900, tx: 0, ty: 0, tz: 0 }
const palette = { bg: '#f9fafb', ink: '#374151', line: '#9ca3af', accent: '#2563eb', ring: '#ffffff' }

/** Middle of the part of the canvas the settings panel does not cover. */
function centre() {
  if (!settingsOpen.value) return { cx: W / 2, cy: H / 2, w: W, h: H }
  if (W > 760) return { cx: (W - 284) / 2, cy: H / 2, w: W - 284, h: H } // panel on the right
  const below = H * 0.5 + 12 // panel along the bottom (max-height: 50%)
  return { cx: W / 2, cy: (H - below) / 2, w: W, h: H - below }
}
watch(settingsOpen, () => { if (follow) aim(); kick() })

interface Projected {
  n: SimNode
  sx: number
  sy: number
  sr: number
  depth: number
  visible: boolean
}
let projected: Projected[] = []
let byNode = new Map<SimNode, Projected>()

function project() {
  if (!sim) return
  projected = []
  byNode = new Map()
  if (mode.value === 2) {
    for (const n of sim.nodes) {
      const p = { n, sx: n.x * cam2.k + cam2.x, sy: n.y * cam2.k + cam2.y, sr: Math.max(1.5, n.radius * cam2.k), depth: 0, visible: true }
      projected.push(p)
      byNode.set(n, p)
    }
    return
  }
  const { cx: ox, cy: oy, w, h } = centre()
  const F = Math.min(w, h)
  const cy = Math.cos(cam3.yaw)
  const sy = Math.sin(cam3.yaw)
  const cp = Math.cos(cam3.pitch)
  const sp = Math.sin(cam3.pitch)
  for (const n of sim.nodes) {
    const x = n.x - cam3.tx
    const y = n.y - cam3.ty
    const z = n.z - cam3.tz
    const x1 = x * cy - z * sy
    const z1 = x * sy + z * cy
    const y2 = y * cp - z1 * sp
    const z2 = y * sp + z1 * cp
    const zc = cam3.dist + z2
    const s = zc > 1 ? F / zc : 0
    const p = { n, sx: ox + x1 * s, sy: oy + y2 * s, sr: Math.max(1.2, n.radius * s), depth: zc, visible: s > 0 }
    projected.push(p)
    byNode.set(n, p)
  }
}

/** Where the camera should be to show the whole layout. */
function aim() {
  if (!sim || !W || !H || !sim.nodes.length) return
  if (mode.value === 2) {
    let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity
    for (const n of sim.nodes) {
      x0 = Math.min(x0, n.x - n.radius); x1 = Math.max(x1, n.x + n.radius)
      y0 = Math.min(y0, n.y - n.radius); y1 = Math.max(y1, n.y + n.radius)
    }
    const pad = 60
    const { cx, cy, w, h } = centre()
    const k = Math.min(4, Math.max(0.05, Math.min((w - pad * 2) / Math.max(x1 - x0, 1), (h - pad * 2) / Math.max(y1 - y0, 1))))
    goal2 = { k, x: cx - ((x0 + x1) / 2) * k, y: cy - ((y0 + y1) / 2) * k }
  } else {
    let tx = 0; let ty = 0; let tz = 0
    for (const n of sim.nodes) { tx += n.x; ty += n.y; tz += n.z }
    const N = sim.nodes.length
    tx /= N; ty /= N; tz /= N
    // Nearly every note within the sphere's radius, not the single furthest.
    const d = sim.nodes.map(n => Math.hypot(n.x - tx, n.y - ty, n.z - tz)).sort((a, b) => a - b)
    const R = Math.max(1, d[Math.floor(d.length * 0.95)] ?? 1)
    goal3 = { tx, ty, tz, dist: R * 2.5 }
  }
}

/** Frame the whole layout (the toolbar button), easing there. */
function fit() {
  aim()
  kick()
}

/** Move the camera a step towards its goal; true while still moving. */
function ease(): boolean {
  const t = snap ? 1 : 0.18
  snap = false
  let moving = false
  if (mode.value === 2 && goal2) {
    cam2.k += (goal2.k - cam2.k) * t
    cam2.x += (goal2.x - cam2.x) * t
    cam2.y += (goal2.y - cam2.y) * t
    if (Math.abs(goal2.k - cam2.k) < 1e-3 * goal2.k && Math.abs(goal2.x - cam2.x) < 0.5 && Math.abs(goal2.y - cam2.y) < 0.5) goal2 = null
    else moving = true
  }
  if (mode.value === 3 && goal3) {
    cam3.tx += (goal3.tx - cam3.tx) * t
    cam3.ty += (goal3.ty - cam3.ty) * t
    cam3.tz += (goal3.tz - cam3.tz) * t
    cam3.dist += (goal3.dist - cam3.dist) * t
    if (Math.abs(goal3.dist - cam3.dist) < 0.5 && Math.hypot(goal3.tx - cam3.tx, goal3.ty - cam3.ty, goal3.tz - cam3.tz) < 0.5) goal3 = null
    else moving = true
  }
  return moving
}

/** The reader moved the camera: stop framing for them. */
function takeCamera() {
  follow = false
  goal2 = null
  goal3 = null
}

function labelSet(): Set<string> {
  const out = new Set<string>()
  if (!sim) return out
  const ranked = [...sim.nodes].sort((a, b) => (info.value.get(b.id)?.degree ?? 0) - (info.value.get(a.id)?.degree ?? 0))
  for (const n of ranked.slice(0, display.labelCount)) out.add(n.id)
  const focus = hoverId.value ?? selectedId.value
  if (focus) {
    out.add(focus)
    for (const nb of adjacency.value.get(focus) ?? []) out.add(nb)
  }
  if (selectedId.value) out.add(selectedId.value)
  return out
}

function draw() {
  if (!ctx || !sim) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.fillStyle = palette.bg
  ctx.fillRect(0, 0, W, H)
  project()

  const focus = hoverId.value ?? selectedId.value
  const near = focus ? adjacency.value.get(focus) ?? new Set<string>() : null
  const lit = (id: string) => !near || id === focus || near.has(id)
  const three = mode.value === 3

  // Depth cue: far things fade (3D only).
  let dMin = Infinity
  let dMax = -Infinity
  if (three) for (const p of projected) if (p.visible) { dMin = Math.min(dMin, p.depth); dMax = Math.max(dMax, p.depth) }
  const fog = (d: number) => (three && dMax > dMin ? 1 - 0.65 * ((d - dMin) / (dMax - dMin)) : 1)

  // Links: the quiet ones in one batch, then the ones touching the focus on top.
  const base = display.linkOpacity
  if (base > 0) {
    ctx.lineWidth = 1
    ctx.strokeStyle = palette.line
    if (!three) {
      ctx.globalAlpha = near ? base * 0.25 : base
      ctx.beginPath()
      for (const [a, b] of edges) {
        if (near && (a.id === focus || b.id === focus)) continue
        const pa = byNode.get(a)!
        const pb = byNode.get(b)!
        ctx.moveTo(pa.sx, pa.sy)
        ctx.lineTo(pb.sx, pb.sy)
      }
      ctx.stroke()
    } else {
      for (const [a, b] of edges) {
        if (near && (a.id === focus || b.id === focus)) continue
        const pa = byNode.get(a)!
        const pb = byNode.get(b)!
        if (!pa.visible || !pb.visible) continue
        ctx.globalAlpha = base * fog((pa.depth + pb.depth) / 2) * (near ? 0.25 : 1)
        ctx.beginPath()
        ctx.moveTo(pa.sx, pa.sy)
        ctx.lineTo(pb.sx, pb.sy)
        ctx.stroke()
      }
    }
  }
  if (focus) {
    ctx.globalAlpha = 0.85
    ctx.strokeStyle = palette.accent
    ctx.lineWidth = 1.6
    ctx.beginPath()
    for (const [a, b] of edges) {
      if (a.id !== focus && b.id !== focus) continue
      const pa = byNode.get(a)!
      const pb = byNode.get(b)!
      if (!pa.visible || !pb.visible) continue
      ctx.moveTo(pa.sx, pa.sy)
      ctx.lineTo(pb.sx, pb.sy)
    }
    ctx.stroke()
  }

  // Nodes: far ones first in 3D, small ones first in 2D (hubs stay on top).
  const order = projected.filter(p => p.visible)
  if (three) order.sort((a, b) => b.depth - a.depth)
  else order.sort((a, b) => a.n.radius - b.n.radius)
  for (const p of order) {
    const on = lit(p.n.id)
    ctx.globalAlpha = (on ? 1 : 0.14) * fog(p.depth)
    ctx.beginPath()
    ctx.arc(p.sx, p.sy, p.sr, 0, Math.PI * 2)
    ctx.fillStyle = color(p.n.group)
    ctx.fill()
    ctx.lineWidth = p.n.id === selectedId.value ? 3 : 1.2
    ctx.strokeStyle = p.n.id === selectedId.value ? palette.ink : palette.ring
    ctx.stroke()
  }

  // Labels, nearest and most important first, skipping any that would overlap.
  const want = labelSet()
  const placed: [number, number, number, number][] = []
  const labelled = order.filter(p => want.has(p.n.id)).reverse()
  const priority = (id: string) => (id === focus || id === selectedId.value ? 2 : near?.has(id) ? 1 : 0)
  labelled.sort((a, b) => priority(b.n.id) - priority(a.n.id))
  ctx.textBaseline = 'middle'
  ctx.lineJoin = 'round'
  for (const p of labelled) {
    const text = props.titles[p.n.id] ?? p.n.id
    const strong = priority(p.n.id) === 2
    ctx.font = `${strong ? 600 : 400} ${strong ? 13 : 11}px ui-sans-serif, system-ui, sans-serif`
    const w = ctx.measureText(text).width
    const x = p.sx + p.sr + 4
    const y = p.sy
    const box: [number, number, number, number] = [x - 2, y - 8, x + w + 2, y + 8]
    if (!strong && placed.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) continue
    placed.push(box)
    ctx.globalAlpha = (lit(p.n.id) ? 1 : 0.3) * Math.max(0.45, fog(p.depth))
    ctx.lineWidth = 3
    ctx.strokeStyle = palette.bg
    ctx.strokeText(text, x, y)
    ctx.fillStyle = palette.ink
    ctx.fillText(text, x, y)
  }
  ctx.globalAlpha = 1
}

// --- the frame loop ------------------------------------------------------------ //

let raf = 0
function kick() {
  if (!raf && ctx) raf = requestAnimationFrame(frame)
}
function frame() {
  raf = 0
  if (!sim) return
  const simulate = !paused.value && sim.running
  if (simulate) {
    sim.tick()
    if (sim.nodes.length < 500) sim.tick()
  }
  // Hold the rotation while the pointer is on a note, so it can be clicked.
  const spin = mode.value === 3 && autoRotate.value && drag.value === null && hoverId.value === null
  if (spin) cam3.yaw += 0.0022
  frames++
  if (follow && W && H && (snap || (simulate && frames % 6 === 0))) aim()
  const moving = ease()
  draw()
  if (simulate || spin || moving || drag.value !== null) kick()
}

// --- pointer ---------------------------------------------------------------------- //

interface Drag {
  kind: 'node' | 'pan' | 'rotate'
  node: SimNode | null
  hit: string | null
  x: number
  y: number
  moved: boolean
}
const drag = ref<Drag | null>(null)

function at(e: PointerEvent | MouseEvent | WheelEvent) {
  const r = canvas.value!.getBoundingClientRect()
  return { x: e.clientX - r.left, y: e.clientY - r.top }
}

function pick(x: number, y: number): SimNode | null {
  let best: Projected | null = null
  for (const p of projected) {
    if (!p.visible) continue
    const d = Math.hypot(p.sx - x, p.sy - y)
    if (d > p.sr + 4) continue
    if (!best || (mode.value === 3 ? p.depth < best.depth : p.n.radius >= best.n.radius)) best = p
  }
  return best?.n ?? null
}

function onDown(e: PointerEvent) {
  if (!sim || e.button !== 0) return
  canvas.value?.setPointerCapture(e.pointerId)
  const { x, y } = at(e)
  const hit = pick(x, y)
  if (hit && mode.value === 2) {
    takeCamera()
    hit.fx = hit.x
    hit.fy = hit.y
    sim.alphaTarget = 0.25
    sim.reheat(0.25)
    drag.value = { kind: 'node', node: hit, hit: hit.id, x, y, moved: false }
  } else {
    drag.value = { kind: mode.value === 2 ? 'pan' : 'rotate', node: null, hit: hit?.id ?? null, x, y, moved: false }
  }
  kick()
}

function onMove(e: PointerEvent) {
  const { x, y } = at(e)
  const d = drag.value
  if (!d) {
    const h = pick(x, y)?.id ?? null
    if (h !== hoverId.value) {
      hoverId.value = h
      kick()
    }
    return
  }
  const dx = x - d.x
  const dy = y - d.y
  if (!d.moved && Math.hypot(dx, dy) < 4) return
  d.moved = true
  d.x = x
  d.y = y
  if (d.kind === 'node' && d.node) {
    d.node.fx = (x - cam2.x) / cam2.k
    d.node.fy = (y - cam2.y) / cam2.k
  } else if (d.kind === 'pan') {
    takeCamera()
    cam2.x += dx
    cam2.y += dy
  } else {
    cam3.yaw += dx * 0.008
    cam3.pitch = Math.max(-1.5, Math.min(1.5, cam3.pitch + dy * 0.008))
  }
  kick()
}

function onUp(e: PointerEvent) {
  const d = drag.value
  if (!d) return
  canvas.value?.releasePointerCapture?.(e.pointerId)
  if (d.node) {
    d.node.fx = null
    d.node.fy = null
  }
  if (sim) sim.alphaTarget = 0
  if (!d.moved) select(d.hit)
  drag.value = null
  kick()
}

function onLeave() {
  if (hoverId.value !== null && !drag.value) {
    hoverId.value = null
    kick()
  }
}

function onWheel(e: WheelEvent) {
  takeCamera()
  const f = Math.exp(-e.deltaY * 0.0015)
  if (mode.value === 2) {
    const { x, y } = at(e)
    const k = Math.min(6, Math.max(0.03, cam2.k * f))
    cam2.x = x - ((x - cam2.x) * k) / cam2.k
    cam2.y = y - ((y - cam2.y) * k) / cam2.k
    cam2.k = k
  } else {
    cam3.dist = Math.min(20000, Math.max(30, cam3.dist / f))
  }
  kick()
}

function onDblClick(e: MouseEvent) {
  const { x, y } = at(e)
  const hit = pick(x, y)
  if (hit) emit('open', hit.id)
}

function select(id: string | null) {
  selectedId.value = id
  if (!id) focusOnly.value = false
  kick()
}

/** Select a note and bring it to the middle, showing its section if hidden. */
function focusNode(id: string) {
  const section = info.value.get(id)?.section
  if (section && hidden.value.includes(section)) hidden.value = hidden.value.filter(s => s !== section)
  findText.value = ''
  takeCamera()
  select(id)
  // The layout may be rebuilt by the line above; centre on the next frame.
  requestAnimationFrame(() => {
    const n = sim?.byId.get(id)
    if (!n) return
    if (mode.value === 2) {
      const { cx, cy } = centre()
      cam2.x = cx - n.x * cam2.k
      cam2.y = cy - n.y * cam2.k
    } else {
      cam3.tx = n.x; cam3.ty = n.y; cam3.tz = n.z
    }
    kick()
  })
}

// --- lifecycle ---------------------------------------------------------------------- //

let observer: ResizeObserver | null = null

function resize() {
  const el = wrap.value
  const c = canvas.value
  if (!el || !c) return
  dpr = window.devicePixelRatio || 1
  W = el.clientWidth
  H = el.clientHeight
  c.width = Math.round(W * dpr)
  c.height = Math.round(H * dpr)
  if (follow) aim()
  kick()
}

onMounted(() => {
  ctx = canvas.value?.getContext('2d') ?? null
  const css = getComputedStyle(wrap.value!)
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  palette.bg = v('--app-bg-2', palette.bg)
  palette.ink = v('--app-ink-2', palette.ink)
  palette.line = v('--app-ink-4', palette.line)
  palette.accent = v('--app-primary-strong', palette.accent)
  palette.ring = v('--app-bg', palette.ring)
  resize()
  observer = new ResizeObserver(resize)
  if (wrap.value) observer.observe(wrap.value)
  rebuild()
})

onBeforeUnmount(() => {
  if (raf) cancelAnimationFrame(raf)
  observer?.disconnect()
})
</script>

<style scoped>
.wiki-graph {
  position: relative;
  flex: 1;
  min-height: 420px;
  overflow: hidden;
  background: var(--app-bg-2);
}

canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
  cursor: grab;
  touch-action: none;
}
canvas.pointer { cursor: pointer; }
canvas.grabbing { cursor: grabbing; }
canvas:focus-visible { outline: 2px solid var(--app-primary-line); outline-offset: -2px; }

.toolbar {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 2;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 6px;
  max-width: calc(100% - 24px);
}
.toolbar > *, .settings, .card {
  background: var(--app-bg);
  border: 1px solid var(--app-line);
  border-radius: var(--app-radius-lg);
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
}
.seg { display: inline-flex; overflow: hidden; }
.seg button {
  border: 0; background: none; padding: 6px 12px; font-size: 0.8rem; font-weight: 700;
  color: var(--app-ink-3); cursor: pointer;
}
.seg button[aria-pressed="true"] { background: var(--app-ink); color: var(--app-bg); }
.icon {
  width: 32px; height: 32px; display: grid; place-items: center; padding: 0; cursor: pointer;
  color: var(--app-ink-2); font-size: 0.95rem;
}
.icon:hover, .seg button:hover:not([aria-pressed="true"]) { background: var(--app-bg-3); }
.icon[aria-pressed="true"] { background: var(--app-primary-soft); color: var(--app-primary-ink); }

.find { position: relative; }
.find input {
  width: 220px; border: 0; background: none; padding: 7px 10px; font: inherit; font-size: 0.83rem;
  border-radius: var(--app-radius-lg);
}
.find input:focus { outline: 2px solid var(--app-primary-line); }
.matches {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0; list-style: none; margin: 0; padding: 4px;
  background: var(--app-bg); border: 1px solid var(--app-line); border-radius: var(--app-radius-lg);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
}
.matches button, .card li button {
  display: flex; align-items: center; gap: 6px; width: 100%; padding: 4px 6px; border: 0; background: none;
  text-align: left; font: inherit; font-size: 0.8rem; color: var(--app-ink-2); cursor: pointer;
  border-radius: var(--app-radius);
}
.matches button:hover, .card li button:hover { background: var(--app-bg-3); color: var(--app-ink); }

.sw { flex-shrink: 0; width: 9px; height: 9px; border-radius: 50%; display: inline-block; }

.settings {
  position: absolute;
  top: 12px;
  right: 12px;
  bottom: 12px;
  z-index: 2;
  width: 260px;
  overflow-y: auto;
  padding: 4px 14px 12px;
  font-size: 0.8rem;
}
.settings section { padding: 10px 0; border-bottom: 1px solid var(--app-line); }
.settings section:last-child { border-bottom: 0; }
.settings h3 {
  margin: 0 0 8px; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--app-ink-3);
}
.slider { display: grid; grid-template-columns: 1fr auto; gap: 0 8px; align-items: center; margin-bottom: 6px; }
.slider span { color: var(--app-ink-2); }
.slider output { font-variant-numeric: tabular-nums; color: var(--app-ink-3); font-size: 0.75rem; }
.slider input { grid-column: 1 / -1; width: 100%; accent-color: var(--app-primary-strong); margin: 2px 0 0; }
.check { display: flex; align-items: center; gap: 6px; padding: 2px 0; color: var(--app-ink-2); cursor: pointer; }
.check .n { margin-left: auto; color: var(--app-ink-4); font-variant-numeric: tabular-nums; }
.check.focus { margin-top: 8px; }
.check input:disabled + * { opacity: 0.5; }
.link {
  border: 0; background: none; padding: 0; margin-top: 2px; font: inherit; font-size: 0.78rem;
  color: var(--app-primary-strong); cursor: pointer;
}
.link:hover { text-decoration: underline; }

.card {
  position: absolute;
  left: 12px;
  bottom: 40px;
  z-index: 2;
  width: 280px;
  max-height: min(52%, calc(100% - 120px));
  overflow-y: auto;
  padding: 12px 14px;
  font-size: 0.83rem;
}
.card .close {
  position: absolute; top: 6px; right: 6px; border: 0; background: none; color: var(--app-ink-3);
  cursor: pointer; font-size: 0.9rem; padding: 4px;
}
.card .sec { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 0.72rem; color: var(--app-ink-3); }
.card h3 { margin: 4px 24px 2px 0; font-size: 1rem; line-height: 1.3; color: var(--app-ink); }
.card .muted { margin: 0 0 8px; color: var(--app-ink-3); font-size: 0.75rem; }
.card .primary {
  border: 0; border-radius: var(--app-radius); background: var(--app-primary-strong); color: #fff;
  padding: 6px 12px; font: inherit; font-size: 0.8rem; font-weight: 600; cursor: pointer;
}
.card .primary:hover { background: var(--app-primary-ink); }
.card h4 {
  margin: 12px 0 4px; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--app-ink-3);
}
.card ul { list-style: none; margin: 0; padding: 0; }

.hint {
  position: absolute; left: 12px; bottom: 8px; z-index: 1; margin: 0; max-width: calc(100% - 300px);
  font-size: 0.72rem; color: var(--app-ink-3); pointer-events: none;
}

@media (max-width: 760px) {
  .find input { width: 150px; }
  .settings { top: auto; left: 12px; width: auto; max-height: 50%; }
  .card { bottom: 12px; right: 12px; width: auto; max-height: 45%; }
  .hint { display: none; }
}
</style>
