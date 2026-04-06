<template>
  <aside class="schema-panel">
    <div class="panel-section">
      <div class="section-label">Graph Schema</div>
      <ul class="schema-list">
        <li
          v-for="s in schemas"
          :key="s._id"
          :class="['schema-item', { active: modelValue?._id === s._id }]"
          @click="$emit('update:modelValue', s)"
        >
          <span class="schema-name">{{ s.name }}</span>
          <span v-if="statsBySchema[s._id]" class="schema-stat">
            {{ fmtNum(statsBySchema[s._id].nodes) }}n · {{ fmtNum(statsBySchema[s._id].edges) }}e
          </span>
        </li>
      </ul>
    </div>

    <div v-if="typeCounts" class="panel-section">
      <div class="section-label">Node Types</div>
      <ul class="filter-list">
        <li v-for="(count, type) in typeCounts.node_types" :key="type" class="filter-item">
          <label class="filter-label">
            <input
              type="checkbox"
              :checked="!hiddenTypes.has(type)"
              @change="emit('toggleType', type)"
            />
            <span class="type-dot" :style="{ background: nodeTypeColor(type) }"></span>
            <span class="type-name">{{ type }}</span>
            <span class="type-count">{{ fmtNum(count) }}</span>
          </label>
        </li>
      </ul>
    </div>

    <div v-if="typeCounts" class="panel-section">
      <div class="section-label">Edge Types</div>
      <ul class="filter-list">
        <li v-for="(count, type) in augmentedEdgeTypes" :key="type" class="filter-item">
          <label class="filter-label">
            <input
              type="checkbox"
              :checked="!hiddenEdgeTypes.has(type)"
              @change="emit('toggleEdgeType', type)"
            />
            <span class="edge-dash" :style="{ background: edgeTypeColor(type) }"></span>
            <span class="type-name small">{{ type }}</span>
            <span class="type-count">{{ fmtNum(count) }}</span>
          </label>
        </li>
      </ul>
    </div>

    <div v-if="selectedStats" class="panel-section stats-section">
      <div class="section-label">Stats</div>
      <div class="stat-row"><span>Nodes</span><strong>{{ fmtNum(selectedStats.nodes) }}</strong></div>
      <div class="stat-row"><span>Edges</span><strong>{{ fmtNum(selectedStats.edges) }}</strong></div>
      <div v-if="selectedStats.density" class="stat-row">
        <span>Density</span><strong>{{ selectedStats.density.toFixed(6) }}</strong>
      </div>
    </div>

    <div class="panel-actions">
      <button
        v-if="modelValue"
        class="panel-btn primary"
        :disabled="rebuilding"
        @click="$emit('rebuild')"
      >
        {{ rebuilding ? 'Rebuilding…' : 'Rebuild Graph' }}
      </button>
      <button class="panel-btn" @click="$emit('fitView')">Fit View</button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { GraphSchema, GraphStats, TypeCounts } from '@/utils/kbApi'
import { NODE_TYPE_HEX, DEFAULT_NODE_HEX, EDGE_TYPE_HEX, DEFAULT_EDGE_HEX } from '@/utils/kbColors'

// Edge types that should always appear in the sidebar even when count is 0
const ALWAYS_SHOWN_EDGE_TYPES = ['supports', 'extracted_from', 'opposes']

const props = defineProps<{
  schemas: GraphSchema[]
  modelValue: GraphSchema | null
  statsBySchema: Record<string, GraphStats>
  selectedStats: GraphStats | null
  typeCounts: TypeCounts | null
  hiddenTypes: Set<string>
  hiddenEdgeTypes: Set<string>
  rebuilding: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', schema: GraphSchema): void
  (e: 'rebuild'): void
  (e: 'fitView'): void
  (e: 'toggleType', type: string): void
  (e: 'toggleEdgeType', type: string): void
}>()

/**
 * Edge type map guaranteed to include ALWAYS_SHOWN_EDGE_TYPES (count 0 if absent).
 * Preserves ordering: always-shown types first, then any remaining DB types.
 */
const augmentedEdgeTypes = computed<Record<string, number>>(() => {
  const base = props.typeCounts?.edge_types ?? {}
  const result: Record<string, number> = {}
  for (const type of ALWAYS_SHOWN_EDGE_TYPES) {
    result[type] = base[type] ?? 0
  }
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

function nodeTypeColor(type: string): string {
  return NODE_TYPE_HEX[type] ?? DEFAULT_NODE_HEX
}

function edgeTypeColor(type: string): string {
  return EDGE_TYPE_HEX[type] ?? DEFAULT_EDGE_HEX
}
</script>

<style scoped>
.schema-panel {
  width: 220px;
  flex-shrink: 0;
  background: #1e293b;
  border-right: 1px solid #334155;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  gap: 0;
}

.panel-section {
  padding: 0.75rem;
  border-bottom: 1px solid #334155;
}

.section-label {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #64748b;
  font-weight: 700;
  margin-bottom: 0.5rem;
}

.schema-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.schema-item {
  display: flex;
  flex-direction: column;
  padding: 0.4rem 0.5rem;
  border-radius: 5px;
  cursor: pointer;
  gap: 0.1rem;
  border: 1px solid transparent;
}
.schema-item:hover { background: #334155; }
.schema-item.active { background: #1e3a5f; border-color: #3b82f6; }

.schema-name { font-size: 0.78rem; color: #e2e8f0; font-weight: 500; }
.schema-stat { font-size: 0.65rem; color: #64748b; }

.filter-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.filter-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  cursor: pointer;
  font-size: 0.73rem;
  color: #cbd5e1;
}
.filter-label input[type="checkbox"] { accent-color: #3b82f6; flex-shrink: 0; }
.type-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.edge-dash { width: 14px; height: 3px; border-radius: 2px; flex-shrink: 0; opacity: 0.8; }
.type-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.type-name.small { font-size: 0.68rem; color: #94a3b8; }
.type-count { font-size: 0.65rem; color: #475569; margin-left: auto; flex-shrink: 0; }

.stat-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #94a3b8;
  padding: 0.15rem 0;
}
.stat-row strong { color: #e2e8f0; }

.panel-actions {
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-top: auto;
  border-top: 1px solid #334155;
}

.panel-btn {
  padding: 0.45rem;
  border-radius: 5px;
  border: 1px solid #334155;
  background: #0f172a;
  color: #cbd5e1;
  font-size: 0.75rem;
  cursor: pointer;
  text-align: center;
}
.panel-btn:hover { background: #334155; }
.panel-btn.primary { background: #1d4ed8; border-color: #3b82f6; color: white; }
.panel-btn.primary:hover { background: #2563eb; }
.panel-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
