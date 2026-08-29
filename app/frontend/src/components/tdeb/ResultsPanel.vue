<template>
  <div class="results">
    <p v-if="!result" class="results-empty">
      Run a simulation to see state trajectories, energy fluxes and the overall
      energy balance.
    </p>

    <template v-else>
      <section class="chart-section">
        <h3>Compartment states</h3>
        <div ref="statesEl" class="chart-box"></div>
      </section>

      <section class="chart-section">
        <h3>Energy fluxes</h3>
        <div ref="fluxesEl" class="chart-box"></div>
      </section>

      <section class="chart-section">
        <h3>Energy balance</h3>
        <div ref="sankeyEl" class="chart-box"></div>
        <p v-if="sankeyEmpty" class="chart-note">
          Not enough net forward flow to draw a Sankey diagram.
        </p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import Plotly from '@/utils/plotlyCore'
import type { SimulationResult, TDebEdge, TDebNode } from '@/utils/tdebApi'
import { PLOT_COLORS, nodeColor } from '@/utils/tdebConstants'

const props = defineProps<{
  result: SimulationResult | null
  nodes: Record<string, TDebNode>
  edges: Record<string, TDebEdge>
}>()

const statesEl = ref<HTMLElement | null>(null)
const fluxesEl = ref<HTMLElement | null>(null)
const sankeyEl = ref<HTMLElement | null>(null)
const sankeyEmpty = ref(false)

const PLOT_CONFIG = { responsive: true, displayModeBar: false }

function baseLayout(yTitle: string) {
  return {
    paper_bgcolor: '#ffffff',
    plot_bgcolor: '#ffffff',
    font: { family: 'system-ui, sans-serif', color: '#4b5563', size: 11 },
    margin: { l: 60, r: 20, t: 20, b: 45 },
    xaxis: { gridcolor: '#e5e7eb', zerolinecolor: '#e5e7eb', title: { text: 'Time [days]' } },
    yaxis: { gridcolor: '#e5e7eb', zerolinecolor: '#e5e7eb', title: { text: yTitle } },
    legend: { bgcolor: 'transparent', font: { size: 10 }, orientation: 'h' as const, y: -0.22 },
    hovermode: 'x unified' as const,
  }
}

function seriesTraces(
  time: number[], series: Record<string, number[]>, dashed: boolean,
) {
  return Object.entries(series).map(([label, values], i) => ({
    x: time,
    y: values,
    name: label,
    type: 'scatter',
    mode: 'lines',
    line: {
      color: PLOT_COLORS[i % PLOT_COLORS.length],
      width: dashed ? 1.5 : 2,
      ...(dashed ? { dash: 'dot' } : {}),
    },
  }))
}

async function drawStates(result: SimulationResult) {
  if (!statesEl.value) return
  await Plotly.react(
    statesEl.value,
    seriesTraces(result.time, result.states, false),
    baseLayout('Value [J or cm³]'),
    PLOT_CONFIG,
  )
}

async function drawFluxes(result: SimulationResult) {
  if (!fluxesEl.value) return
  await Plotly.react(
    fluxesEl.value,
    seriesTraces(result.time, result.fluxes, true),
    baseLayout('Flux [J/d]'),
    PLOT_CONFIG,
  )
}

/**
 * Sankey of mean forward flux per channel.
 *
 * Plotly rejects a Sankey whose links form a cycle, and a transport network can
 * legitimately contain one, so cycle-closing links are dropped and reported
 * rather than letting the chart fail to render.
 */
