<template>
  <div class="node-table-panel">
    <!-- Toolbar -->
    <div class="ntp-toolbar">
      <select v-model="filterType" class="ntp-select" title="Filter by node type" aria-label="Filter by node type">
        <option value="">All types</option>
        <option v-for="t in uniqueTypes" :key="t" :value="t">{{ t.replace(/_/g, ' ') }}</option>
      </select>
      <input
        v-model="searchText"
        class="ntp-search"
        placeholder="Search label…"
        aria-label="Search node labels"
        spellcheck="false"
      />
      <span class="ntp-count">{{ filteredNodes.length }} / {{ nodes.length }}</span>
    </div>

    <!-- Table. Virtualised: only the rows in view (plus a few either side) are
         rendered, between two spacer rows that stand in for the rest — a graph
         can have tens of thousands of nodes. Rows have one fixed height.

         Keyboard: the table is a single tab stop (a grid with an active row,
         announced through aria-activedescendant); arrows/Page/Home/End move,
         Enter or Space selects. -->
    <div ref="scrollEl" class="ntp-scroll" @scroll.passive="onScroll">
      <table
        ref="tableEl"
        class="ntp-table"
        role="grid"
        aria-label="Graph nodes"
        :aria-rowcount="filteredNodes.length + 1"
        :aria-activedescendant="activeRowId"
        tabindex="0"
        :style="{ '--ntp-row-h': `${ROW_HEIGHT}px` }"
        @keydown="onKeydown"
      >
        <thead ref="theadEl">
          <tr aria-rowindex="1">
            <th class="col-type" :aria-sort="ariaSort('node_type')">
              <button type="button" class="ntp-sort" @click="setSort('node_type')">Type<SortIcon :col="'node_type'" :sortKey="sortKey" :sortDir="sortDir" /></button>
            </th>
            <th class="col-label" :aria-sort="ariaSort('label')">
              <button type="button" class="ntp-sort" @click="setSort('label')">Label<SortIcon :col="'label'" :sortKey="sortKey" :sortDir="sortDir" /></button>
            </th>
            <th class="col-deg" :aria-sort="ariaSort('degree')">
              <button type="button" class="ntp-sort" @click="setSort('degree')">Deg<SortIcon :col="'degree'" :sortKey="sortKey" :sortDir="sortDir" /></button>
            </th>
            <th class="col-sup" :aria-sort="ariaSort('supports')" title="Supporting edges">
              <button type="button" class="ntp-sort" @click="setSort('supports')">Sup<SortIcon :col="'supports'" :sortKey="sortKey" :sortDir="sortDir" /></button>
            </th>
            <th class="col-opp" :aria-sort="ariaSort('opposes')" title="Opposing edges">
              <button type="button" class="ntp-sort" @click="setSort('opposes')">Opp<SortIcon :col="'opposes'" :sortKey="sortKey" :sortDir="sortDir" /></button>
            </th>
            <th class="col-eid">Entity ID</th>
            <th class="col-props">Properties</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="padTop > 0" class="ntp-spacer ntp-spacer--top" aria-hidden="true" :style="{ height: `${padTop}px` }">
            <td colspan="7" />
          </tr>
          <tr
            v-for="(node, i) in visibleNodes"
            :id="rowId(range.start + i)"
            :key="node._id"
            class="ntp-row"
            :class="{
              'row-selected': selectedNode?._id === node._id,
              'row-active': range.start + i === activeIndex,
            }"
            :aria-rowindex="range.start + i + 2"
            :aria-selected="selectedNode?._id === node._id"
            @click="selectAt(range.start + i)"
          >
            <td>
              <span class="type-badge" :class="`type-${node.node_type.replace(/_/g, '-')}`">
                {{ node.node_type.replace(/_/g, ' ') }}
              </span>
            </td>
            <td class="col-label-cell" :title="node.label">{{ node.label }}</td>
            <td class="col-deg-cell">{{ node.degree ?? '—' }}</td>
            <td class="col-sup-cell">{{ node.supports ?? '—' }}</td>
            <td class="col-opp-cell">{{ node.opposes ?? '—' }}</td>
            <td class="col-eid-cell mono" :title="node.entity_id">{{ node.entity_id || '—' }}</td>
            <td class="col-props-cell" :title="formatPropsLong(node)">{{ formatProps(node) }}</td>
          </tr>
          <tr v-if="padBottom > 0" class="ntp-spacer ntp-spacer--bottom" aria-hidden="true" :style="{ height: `${padBottom}px` }">
            <td colspan="7" />
          </tr>
          <tr v-if="filteredNodes.length === 0">
            <td colspan="7" class="ntp-empty">No nodes match the current filter</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script lang="ts">
/** Row height in px that the CSS gives every row (see .ntp-row). The rendered
 *  height is measured once and used instead if it differs (zoom, fonts). */
export const ROW_HEIGHT = 26
/** Rows rendered beyond each edge of the viewport, so fast scrolling stays filled. */
export const OVERSCAN = 8
</script>

