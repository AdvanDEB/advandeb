<template>
  <aside class="ob-panel">
    <!-- ── Search ──────────────────────────────────────────────────── -->
    <div class="ob-search-row">
      <svg class="ob-search-icon" viewBox="0 0 16 16" fill="none">
        <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.4"/>
        <line x1="10" y1="10" x2="14" y2="14" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
      </svg>
      <input
        class="ob-search-input"
        type="text"
        placeholder="Search node..."
        :value="localDisplay.searchQuery"
        @input="setDisplay('searchQuery', ($event.target as HTMLInputElement).value)"
      />
      <button
        v-if="localDisplay.searchQuery"
        class="ob-search-clear"
        @click="setDisplay('searchQuery', '')"
      >✕</button>
    </div>

    <!-- ── Filters section ─────────────────────────────────────────── -->
    <div class="ob-section">
      <button class="ob-section-hd" @click="open.filters = !open.filters">
        <span class="ob-chevron" :class="{ open: open.filters }">›</span>
        <span>Filters</span>
      </button>
      <div v-if="open.filters" class="ob-section-body">
        <!-- Schema selector -->
        <div class="ob-sub-label">Graph</div>
        <ul class="ob-schema-list">
          <li
            v-for="s in schemas"
            :key="s._id"
            :class="['ob-schema-item', { active: modelValue?._id === s._id }]"
            @click="$emit('update:modelValue', s)"
          >
            <span
              v-if="s.artifact"
              :class="['ob-artifact-dot', `ob-artifact--${s.artifact.status}`]"
              :title="artifactTitle(s.artifact)"
            />
            <span class="ob-schema-name">{{ s.name }}</span>
            <span v-if="statsBySchema[s._id]" class="ob-schema-stat">
              {{ fmtNum(statsBySchema[s._id].nodes ?? statsBySchema[s._id].node_count) }}n
            </span>
          </li>
        </ul>
      </div>
    </div>

    <!-- ── Groups section ──────────────────────────────────────────── -->
    <div v-if="typeCounts" class="ob-section">
      <button class="ob-section-hd" @click="open.groups = !open.groups">
        <span class="ob-chevron" :class="{ open: open.groups }">›</span>
        <span>Groups</span>
      </button>
      <div v-if="open.groups" class="ob-section-body">
        <div class="ob-sub-label">Node types</div>
        <ul class="ob-type-list">
          <li v-for="(count, type) in typeCounts.node_types" :key="type" class="ob-type-item">
            <label class="ob-type-label">
              <span
                class="ob-type-dot"
                :style="{ background: nodeHex(type), boxShadow: `0 0 6px ${nodeHex(type)}88` }"
              />
              <input
                type="checkbox"
                class="ob-cb"
                :checked="!hiddenTypes.has(type)"
                @change="emit('toggleType', type)"
              />
              <span class="ob-type-name">{{ type }}</span>
              <span class="ob-type-count">{{ fmtNum(count) }}</span>
            </label>
          </li>
        </ul>

        <div class="ob-sub-label" style="margin-top:0.6rem">Edge types</div>
        <ul class="ob-type-list">
          <li v-for="(count, type) in augmentedEdgeTypes" :key="type" class="ob-type-item">
            <label class="ob-type-label">
              <span
                class="ob-edge-dash"
                :style="{ background: edgeHex(type) }"
              />
              <input
                type="checkbox"
                class="ob-cb"
                :checked="!hiddenEdgeTypes.has(type)"
                @change="emit('toggleEdgeType', type)"
              />
              <span class="ob-type-name ob-small">{{ type }}</span>
              <span class="ob-type-count">{{ fmtNum(count) }}</span>
            </label>
          </li>
        </ul>
      </div>
    </div>

    <!-- ── Display section ─────────────────────────────────────────── -->
    <div class="ob-section">
      <button class="ob-section-hd" @click="open.display = !open.display">
        <span class="ob-chevron" :class="{ open: open.display }">›</span>
        <span>Display</span>
      </button>
      <div v-if="open.display" class="ob-section-body">
        <div class="ob-control-row">
          <span class="ob-ctrl-label">Node size</span>
          <input type="range" min="0.5" max="3" step="0.1"
            :value="localDisplay.nodeSizeScale"
            @input="setDisplayNum('nodeSizeScale', $event)"
          />
          <span class="ob-ctrl-val">{{ localDisplay.nodeSizeScale.toFixed(1) }}</span>
        </div>
        <div class="ob-control-row">
          <span class="ob-ctrl-label">Link width</span>
          <input type="range" min="0.5" max="3" step="0.1"
            :value="localDisplay.linkWidthScale"
            @input="setDisplayNum('linkWidthScale', $event)"
          />
          <span class="ob-ctrl-val">{{ localDisplay.linkWidthScale.toFixed(1) }}</span>
        </div>
        <div class="ob-control-row">
          <label class="ob-toggle-label">
            <span class="ob-ctrl-label">Particles</span>
            <input type="checkbox" class="ob-cb" :checked="localDisplay.linkParticles"
              @change="setDisplay('linkParticles', ($event.target as HTMLInputElement).checked)"
            />
            <span class="ob-toggle-track" :class="{ on: localDisplay.linkParticles }" />
          </label>
        </div>
        <template v-if="localDisplay.linkParticles">
          <div class="ob-control-row">
            <span class="ob-ctrl-label">Particle count</span>
            <input type="range" min="1" max="6" step="1"
              :value="localDisplay.linkParticleCount"
              @input="setDisplayNum('linkParticleCount', $event)"
            />
            <span class="ob-ctrl-val">{{ localDisplay.linkParticleCount }}</span>
          </div>
          <div class="ob-control-row">
            <span class="ob-ctrl-label">Particle speed</span>
            <input type="range" min="0.3" max="3" step="0.1"
              :value="localDisplay.linkParticleSpeed"
              @input="setDisplayNum('linkParticleSpeed', $event)"
            />
            <span class="ob-ctrl-val">{{ localDisplay.linkParticleSpeed.toFixed(1) }}</span>
          </div>
        </template>
      </div>
    </div>

    <!-- ── Forces section ──────────────────────────────────────────── -->
    <div class="ob-section">
      <button class="ob-section-hd" @click="open.forces = !open.forces">
        <span class="ob-chevron" :class="{ open: open.forces }">›</span>
        <span>Forces</span>
      </button>
      <div v-if="open.forces" class="ob-section-body">
        <div class="ob-control-row">
          <span class="ob-ctrl-label">Repulsion</span>
          <input type="range" min="0.1" max="10" step="0.1"
            :value="localDisplay.repulsion"
            @input="setDisplayNum('repulsion', $event)"
          />
          <span class="ob-ctrl-val">{{ localDisplay.repulsion.toFixed(1) }}</span>
        </div>
        <div class="ob-control-row">
          <span class="ob-ctrl-label">Link dist.</span>
          <input type="range" min="1" max="100" step="1"
            :value="localDisplay.linkDistance"
            @input="setDisplayNum('linkDistance', $event)"
          />
          <span class="ob-ctrl-val">{{ localDisplay.linkDistance }}</span>
        </div>
        <div class="ob-control-row">
          <span class="ob-ctrl-label">Gravity</span>
          <input type="range" min="0" max="1" step="0.01"
            :value="localDisplay.gravity"
            @input="setDisplayNum('gravity', $event)"
          />
          <span class="ob-ctrl-val">{{ localDisplay.gravity.toFixed(2) }}</span>
        </div>
      </div>
    </div>

    <!-- ── Stats section ───────────────────────────────────────────── -->
    <div v-if="selectedStats" class="ob-section">
      <button class="ob-section-hd" @click="open.stats = !open.stats">
        <span class="ob-chevron" :class="{ open: open.stats }">›</span>
        <span>Stats</span>
      </button>
      <div v-if="open.stats" class="ob-section-body ob-stats">
        <div class="ob-stat-row">
          <span>Nodes</span>
          <strong>{{ fmtNum(selectedStats.nodes ?? selectedStats.node_count) }}</strong>
        </div>
        <div class="ob-stat-row">
          <span>Edges</span>
          <strong>{{ fmtNum(selectedStats.edges ?? selectedStats.edge_count) }}</strong>
        </div>
        <div v-if="selectedStats.density" class="ob-stat-row">
          <span>Density</span>
          <strong>{{ selectedStats.density.toFixed(6) }}</strong>
        </div>
      </div>
    </div>

    <!-- ── Actions ─────────────────────────────────────────────────── -->
    <div class="ob-actions">
      <button class="ob-action-btn" @click="$emit('fitView')">
        <svg viewBox="0 0 16 16" fill="none" width="13" height="13">
          <rect x="1" y="1" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.4"/>
          <rect x="10" y="1" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.4"/>
          <rect x="1" y="10" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.4"/>
          <rect x="10" y="10" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.4"/>
        </svg>
        Fit view
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { GraphSchema, GraphStats, TypeCounts } from '@/utils/kbApi'
import type { GraphArtifactMeta } from '@/types/graphArtifact'
import { NODE_TYPE_HEX, DEFAULT_NODE_HEX, EDGE_TYPE_HEX, DEFAULT_EDGE_HEX } from '@/utils/kbColors'
import type { DisplayConfig } from '@/components/kb/CosmographCanvas.vue'