async function drawSankey(result: SimulationResult) {
  if (!sankeyEl.value) return

  const nodeIds = Object.keys(props.nodes)
  const indexOf = new Map(nodeIds.map((id, i) => [id, i]))
  const labels = nodeIds.map(id => props.nodes[id].name)
  const colors = nodeIds.map(id => nodeColor(props.nodes[id].node_type))

  const candidates: { s: number; t: number; v: number; label: string }[] = []

  for (const edge of Object.values(props.edges)) {
    const s = indexOf.get(edge.source_id)
    const t = indexOf.get(edge.target_id)
    if (s === undefined || t === undefined) continue

    // The backend disambiguates duplicate edge names with a " [id]" suffix.
    const values = result.fluxes[edge.name] ?? result.fluxes[`${edge.name} [${edge.id}]`]
    if (!values || values.length === 0) continue

    const mean = values.reduce((a, b) => a + b, 0) / values.length
    if (!Number.isFinite(mean) || mean <= 0) continue
    candidates.push({ s, t, v: mean, label: edge.name })
  }

  const links = dropCycles(candidates, nodeIds.length)

  if (links.length === 0) {
    sankeyEmpty.value = true
    Plotly.purge(sankeyEl.value)
    return
  }
  sankeyEmpty.value = false

  await Plotly.react(sankeyEl.value, [{
    type: 'sankey',
    orientation: 'h',
    node: {
      pad: 20,
      thickness: 18,
      line: { color: 'rgba(0,0,0,0.12)', width: 1 },
      label: labels,
      color: colors,
    },
    link: {
      source: links.map(l => l.s),
      target: links.map(l => l.t),
      value: links.map(l => l.v),
      label: links.map(l => l.label),
      color: 'rgba(59,130,246,0.25)',
    },
  }], {
    ...baseLayout(''),
    xaxis: undefined,
    yaxis: undefined,
    margin: { l: 10, r: 10, t: 10, b: 10 },
  }, PLOT_CONFIG)
}

/**
 * Keep links in descending flux order, skipping any that would close a cycle.
 * Largest flows win, so the dropped links are the least significant ones.
 */
function dropCycles(
  links: { s: number; t: number; v: number; label: string }[], nodeCount: number,
) {
  const adjacency: number[][] = Array.from({ length: nodeCount }, () => [])
  const kept: typeof links = []

  const reaches = (from: number, goal: number): boolean => {
    const seen = new Set<number>()
    const stack = [from]
    while (stack.length) {
      const cur = stack.pop()!
      if (cur === goal) return true
      if (seen.has(cur)) continue
      seen.add(cur)
      stack.push(...adjacency[cur])
    }
    return false
  }

  for (const link of [...links].sort((a, b) => b.v - a.v)) {
    if (link.s === link.t) continue
    if (reaches(link.t, link.s)) continue
    adjacency[link.s].push(link.t)
    kept.push(link)
  }
  return kept
}

async function redraw() {
  if (!props.result?.success) return
  await nextTick()
  await drawStates(props.result)
  await drawFluxes(props.result)
  await drawSankey(props.result)
}

/** Chart PNGs for the LaTeX export bundle; null when a chart has no data. */
async function toPng(el: HTMLElement | null, w: number, h: number): Promise<Blob | null> {
  if (!el || !(el as unknown as { data?: unknown[] }).data) return null
  try {
    const dataUrl = await Plotly.toImage(el, { format: 'png', width: w, height: h, scale: 2 })
    return await (await fetch(dataUrl)).blob()
  } catch {
    return null
  }
}

defineExpose({
  chartImages: async () => ({
    states: await toPng(statesEl.value, 900, 500),
    fluxes: await toPng(fluxesEl.value, 900, 500),
    sankey: await toPng(sankeyEl.value, 900, 500),
  }),
})

watch(() => props.result, redraw, { immediate: true })

onBeforeUnmount(() => {
  for (const el of [statesEl.value, fluxesEl.value, sankeyEl.value]) {
    if (el) Plotly.purge(el)
  }
})
</script>

<style scoped>
.results { display: flex; flex-direction: column; gap: 1.25rem; }
.results-empty {
  color: #6b7280;
  font-size: 0.85rem;
  line-height: 1.6;
  padding: 2rem 0.5rem;
  text-align: center;
}
.chart-section { display: flex; flex-direction: column; gap: 0.4rem; }
.chart-section h3 {
  font-size: 0.78rem;
  font-weight: 600;
  color: #374151;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 0;
}
.chart-box {
  width: 100%;
  height: 260px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}
.chart-note { font-size: 0.72rem; color: #6b7280; margin: 0; }
</style>