<script setup lang="ts">
import { ref, computed, defineComponent, h, onBeforeUnmount, onMounted, onUpdated, useId, watch } from 'vue'
import type { GraphNode } from '@/utils/kbApi'

// ── Props / Emits ────────────────────────────────────────────────────────────

const props = defineProps<{
  nodes: GraphNode[]
  selectedNode: GraphNode | null
}>()

const emit = defineEmits<{
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
    // aria-hidden: the header's aria-sort already says which way it sorts.
    return () => {
      if (p.col !== p.sortKey) return h('span', { class: 'sort-icon sort-none', 'aria-hidden': 'true' }, ' ⇅')
      return h('span', { class: 'sort-icon sort-active', 'aria-hidden': 'true' }, p.sortDir === 'asc' ? ' ↑' : ' ↓')
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
  const NUMERIC_KEYS = new Set(['degree', 'supports', 'opposes'])
  list = [...list].sort((a, b) => {
    let av: any = (a as any)[key] ?? ''
    let bv: any = (b as any)[key] ?? ''
    if (NUMERIC_KEYS.has(key)) {
      av = (a as any)[key] ?? -1
      bv = (b as any)[key] ?? -1
    }
    if (av < bv) return -1 * dir
    if (av > bv) return  1 * dir
    return 0
  })

  return list
})

// ── Virtual window ───────────────────────────────────────────────────────────

/** Used until the scroll box can be measured (and in tests, where it can't). */
const FALLBACK_VIEWPORT = 240

const scrollEl  = ref<HTMLElement | null>(null)
const tableEl   = ref<HTMLTableElement | null>(null)
const theadEl   = ref<HTMLElement | null>(null)
const scrollTop = ref(0)
const viewportH = ref(FALLBACK_VIEWPORT)
const rowH      = ref(ROW_HEIGHT)

const range = computed(() => {
  const n = filteredNodes.value.length
  const first = Math.floor(scrollTop.value / rowH.value)
  const inView = Math.ceil(viewportH.value / rowH.value)
  const start = Math.min(n, Math.max(0, first - OVERSCAN))
  const end = Math.min(n, Math.max(start, first + inView + OVERSCAN))
  return { start, end }
})

const visibleNodes = computed(() => filteredNodes.value.slice(range.value.start, range.value.end))
const padTop       = computed(() => range.value.start * rowH.value)
const padBottom    = computed(() => (filteredNodes.value.length - range.value.end) * rowH.value)

function onScroll() {
  if (scrollEl.value) scrollTop.value = scrollEl.value.scrollTop
}

function measureViewport() {
  const h = scrollEl.value?.clientHeight ?? 0
  viewportH.value = h > 0 ? h : FALLBACK_VIEWPORT
}

// The spacers are only right if rowH is the real row pitch, so take it from a
// rendered row once there is one. (0 where nothing is laid out, e.g. jsdom.)
let rowMeasured = false
function measureRow() {
  if (rowMeasured) return
  const row = tableEl.value?.querySelector('tr.ntp-row')
  const h = row?.getBoundingClientRect().height ?? 0
  if (h <= 0) return
  rowMeasured = true
  if (Math.abs(h - rowH.value) > 0.25) rowH.value = h
}

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  measureViewport()
  measureRow()
  if (typeof ResizeObserver !== 'undefined' && scrollEl.value) {
    resizeObserver = new ResizeObserver(measureViewport)
    resizeObserver.observe(scrollEl.value)
  }
})

onUpdated(measureRow)

onBeforeUnmount(() => { resizeObserver?.disconnect(); resizeObserver = null })

// ── Active row (keyboard) and selection ──────────────────────────────────────

const idPrefix = `ntp-${useId()}`
const activeIndex = ref(0)

function rowId(index: number): string {
  return `${idPrefix}-r${index}`
}

/** Only a rendered row can be the active descendant. */
const activeRowId = computed(() => {
  const { start, end } = range.value
  const i = activeIndex.value
  return i >= start && i < end ? rowId(i) : undefined
})

function selectAt(index: number) {
  const node = filteredNodes.value[index]
  if (!node) return
  activeIndex.value = index
  emit('select', node)
}

/** Scroll the minimum needed for row `index` to be fully visible below the sticky header. */
function scrollRowIntoView(index: number) {
  const el = scrollEl.value
  if (!el) return
  const headerH = theadEl.value?.getBoundingClientRect().height ?? 0
  const visibleH = viewportH.value - headerH
  const top = index * rowH.value
  if (top < el.scrollTop) el.scrollTop = top
  else if (top + rowH.value > el.scrollTop + visibleH) el.scrollTop = top + rowH.value - visibleH
  scrollTop.value = el.scrollTop
}

function setActive(index: number) {
  activeIndex.value = index
  scrollRowIntoView(index)
}