const ALWAYS_SHOWN_EDGE_TYPES = ['supports', 'extracted_from', 'opposes']

const DEFAULT_DISPLAY: Required<DisplayConfig> = {
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

const props = defineProps<{
  schemas: GraphSchema[]
  modelValue: GraphSchema | null
  statsBySchema: Record<string, GraphStats>
  selectedStats: GraphStats | null
  typeCounts: TypeCounts | null
  hiddenTypes: Set<string>
  hiddenEdgeTypes: Set<string>
  display?: Partial<DisplayConfig>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', schema: GraphSchema): void
  (e: 'fitView'): void
  (e: 'toggleType', type: string): void
  (e: 'toggleEdgeType', type: string): void
  (e: 'update:display', display: DisplayConfig): void
}>()

// Section open/closed state
const open = reactive({ filters: true, groups: true, display: true, forces: false, stats: false })

// Local copy of display config for two-way binding
const localDisplay = reactive<Required<DisplayConfig>>({ ...DEFAULT_DISPLAY, ...props.display })

watch(() => props.display, (d) => {
  if (!d) return
  Object.assign(localDisplay, d)
}, { deep: true })

function setDisplay<K extends keyof DisplayConfig>(key: K, value: DisplayConfig[K]) {
  (localDisplay as any)[key] = value
  emit('update:display', { ...localDisplay })
}

function setDisplayNum(key: keyof DisplayConfig, ev: Event) {
  const val = parseFloat((ev.target as HTMLInputElement).value)
  if (!isNaN(val)) setDisplay(key, val as any)
}

const augmentedEdgeTypes = computed<Record<string, number>>(() => {
  const base = props.typeCounts?.edge_types ?? {}
  const result: Record<string, number> = {}
  for (const type of ALWAYS_SHOWN_EDGE_TYPES) result[type] = base[type] ?? 0
  for (const [type, count] of Object.entries(base)) {
    if (!(type in result)) result[type] = count
  }
  return result
})

function fmtNum(n: number | undefined): string {
  if (n == null || isNaN(n as number)) return '—'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k'
  return String(n)
}

function nodeHex(type: string) { return NODE_TYPE_HEX[type] ?? DEFAULT_NODE_HEX }
function edgeHex(type: string) { return EDGE_TYPE_HEX[type] ?? DEFAULT_EDGE_HEX }

function artifactTitle(meta: GraphArtifactMeta): string {
  switch (meta.status) {
    case 'ready':    return `Ready · ${meta.built_at ? new Date(meta.built_at).toLocaleDateString() : ''}`
    case 'stale':    return 'Stale — rebuilds on next load'
    case 'building': return 'Building…'
    case 'failed':   return `Failed: ${meta.error ?? 'unknown'}`
    case 'missing':  return 'Not yet built'
    case 'too_large_for_browser': return 'Too large for browser'
    default: return meta.status
  }
}
</script>

<style scoped>
/* ── Panel shell ─────────────────────────────────────────────────────────── */
.ob-panel {
  width: 220px;
  flex-shrink: 0;
  background: #0f1117;
  border-right: 1px solid rgba(255,255,255,0.07);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  overflow-x: hidden;
  font-size: 0.76rem;
  color: #b0b8cc;
  scrollbar-width: thin;
  scrollbar-color: #2a2f3e transparent;
}

/* ── Search ──────────────────────────────────────────────────────────────── */
.ob-search-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.5rem 0.7rem;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.ob-search-icon {
  width: 13px;
  height: 13px;
  color: #4a5270;
  flex-shrink: 0;
}
.ob-search-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  font-size: 0.73rem;
  color: #c8d0e0;
  caret-color: #7090e0;
  min-width: 0;
}
.ob-search-input::placeholder { color: #3a4060; }
.ob-search-clear {
  background: none;
  border: none;
  color: #4a5270;
  font-size: 0.65rem;
  cursor: pointer;
  padding: 0 0.1rem;
  line-height: 1;
}
.ob-search-clear:hover { color: #9098b0; }

/* ── Collapsible sections ─────────────────────────────────────────────────── */
.ob-section {
  border-bottom: 1px solid rgba(255,255,255,0.05);
}

.ob-section-hd {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  padding: 0.5rem 0.7rem;
  color: #8090b0;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  user-select: none;
}
.ob-section-hd:hover { color: #b0b8d0; }

.ob-chevron {
  font-size: 0.9rem;
  line-height: 1;
  color: #4a5270;
  transition: transform 0.15s;
  display: inline-block;
}
.ob-chevron.open { transform: rotate(90deg); color: #7090d0; }

.ob-section-body {
  padding: 0.3rem 0.7rem 0.6rem;
}

.ob-sub-label {
  font-size: 0.63rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #3a4060;
  font-weight: 700;
  margin-bottom: 0.3rem;
}

/* ── Schema list ─────────────────────────────────────────────────────────── */
.ob-schema-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.ob-schema-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.32rem 0.45rem;
  border-radius: 5px;
  cursor: pointer;
  border: 1px solid transparent;
}
.ob-schema-item:hover { background: rgba(255,255,255,0.05); }
.ob-schema-item.active {
  background: rgba(80, 120, 255, 0.12);
  border-color: rgba(80, 120, 255, 0.3);
}

.ob-artifact-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ob-artifact--ready    { background: #34e778; box-shadow: 0 0 5px #34e77888; }
.ob-artifact--stale    { background: #ffc828; }
.ob-artifact--building { background: #63b3ff; animation: ob-pulse 1.2s ease-in-out infinite; }
.ob-artifact--failed   { background: #ff5050; }
.ob-artifact--missing  { background: #3a4060; }
.ob-artifact--too_large_for_browser { background: #ff9b46; }

@keyframes ob-pulse { 0%,100% { opacity: 0.5; } 50% { opacity: 1; } }

.ob-schema-name { font-size: 0.75rem; color: #c0c8d8; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ob-schema-item.active .ob-schema-name { color: #a0b8ff; }
.ob-schema-stat { font-size: 0.62rem; color: #3a4060; flex-shrink: 0; }

/* ── Type / group list ───────────────────────────────────────────────────── */
.ob-type-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.ob-type-item { }

.ob-type-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  cursor: pointer;
  padding: 0.18rem 0.3rem;
  border-radius: 4px;
}
.ob-type-label:hover { background: rgba(255,255,255,0.04); }

.ob-type-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ob-edge-dash {
  width: 14px;
  height: 2.5px;
  border-radius: 2px;
  flex-shrink: 0;
  opacity: 0.9;
}

/* visually hide native checkbox but keep it functional */
.ob-cb {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
  pointer-events: none;
}

.ob-type-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #9098b0; font-size: 0.73rem; }
.ob-type-name.ob-small { font-size: 0.67rem; color: #6878a0; }
.ob-type-count { font-size: 0.62rem; color: #3a4060; flex-shrink: 0; margin-left: auto; }

/* dim when hidden (checkbox unchecked) */
.ob-cb:not(:checked) ~ .ob-type-name,
.ob-cb:not(:checked) ~ .ob-type-count {
  opacity: 0.4;
}
.ob-cb:not(:checked) + .ob-type-dot,
.ob-cb:not(:checked) + .ob-edge-dash {
  opacity: 0.2;
}

/* ── Display controls ────────────────────────────────────────────────────── */
.ob-control-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.22rem 0;
}
.ob-ctrl-label {
  width: 72px;
  font-size: 0.69rem;
  color: #6878a0;
  flex-shrink: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ob-control-row input[type="range"] {
  flex: 1;
  appearance: none;
  height: 3px;
  background: #2a3050;
  border-radius: 2px;
  outline: none;
  cursor: pointer;
  min-width: 0;
}
.ob-control-row input[type="range"]::-webkit-slider-thumb {
  appearance: none;
  width: 11px;
  height: 11px;
  background: #5070e0;
  border-radius: 50%;
  box-shadow: 0 0 6px #5070e088;
  cursor: pointer;
}
.ob-ctrl-val {
  font-size: 0.62rem;
  color: #4a5a80;
  width: 26px;
  text-align: right;
  flex-shrink: 0;
}

/* Toggle switch */
.ob-toggle-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  cursor: pointer;
  flex: 1;
}
.ob-toggle-track {
  width: 28px;
  height: 14px;
  background: #2a3050;
  border-radius: 7px;
  position: relative;
  flex-shrink: 0;
  transition: background 0.2s;
}
.ob-toggle-track::after {
  content: '';
  position: absolute;
  width: 10px;
  height: 10px;
  background: #4a5a80;
  border-radius: 50%;
  top: 2px;
  left: 2px;
  transition: left 0.2s, background 0.2s;
}
.ob-toggle-track.on { background: rgba(80, 130, 255, 0.35); }
.ob-toggle-track.on::after { left: 16px; background: #6090ff; box-shadow: 0 0 6px #6090ff88; }

/* ── Stats ───────────────────────────────────────────────────────────────── */
.ob-stats { display: flex; flex-direction: column; gap: 0.25rem; }
.ob-stat-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.72rem;
  color: #6878a0;
  padding: 0.1rem 0;
}
.ob-stat-row strong { color: #9098b0; font-weight: 600; }

/* ── Actions ─────────────────────────────────────────────────────────────── */
.ob-actions {
  padding: 0.6rem 0.7rem;
  margin-top: auto;
  border-top: 1px solid rgba(255,255,255,0.05);
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.ob-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  padding: 0.42rem 0.6rem;
  border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.04);
  color: #7888a8;
  font-size: 0.72rem;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.ob-action-btn:hover {
  background: rgba(80, 120, 255, 0.15);
  border-color: rgba(80, 120, 255, 0.35);
  color: #a0b4ff;
}
</style>
