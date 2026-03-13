<template>
  <div class="knowledge-graph">
    <!-- Toolbar -->
    <div class="graph-toolbar">
      <div class="toolbar-group">
        <select v-model="graphType" @change="loadGraph" class="graph-select">
          <option value="knowledge">Knowledge Graph</option>
          <option value="citation">Citation Network</option>
          <option value="taxonomy">Taxonomy</option>
        </select>
      </div>

      <div class="toolbar-group">
        <button class="tool-btn" @click="applyLayout('cose')" title="Force layout">Force</button>
        <button class="tool-btn" @click="applyLayout('breadthfirst')" title="Hierarchical">Tree</button>
        <button class="tool-btn" @click="applyLayout('circle')" title="Circular">Circle</button>
        <button class="tool-btn" @click="applyLayout('concentric')" title="Concentric">Rings</button>
      </div>

      <div class="toolbar-group">
        <input
          v-model="searchQuery"
          placeholder="Search nodes…"
          class="search-input"
          @input="highlightSearch"
        />
      </div>

      <div class="toolbar-group">
        <button class="tool-btn" @click="fitGraph">Fit</button>
        <button class="tool-btn" @click="resetGraph">Reset</button>
      </div>

      <div class="node-type-filters">
        <label
          v-for="(color, type) in NODE_COLORS"
          :key="type"
          class="type-filter"
        >
          <input
            type="checkbox"
            :checked="visibleTypes.has(type)"
            @change="toggleType(type)"
          />
          <span class="type-dot" :style="{ background: color }"></span>
          {{ type }}
        </label>
      </div>
    </div>

    <!-- Graph canvas -->
    <div ref="cyContainer" class="cy-container"></div>

    <!-- Loading overlay -->
    <div v-if="loading" class="loading-overlay">Loading graph…</div>

    <!-- Node info panel -->
    <transition name="slide">
      <div v-if="selectedNode" class="node-info-panel">
        <div class="node-info-header">
          <span class="node-label">{{ selectedNode.label }}</span>
          <button class="close-btn" @click="selectedNode = null">✕</button>
        </div>

        <div class="node-info-body">
          <div v-for="(value, key) in filteredNodeData" :key="key" class="info-row">
            <span class="info-key">{{ key }}</span>
            <span class="info-value">{{ value }}</span>
          </div>
        </div>

        <div class="node-actions">
          <button class="action-btn" @click="expandNode(selectedNode.id)">
            Expand neighbors
          </button>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import cytoscape, { type Core, type LayoutOptions } from 'cytoscape'
import api from '@/utils/api'

const NODE_COLORS: Record<string, string> = {
  taxon: '#4ade80',
  document: '#60a5fa',
  concept: '#f97316',
  fact: '#a78bfa',
  chunk: '#94a3b8',
  default: '#e5e7eb',
}

interface SelectedNode {
  id: string
  label: string
  type: string
  data: Record<string, unknown>
}

const cyContainer = ref<HTMLElement>()
let cy: Core | null = null

const graphType = ref('knowledge')
const loading = ref(false)
const selectedNode = ref<SelectedNode | null>(null)
const searchQuery = ref('')
const visibleTypes = ref(new Set(Object.keys(NODE_COLORS)))

const LAYOUT_CONFIGS: Record<string, LayoutOptions> = {
  cose: { name: 'cose', animate: true, animationDuration: 500 } as LayoutOptions,
  breadthfirst: { name: 'breadthfirst', directed: true, animate: true } as LayoutOptions,
  circle: { name: 'circle', animate: true } as LayoutOptions,
  concentric: { name: 'concentric', animate: true } as LayoutOptions,
}

const HIDDEN_KEYS = new Set(['id', 'color', 'size', 'type'])

const filteredNodeData = computed(() => {
  if (!selectedNode.value) return {}
  return Object.fromEntries(
    Object.entries(selectedNode.value.data).filter(([k]) => !HIDDEN_KEYS.has(k))
  )
})

onMounted(() => {
  cy = cytoscape({
    container: cyContainer.value,
    elements: [],
    style: [
      {
        selector: 'node',
        style: {
          label: 'data(label)',
          'background-color': 'data(color)',
          width: 'data(size)',
          height: 'data(size)',
          'font-size': '10px',
          'text-valign': 'bottom',
          'text-margin-y': 4,
          color: '#374151',
          'text-outline-color': '#fff',
          'text-outline-width': 2,
        },
      },
      {
        selector: 'edge',
        style: {
          width: 2,
          'line-color': '#d1d5db',
          'target-arrow-color': '#d1d5db',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          label: 'data(label)',
          'font-size': '8px',
          color: '#9ca3af',
        },
      },
      {
        selector: 'node.highlighted',
        style: {
          'border-width': 3,
          'border-color': '#f59e0b',
          'border-opacity': 1,
        },
      },
      {
        selector: 'node.selected',
        style: {
          'border-width': 3,
          'border-color': '#3b82f6',
        },
      },
      {
        selector: 'node.dimmed',
        style: { opacity: 0.2 },
      },
      {
        selector: 'edge.dimmed',
        style: { opacity: 0.1 },
      },
    ],
    layout: { name: 'cose' } as LayoutOptions,
    minZoom: 0.1,
    maxZoom: 4,
  })

  cy.on('tap', 'node', (evt) => {
    const node = evt.target
    cy?.nodes().removeClass('selected')
    node.addClass('selected')
    selectedNode.value = {
      id: node.id(),
      label: node.data('label'),
      type: node.data('type'),
      data: node.data(),
    }
  })

  cy.on('tap', (evt) => {
    if (evt.target === cy) {
      cy?.nodes().removeClass('selected')
      selectedNode.value = null
    }
  })

  loadGraph()
})