function onKeydown(ev: KeyboardEvent) {
  const n = filteredNodes.value.length
  if (!n || ev.target !== tableEl.value) return
  const page = Math.max(1, Math.floor(viewportH.value / rowH.value) - 1)
  const at = Math.min(activeIndex.value, n - 1)
  let next: number
  switch (ev.key) {
    case 'ArrowDown': next = at + 1; break
    case 'ArrowUp':   next = at - 1; break
    case 'PageDown':  next = at + page; break
    case 'PageUp':    next = at - page; break
    case 'Home':      next = 0; break
    case 'End':       next = n - 1; break
    case 'Enter':
    case ' ':
      ev.preventDefault()
      selectAt(at)
      return
    default:
      return
  }
  ev.preventDefault()
  setActive(Math.min(n - 1, Math.max(0, next)))
}

// Keep the active row on the selected node — after a click on the canvas, or
// when filtering/sorting reorders the list — so keyboard navigation resumes
// from it. This does not scroll: the table stays where the user left it.
watch([() => props.selectedNode?._id, filteredNodes], ([id]) => {
  const i = id ? filteredNodes.value.findIndex(n => n._id === id) : -1
  if (i >= 0) activeIndex.value = i
  else activeIndex.value = Math.min(activeIndex.value, Math.max(0, filteredNodes.value.length - 1))
})

// ── Helpers ──────────────────────────────────────────────────────────────────

function setSort(col: string) {
  if (sortKey.value === col) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = col
    sortDir.value = (col === 'degree' || col === 'supports' || col === 'opposes') ? 'desc' : 'asc'
  }
}

function ariaSort(col: string): 'ascending' | 'descending' | 'none' {
  if (sortKey.value !== col) return 'none'
  return sortDir.value === 'asc' ? 'ascending' : 'descending'
}

const PROP_KEYS = ['doi', 'year', 'authors', 'journal', 'rank', 'tax_id', 'confidence', 'status', 'category']

function formatProps(node: GraphNode): string {
  const parts: string[] = []
  const props = node.properties ?? {}
  for (const k of PROP_KEYS) {
    const v = props[k]
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
  const props = node.properties ?? {}
  for (const k of PROP_KEYS) {
    const v = props[k]
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
.ntp-select:focus { border-color: var(--app-primary); }

.ntp-search {
  flex: 1;
  min-width: 0;
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
.ntp-search:focus { border-color: var(--app-primary); }

.ntp-count {
  margin-left: auto;
  font-size: 0.65rem;
  color: #475569;
  white-space: nowrap;
}

/* ── Scroll container ────────────────────────────────────────────────────── */
.ntp-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: auto;
}

/* ── Table ───────────────────────────────────────────────────────────────── */
.ntp-table {
  width: 100%;
  min-width: 720px; /* the fixed columns' share; narrower screens scroll sideways */
  border-collapse: collapse;
  font-size: 0.72rem;
  table-layout: fixed;
}
.ntp-table:focus { outline: none; }
.ntp-table:focus-visible { box-shadow: inset 0 0 0 2px #60a5fa; }

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
  user-select: none;
  white-space: nowrap;
}
.ntp-table th:hover { color: #94a3b8; }

/* Sort control: a real button, styled as the header text it replaces. */
.ntp-sort {
  font: inherit;
  color: inherit;
  text-transform: inherit;
  letter-spacing: inherit;
  text-align: inherit;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
}
.ntp-sort:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; border-radius: 2px; }

.ntp-table td {
  padding: 0.3rem 0.6rem;
  color: #cbd5e1;
  border-bottom: 1px solid #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

/* One fixed height for every data row (single line, clipped), which is what
   lets the spacer rows stand in for the unrendered ones. */
.ntp-table tbody tr.ntp-row td {
  height: var(--ntp-row-h);
  padding-top: 0;
  padding-bottom: 0;
  line-height: 1;
}

.ntp-table tbody tr.ntp-spacer td {
  padding: 0;
  border: none;
}

.ntp-table tbody tr.ntp-row {
  cursor: pointer;
  transition: background 0.1s;
}
.ntp-table tbody tr.ntp-row:hover { background: #263348; }
.ntp-table tbody tr.ntp-row.row-selected {
  background: #1e3a5f;
  border-left: 2px solid var(--app-primary);
}
/* The keyboard's current row, while the table has focus. */
.ntp-table:focus-visible tbody tr.row-active {
  outline: 1px dashed #60a5fa;
  outline-offset: -1px;
}

/* ── Column widths ───────────────────────────────────────────────────────── */
.col-type  { width: 130px; }
.col-label { width: auto;  }
.col-deg   { width: 48px; text-align: right; }
.col-sup   { width: 48px; text-align: right; }
.col-opp   { width: 48px; text-align: right; }
.col-eid   { width: 110px; }
.col-props { width: 240px; }

.col-deg-cell   { text-align: right; color: #94a3b8; }
.col-sup-cell   { text-align: right; color: #34e778; }
.col-opp-cell   { text-align: right; color: #ff7a7a; }
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
.type-badge.type-document           { background: #1d4ed8; color: var(--app-primary-line); }
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

/* ── Narrow screens: don't let the table take the whole graph column ────── */
@media (max-width: 900px) {
  .node-table-panel { height: 40%; min-height: 160px; }
}

@media (pointer: coarse) {
  .ntp-select,
  .ntp-search { min-height: 36px; }
}
</style>
