<template>
  <div class="sim-panel">
    <div class="field-row">
      <label class="field">
        <span>Duration [days]</span>
        <input v-model.number="config.duration" type="number" min="0.1" step="1" />
      </label>
      <label class="field">
        <span>Output interval [days]</span>
        <input v-model.number="config.dt" type="number" min="0.001" step="0.1" />
      </label>
    </div>

    <label class="field">
      <span>Solver</span>
      <select v-model="config.method">
        <option v-for="m in SOLVER_METHODS" :key="m.value" :value="m.value">{{ m.label }}</option>
      </select>
    </label>

    <p class="point-count" :class="{ warn: tooManyPoints }">
      {{ pointCount.toLocaleString() }} output points
      <template v-if="tooManyPoints"> — reduce the duration or widen the interval</template>
    </p>

    <div class="divider">Environment</div>

    <label class="field">
      <span>Temperature — {{ config.temperatureC }} °C</span>
      <input v-model.number="config.temperatureC" type="range" min="0" max="40" step="0.5" />
    </label>

    <label class="field">
      <span>Food availability f — {{ config.foodDensity }}</span>
      <input v-model.number="config.foodDensity" type="range" min="0" max="1" step="0.01" />
    </label>

    <div class="sim-buttons">
      <button class="btn-primary" :disabled="busy || !canRun" @click="emit('run', request())">
        {{ running ? 'Computing…' : '▶ Run simulation' }}
      </button>
      <button class="btn-secondary" :disabled="busy || !canRun" @click="emit('stream', request())">
        ◉ Live stream
      </button>
      <button v-if="streaming" class="btn-stop" @click="emit('stop')">■ Stop</button>
    </div>

    <p v-if="!canRun" class="hint">
      Add at least one non-food compartment before running a simulation.
    </p>

    <div v-if="progress !== null" class="progress-wrap">
      <div class="progress-bar"><div class="progress-fill" :style="{ width: progressPct }"></div></div>
      <span class="progress-text">{{ progressText }}</span>
    </div>

    <p v-if="errorMessage" class="sim-error">{{ errorMessage }}</p>

    <template v-if="stateNodes.length">
      <div class="divider">Tracked variables</div>
      <div class="var-list">
        <label v-for="n in stateNodes" :key="n.id" class="var-item">
          <input v-model="tracked" type="checkbox" :value="n.name" />
          <span class="var-dot" :style="{ background: nodeColor(n.node_type) }"></span>
          <span>{{ n.name }}</span>
        </label>
      </div>
      <div v-show="hasLiveChart" ref="liveEl" class="chart-box"></div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import Plotly from '@/utils/plotlyCore'
import type { SimulationRequest, SimulationResult, TDebNode } from '@/utils/tdebApi'
import { KELVIN_OFFSET, SOLVER_METHODS, nodeColor } from '@/utils/tdebConstants'

const props = defineProps<{
  nodes: Record<string, TDebNode>
  running: boolean
  streaming: boolean
  progress: number | null
  progressLabel: string
  errorMessage: string
  result: SimulationResult | null
}>()

const emit = defineEmits<{
  (e: 'run', request: SimulationRequest): void
  (e: 'stream', request: SimulationRequest): void
  (e: 'stop'): void
}>()

const config = reactive({
  duration: 365,
  dt: 1,
  method: 'RK45' as SimulationRequest['method'],
  temperatureC: 20,
  foodDensity: 1,
})

const tracked = ref<string[]>([])
const liveEl = ref<HTMLElement | null>(null)
const hasLiveChart = ref(false)

/** Trace order for extendTraces — index i is the trace for traceNames[i]. */
let traceNames: string[] = []

const busy = computed(() => props.running || props.streaming)

// Food compartments are boundary conditions, so they never appear as states.
const stateNodes = computed(() =>
  Object.values(props.nodes).filter(n => n.node_type !== 'food'))

const canRun = computed(() => stateNodes.value.length > 0)

const pointCount = computed(() => {
  if (!(config.dt > 0) || !(config.duration > 0)) return 0
  return Math.floor(config.duration / config.dt) + 1
})
// Mirrors MAX_OUTPUT_POINTS on the server, surfaced before the request is sent.
const tooManyPoints = computed(() => pointCount.value > 100_000)

const progressPct = computed(() =>
  `${Math.round((props.progress ?? 0) * 100)}%`)
const progressText = computed(() =>
  props.progressLabel || progressPct.value)

function request(): SimulationRequest {
  return {
    t_end: config.duration,
    dt_output: config.dt,
    method: config.method,
    temperature: config.temperatureC + KELVIN_OFFSET,
    food_density: config.foodDensity,
  }
}

// Default to tracking every state compartment; keep the selection in sync as
// compartments are added or removed, without clobbering a manual choice.
watch(stateNodes, (nodes, previous) => {
  const names = nodes.map(n => n.name)
  const previousNames = (previous ?? []).map(n => n.name)
  const added = names.filter(n => !previousNames.includes(n))
  tracked.value = [...tracked.value.filter(n => names.includes(n)), ...added]
}, { immediate: true })