onUnmounted(() => {
  cy?.destroy()
})

async function loadGraph() {
  loading.value = true
  try {
    const { data } = await api.get(`/graph/${graphType.value}?depth=2`)
    cy?.elements().remove()
    cy?.add(data.elements.nodes)
    cy?.add(data.elements.edges)
    applyLayout('cose')
    applyTypeFilter()
  } catch {
    // graph service may not have data yet — show empty canvas silently
  } finally {
    loading.value = false
  }
}

async function expandNode(nodeId: string) {
  try {
    const { data } = await api.get(`/graph/expand?node=${nodeId}&hops=1`)
    cy?.add(data.elements.nodes)
    cy?.add(data.elements.edges)
    applyLayout('cose')
  } catch {
    // ignore
  }
}

function applyLayout(name: string) {
  const config = LAYOUT_CONFIGS[name] || LAYOUT_CONFIGS.cose
  cy?.layout(config).run()
}

function fitGraph() {
  cy?.fit()
}

function resetGraph() {
  cy?.reset()
}

function highlightSearch() {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) {
    cy?.elements().removeClass('highlighted dimmed')
    return
  }
  cy?.nodes().forEach((node) => {
    const label = (node.data('label') as string || '').toLowerCase()
    if (label.includes(q)) {
      node.addClass('highlighted')
      node.removeClass('dimmed')
    } else {
      node.addClass('dimmed')
      node.removeClass('highlighted')
    }
  })
  cy?.edges().addClass('dimmed')
}

function toggleType(type: string) {
  if (visibleTypes.value.has(type)) {
    visibleTypes.value.delete(type)
  } else {
    visibleTypes.value.add(type)
  }
  applyTypeFilter()
}

function applyTypeFilter() {
  cy?.nodes().forEach((node) => {
    const t = node.data('type') as string || 'default'
    if (visibleTypes.value.has(t)) {
      node.style('display', 'element')
    } else {
      node.style('display', 'none')
    }
  })
}
</script>

<style scoped>
.knowledge-graph {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.graph-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.graph-select {
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 0.25rem 0.5rem;
  font-size: 0.8rem;
  background: white;
}

.tool-btn {
  background: white;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 0.25rem 0.5rem;
  font-size: 0.78rem;
  cursor: pointer;
  color: #374151;
}

.tool-btn:hover { background: #f3f4f6; }

.search-input {
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 0.25rem 0.5rem;
  font-size: 0.8rem;
  width: 140px;
}

.node-type-filters {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-left: auto;
}

.type-filter {
  display: flex;
  align-items: center;
  gap: 0.2rem;
  font-size: 0.75rem;
  cursor: pointer;
  color: #4b5563;
}

.type-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.cy-container {
  flex: 1;
  background: #fafafa;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.75);
  font-size: 0.9rem;
  color: #6b7280;
}

.node-info-panel {
  position: absolute;
  top: 60px;
  right: 12px;
  width: 240px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  z-index: 10;
}

.node-info-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  background: #f3f4f6;
  border-bottom: 1px solid #e5e7eb;
  font-weight: 600;
  font-size: 0.85rem;
}

.close-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: #9ca3af;
  font-size: 0.9rem;
}

.node-info-body {
  padding: 0.5rem 0.75rem;
  max-height: 240px;
  overflow-y: auto;
  font-size: 0.78rem;
}

.info-row {
  display: flex;
  gap: 0.5rem;
  padding: 0.2rem 0;
  border-bottom: 1px solid #f3f4f6;
}

.info-key {
  color: #6b7280;
  min-width: 70px;
  font-weight: 500;
}

.info-value {
  color: #111827;
  word-break: break-all;
}

.node-actions {
  padding: 0.5rem 0.75rem;
  border-top: 1px solid #e5e7eb;
}

.action-btn {
  width: 100%;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 4px;
  padding: 0.35rem;
  font-size: 0.78rem;
  cursor: pointer;
}

.action-btn:hover { background: #2563eb; }

.slide-enter-active,
.slide-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateX(10px);
}
</style>
