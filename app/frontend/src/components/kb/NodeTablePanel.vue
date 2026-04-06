<template>
  <div class="node-table-panel">
    <!-- Toolbar -->
    <div class="ntp-toolbar">
      <select v-model="filterType" class="ntp-select" title="Filter by node type">
        <option value="">All types</option>
        <option v-for="t in uniqueTypes" :key="t" :value="t">{{ t.replace(/_/g, ' ') }}</option>
      </select>
      <input
        v-model="searchText"
        class="ntp-search"
        placeholder="Search label…"
        spellcheck="false"
      />
      <span class="ntp-count">{{ filteredNodes.length }} / {{ nodes.length }}</span>
    </div>

    <!-- Table -->
    <div class="ntp-scroll">
      <table class="ntp-table">
        <thead>
          <tr>
            <th class="col-type"  @click="setSort('node_type')">Type<SortIcon :col="'node_type'" :sortKey="sortKey" :sortDir="sortDir" /></th>
            <th class="col-label" @click="setSort('label')">Label<SortIcon :col="'label'" :sortKey="sortKey" :sortDir="sortDir" /></th>
            <th class="col-deg"   @click="setSort('degree')">Deg<SortIcon :col="'degree'" :sortKey="sortKey" :sortDir="sortDir" /></th>
            <th class="col-eid">Entity ID</th>
            <th class="col-props">Properties</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="node in filteredNodes"
            :key="node._id"
            :class="{ 'row-selected': selectedNode?._id === node._id }"
            @click="$emit('select', node)"
          >
            <td>
              <span class="type-badge" :class="`type-${node.node_type.replace(/_/g, '-')}`">
                {{ node.node_type.replace(/_/g, ' ') }}
              </span>
            </td>
            <td class="col-label-cell" :title="node.label">{{ node.label }}</td>
            <td class="col-deg-cell">{{ node.degree ?? '—' }}</td>
            <td class="col-eid-cell mono" :title="node.entity_id">{{ node.entity_id || '—' }}</td>
            <td class="col-props-cell" :title="formatPropsLong(node)">{{ formatProps(node) }}</td>
          </tr>
          <tr v-if="filteredNodes.length === 0">
            <td colspan="5" class="ntp-empty">No nodes match the current filter</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, defineComponent, h } from 'vue'
import type { GraphNode } from '@/utils/kbApi'

// ── Props / Emits ────────────────────────────────────────────────────────────

const props = defineProps<{
  nodes: GraphNode[]
  selectedNode: GraphNode | null
}>()

defineEmits<{
  (e: 'select', node: GraphNode): void
}>()

// ── Sort icon inline component ───────────────────────────────────────────────

const SortIcon = defineComponent({
  props: {
    col: { type: String, required: true },
    sortKey: { type: String, required: true },
    sortDir: { type: String, required: true },
  },
  setup(p) {
    return () => {
      if (p.col !== p.sortKey) return h('span', { class: 'sort-icon sort-none' }, ' ⇅')
      return h('span', { class: 'sort-icon sort-active' }, p.sortDir === 'asc' ? ' ↑' : ' ↓')
    }
  },
})

// ── Reactive state ───────────────────────────────────────────────────────────

const filterType = ref('')
const searchText = ref('')
const sortKey    = ref<string>('degree')
const sortDir    = ref<'asc' | 'desc'>('desc')

// ── Derived data ─────────────────────────────────────────────────────────────

const uniqueTypes = computed<string[]>(() => {
  const s = new Set<string>()
  for (const n of props.nodes) s.add(n.node_type)
  return Array.from(s).sort()
})

const filteredNodes = computed<GraphNode[]>(() => {
  let list = props.nodes

  if (filterType.value) {
    list = list.filter(n => n.node_type === filterType.value)
  }

  if (searchText.value.trim()) {
    const q = searchText.value.trim().toLowerCase()
    list = list.filter(n => n.label?.toLowerCase().includes(q))
  }

  // sort
  const key = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  list = [...list].sort((a, b) => {
    let av: any = (a as any)[key] ?? ''
    let bv: any = (b as any)[key] ?? ''
    if (key === 'degree') {
      av = (a.degree ?? -1)
      bv = (b.degree ?? -1)
    }
    if (av < bv) return -1 * dir
    if (av > bv) return  1 * dir
    return 0
  })

  return list
})

// ── Helpers ──────────────────────────────────────────────────────────────────

function setSort(col: string) {
  if (sortKey.value === col) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = col
    sortDir.value = col === 'degree' ? 'desc' : 'asc'
  }
}

const PROP_KEYS = ['doi', 'year', 'authors', 'journal', 'rank', 'tax_id', 'confidence', 'status', 'category']