function layout() {
  return {
    paper_bgcolor: '#ffffff',
    plot_bgcolor: '#ffffff',
    font: { family: 'system-ui, sans-serif', color: '#4b5563', size: 11 },
    margin: { l: 55, r: 15, t: 15, b: 40 },
    xaxis: { gridcolor: '#e5e7eb', zerolinecolor: '#e5e7eb', title: { text: 'Time [days]' } },
    yaxis: { gridcolor: '#e5e7eb', zerolinecolor: '#e5e7eb', title: { text: 'Value' } },
    legend: { bgcolor: 'transparent', font: { size: 10 }, orientation: 'h' as const, y: -0.28 },
    hovermode: 'x unified' as const,
  }
}

function colorFor(name: string): string {
  const node = stateNodes.value.find(n => n.name === name)
  return nodeColor(node?.node_type ?? 'custom')
}

/** Reset the live chart to empty traces, one per tracked variable. */
async function initLiveChart() {
  traceNames = [...tracked.value]
  if (!traceNames.length) {
    hasLiveChart.value = false
    return
  }
  hasLiveChart.value = true
  await nextTick()
  if (!liveEl.value) return
  await Plotly.react(liveEl.value, traceNames.map(name => ({
    x: [] as number[],
    y: [] as number[],
    name,
    type: 'scatter',
    mode: 'lines',
    line: { color: colorFor(name), width: 2 },
  })), layout(), { responsive: true, displayModeBar: false })
}

/** Append one streamed snapshot to the live traces. */
async function pushSnapshot(time: number, values: Record<string, number>) {
  if (!liveEl.value || !traceNames.length) return
  const xs: number[][] = []
  const ys: number[][] = []
  const indices: number[] = []
  traceNames.forEach((name, i) => {
    const v = values[name]
    if (v === undefined) return
    xs.push([time])
    ys.push([v])
    indices.push(i)
  })
  if (indices.length) {
    await Plotly.extendTraces(liveEl.value, { x: xs, y: ys }, indices)
  }
}

/** Draw a completed batch result on the live chart. */
async function showBatch(result: SimulationResult) {
  traceNames = tracked.value.filter(name => result.states[name])
  if (!traceNames.length) {
    hasLiveChart.value = false
    return
  }
  hasLiveChart.value = true
  await nextTick()
  if (!liveEl.value) return
  await Plotly.react(liveEl.value, traceNames.map(name => ({
    x: result.time,
    y: result.states[name],
    name,
    type: 'scatter',
    mode: 'lines',
    line: { color: colorFor(name), width: 2 },
  })), layout(), { responsive: true, displayModeBar: false })
}

defineExpose({ initLiveChart, pushSnapshot, showBatch })

watch(() => props.result, (r) => { if (r?.success) showBatch(r) })

onBeforeUnmount(() => { if (liveEl.value) Plotly.purge(liveEl.value) })
</script>

<style scoped>
.sim-panel { display: flex; flex-direction: column; gap: 0.75rem; }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }
.field { display: flex; flex-direction: column; gap: 0.25rem; }
.field > span { font-size: 0.72rem; font-weight: 600; color: #4b5563; }
.field input[type='number'],
.field select {
  border: 1px solid #d1d5db;
  border-radius: 5px;
  padding: 0.35rem 0.5rem;
  font-size: 0.82rem;
  color: #111827;
  background: #fff;
  width: 100%;
}
.field input[type='range'] { width: 100%; accent-color: #3b82f6; }

.point-count { font-size: 0.68rem; color: #9ca3af; margin: -0.4rem 0 0; }
.point-count.warn { color: #b45309; font-weight: 600; }

.divider {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 0.25rem;
  margin-top: 0.3rem;
}

.sim-buttons { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.3rem; }
.btn-primary,
.btn-secondary,
.btn-stop {
  border-radius: 5px;
  padding: 0.42rem 0.85rem;
  font-size: 0.8rem;
  cursor: pointer;
  border: 1px solid transparent;
}
.btn-primary { background: #3b82f6; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #2563eb; }
.btn-secondary { background: #fff; color: #374151; border-color: #d1d5db; }
.btn-secondary:hover:not(:disabled) { background: #f3f4f6; }
.btn-stop { background: #fef2f2; color: #b91c1c; border-color: #fecaca; }
.btn-stop:hover { background: #fee2e2; }
.btn-primary:disabled,
.btn-secondary:disabled { opacity: 0.55; cursor: default; }

.hint { font-size: 0.72rem; color: #6b7280; margin: 0; }

.progress-wrap { display: flex; align-items: center; gap: 0.5rem; }
.progress-bar {
  flex: 1;
  height: 6px;
  background: #e5e7eb;
  border-radius: 999px;
  overflow: hidden;
}
.progress-fill { height: 100%; background: #3b82f6; transition: width 0.15s linear; }
.progress-text {
  font-size: 0.7rem;
  color: #6b7280;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.sim-error {
  font-size: 0.75rem;
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 5px;
  padding: 0.4rem 0.55rem;
  margin: 0;
}

.var-list { display: flex; flex-direction: column; gap: 0.3rem; }
.var-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  color: #374151;
  cursor: pointer;
}
.var-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }

.chart-box {
  width: 100%;
  height: 220px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  margin-top: 0.4rem;
}
</style>