function formatProps(node: GraphNode): string {
  const parts: string[] = []
  for (const k of PROP_KEYS) {
    const v = node.properties[k]
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) {
      if (v.length) parts.push(`${k}: ${(v as string[]).slice(0, 2).join(', ')}${v.length > 2 ? '…' : ''}`)
    } else if (typeof v === 'number') {
      parts.push(`${k}: ${(v as number).toFixed ? (v as number).toFixed(2).replace(/\.?0+$/, '') : v}`)
    } else {
      const s = String(v)
      parts.push(`${k}: ${s.length > 30 ? s.slice(0, 30) + '…' : s}`)
    }
    if (parts.length >= 3) break
  }
  return parts.join(' · ') || '—'
}

function formatPropsLong(node: GraphNode): string {
  const parts: string[] = []
  for (const k of PROP_KEYS) {
    const v = node.properties[k]
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) {
      parts.push(`${k}: ${(v as string[]).join(', ')}`)
    } else {
      parts.push(`${k}: ${v}`)
    }
  }
  return parts.join('\n') || '—'
}
</script>

<style scoped>
.node-table-panel {
  flex-shrink: 0;
  height: 240px;
  display: flex;
  flex-direction: column;
  background: #1e293b;
  border-top: 1px solid #334155;
  overflow: hidden;
}

/* ── Toolbar ─────────────────────────────────────────────────────────────── */
.ntp-toolbar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.75rem;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  flex-shrink: 0;
}

.ntp-select {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 4px;
  color: #cbd5e1;
  font-size: 0.7rem;
  padding: 0.15rem 0.4rem;
  cursor: pointer;
  outline: none;
}
.ntp-select:focus { border-color: #3b82f6; }

.ntp-search {
  flex: 1;
  max-width: 220px;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 4px;
  color: #cbd5e1;
  font-size: 0.7rem;
  padding: 0.15rem 0.5rem;
  outline: none;
}
.ntp-search::placeholder { color: #475569; }
.ntp-search:focus { border-color: #3b82f6; }

.ntp-count {
  margin-left: auto;
  font-size: 0.65rem;
  color: #475569;
  white-space: nowrap;
}

/* ── Scroll container ────────────────────────────────────────────────────── */
.ntp-scroll {
  flex: 1;
  overflow-y: auto;
  overflow-x: auto;
}

/* ── Table ───────────────────────────────────────────────────────────────── */
.ntp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.72rem;
  table-layout: fixed;
}

.ntp-table thead {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #0f172a;
}

.ntp-table th {
  padding: 0.3rem 0.6rem;
  text-align: left;
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
  border-bottom: 1px solid #334155;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.ntp-table th:hover { color: #94a3b8; }

.ntp-table td {
  padding: 0.3rem 0.6rem;
  color: #cbd5e1;
  border-bottom: 1px solid #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.ntp-table tbody tr {
  cursor: pointer;
  transition: background 0.1s;
}
.ntp-table tbody tr:hover { background: #263348; }
.ntp-table tbody tr.row-selected {
  background: #1e3a5f;
  border-left: 2px solid #3b82f6;
}

/* ── Column widths ───────────────────────────────────────────────────────── */
.col-type  { width: 130px; }
.col-label { width: auto;  }
.col-deg   { width: 48px; text-align: right; }
.col-eid   { width: 110px; }
.col-props { width: 240px; }

.col-deg-cell   { text-align: right; color: #94a3b8; }
.col-eid-cell   { color: #475569; font-size: 0.65rem; }
.col-props-cell { color: #64748b; }
.col-label-cell { color: #e2e8f0; }

.mono { font-family: monospace; }

/* ── Type badges (match NodeInspector colours) ───────────────────────────── */
.type-badge {
  display: inline-block;
  font-size: 0.6rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  background: #334155;
  color: #94a3b8;
  white-space: nowrap;
}
.type-badge.type-document           { background: #1d4ed8; color: #bfdbfe; }
.type-badge.type-external-document  { background: #334155; color: #94a3b8; }
.type-badge.type-fact               { background: #065f46; color: #6ee7b7; }
.type-badge.type-stylized-fact      { background: #78350f; color: #fde68a; }
.type-badge.type-taxon,
.type-badge.type-species,
.type-badge.type-genus,
.type-badge.type-family,
.type-badge.type-order,
.type-badge.type-class              { background: #4c1d95; color: #ddd6fe; }
.type-badge.type-phylum             { background: #7c2d12; color: #fed7aa; }
.type-badge.type-kingdom            { background: #7f1d1d; color: #fca5a5; }

/* ── Sort icon ───────────────────────────────────────────────────────────── */
.sort-icon { font-size: 0.6rem; }
.sort-none { color: #334155; }
.sort-active { color: #60a5fa; }

/* ── Empty state ─────────────────────────────────────────────────────────── */
.ntp-empty {
  text-align: center;
  padding: 1.5rem;
  color: #475569;
  font-style: italic;
}

/* ── Scrollbar styling ───────────────────────────────────────────────────── */
.ntp-scroll::-webkit-scrollbar { width: 6px; height: 6px; }
.ntp-scroll::-webkit-scrollbar-track { background: #0f172a; }
.ntp-scroll::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
.ntp-scroll::-webkit-scrollbar-thumb:hover { background: #475569; }
</style>
