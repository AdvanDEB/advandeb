<template>
  <div class="app">
    <!-- Toolbar -->
    <header class="toolbar">
      <span class="brand">AdvanDEB KB</span>

      <select v-model="selectedSchemaId" class="toolbar-select" @change="onSchemaChange">
        <option value="" disabled>schema ▾</option>
        <option v-for="s in schemas" :key="s._id" :value="s._id">{{ s.name }}</option>
      </select>

      <button
        class="toolbar-btn"
        :class="{ active: is3D }"
        @click="is3D = !is3D"
        title="Toggle 3D view"
      >3D</button>

      <!-- Color mode toggle (Task 1) -->
      <div class="color-mode-ctrl">
        <span class="ctrl-label">color</span>
        <button
          class="toolbar-btn"
          :class="{ active: colorMode === 'type' }"
          @click="colorMode = 'type'"
          title="Color nodes by type"
        >type</button>
        <button
          class="toolbar-btn"
          :class="{ active: colorMode === 'cluster' }"
          @click="colorMode = 'cluster'"
          title="Color nodes by cluster"
        >cluster</button>
      </div>

      <span v-if="graphStats" class="stats">
        {{ graphStats.nodes.toLocaleString() }} nodes &nbsp;
        {{ graphStats.edges.toLocaleString() }} edges
      </span>

      <div v-if="graphStats" class="gravity-ctrl">
        <span class="ctrl-label">confidence ≥</span>
        <input
          type="range" min="0" max="1" step="0.05"
          v-model.number="minWeight"
          class="slider"
          title="Hide edges below this confidence threshold"
        />
        <span class="slider-val">{{ Math.round(minWeight * 100) }}%</span>
      </div>

      <span class="spacer"></span>

      <button
        class="toolbar-btn"
        :disabled="!selectedSchemaId || rebuilding"
        @click="rebuildGraph"
        title="Rebuild graph from source data"
      >{{ rebuilding ? '↺ Building…' : '↺ Rebuild' }}</button>

      <button
        class="toolbar-btn"
        :class="{ active: activeDrawer === 'ingestion' }"
        @click="toggleDrawer('ingestion')"
        title="Batch ingestion"
      >≡ Ingestion</button>

      <button
        class="toolbar-btn"
        :class="{ active: activeDrawer === 'database' }"
        @click="toggleDrawer('database')"
        title="Database inspector"
      >⬡ DB</button>

      <button
        class="toolbar-btn"
        :class="{ active: activeDrawer === 'filesystem' }"
        @click="toggleDrawer('filesystem')"
        title="Filesystem browser"
      >📁 FS</button>

      <button
        class="toolbar-btn"
        :class="{ active: activeDrawer === 'kgbuilder' }"
        @click="toggleDrawer('kgbuilder')"
        title="KG builder — link documents to taxa"
      >⬡ KG</button>
    </header>

    <!-- Filter bar — shown only when a graph is loaded -->
    <div v-if="graphStats && (presentNodeTypes.length || presentEdgeTypes.length)" class="filter-bar">
      <div v-if="presentNodeTypes.length" class="filter-group">
        <span class="filter-label">nodes</span>
        <label
          v-for="type in presentNodeTypes"
          :key="'n-' + type"
          class="filter-chip"
          :title="type"
        >
          <input
            type="checkbox"
            :checked="!hiddenNodeTypes.has(type)"
            @change="toggleNodeType(type)"
          />
          <span class="chip-dot" :style="{ background: nodeColors[type] || '#7f8c8d' }"></span>
          <span class="chip-label">{{ type }}</span>
        </label>
      </div>

      <div v-if="presentEdgeTypes.length" class="filter-group edge-group">
        <span class="filter-label">edges</span>
        <label
          v-for="type in presentEdgeTypes"
          :key="'e-' + type"
          class="filter-chip"
          :title="type"
        >
          <input
            type="checkbox"
            :checked="!hiddenEdgeTypes.has(type)"
            @change="toggleEdgeType(type)"
          />
          <span class="chip-dot edge-dot" :style="{ background: edgeColors[type] || '#cccccc' }"></span>
          <span class="chip-label">{{ type }}</span>
        </label>
      </div>

      <!-- LOD hint — only shown in 2D mode -->
      <div v-if="!is3D && graphStats" class="filter-group lod-hint">
        <span class="filter-label">zoom for</span>
        <span class="lod-pill fact-pill">facts</span>
        <span class="lod-pill doc-pill">documents</span>
      </div>

      <!-- Cluster chips — visible only when colorMode === 'cluster' (Task 2) -->
      <div v-if="colorMode === 'cluster' && presentClusters.length" class="filter-group cluster-group">
        <span class="filter-label">clusters</span>
        <label
          v-for="c in presentClusters"
          :key="'c-' + c.id"
          class="filter-chip"
          :title="'Cluster ' + c.id"
        >
          <input
            type="checkbox"
            :checked="!hiddenClusters.has(c.id)"
            @change="toggleCluster(c.id)"
          />
          <span class="chip-dot" :style="{ background: c.color }"></span>
          <span class="chip-label">{{ c.id }}</span>
        </label>
      </div>
    </div>

    <!-- Schema-specific expand controls (Task 3) -->
    <div v-if="graphStats && schemaName" class="schema-controls">
      <span class="ctrl-label">expand</span>
      <!-- taxonomical -->
      <template v-if="schemaName === 'taxonomical'">
        <button class="toolbar-btn" @click="expandType('phylum')">phylum</button>
        <button class="toolbar-btn" @click="expandType('class')">class</button>
        <button class="toolbar-btn" @click="expandType('order')">order</button>
        <button class="toolbar-btn" @click="expandType('family')">family</button>
        <button class="toolbar-btn" @click="expandType('genus')">genus</button>
        <button class="toolbar-btn" @click="expandType('species')">species</button>
      </template>
      <!-- sf_support -->
      <template v-else-if="schemaName === 'sf_support'">
        <button class="toolbar-btn" @click="expandType('stylized_fact')">all facts</button>
        <button class="toolbar-btn" @click="expandType('document')">all documents</button>
      </template>
      <!-- knowledge_graph -->
      <template v-else-if="schemaName === 'knowledge_graph'">
        <button class="toolbar-btn" @click="expandType('stylized_fact')">SFs</button>
        <button class="toolbar-btn" @click="expandType('fact')">facts</button>
        <button class="toolbar-btn" @click="expandType('document')">documents</button>
        <button class="toolbar-btn" @click="expandType('species')">species</button>
      </template>
      <!-- citation -->
      <template v-else-if="schemaName === 'citation'">
        <button class="toolbar-btn" @click="expandType('document')">all documents</button>
      </template>
    </div>

    <!-- Canvas area -->
    <div class="canvas-area">
      <SearchOverlay @search="onSearch" />
      <GraphCanvas
        ref="graphCanvasRef"
        :schemaId="selectedSchemaId"
        :is3D="is3D"
        :colorMode="colorMode"
        :minWeight="minWeight"
        @node-selected="onNodeSelected"
        @node-deselected="selectedNode = null"
        @stats-updated="onStatsUpdated"
        @schemas-loaded="onSchemasLoaded"
        @graph-types-updated="onGraphTypesUpdated"
      />
      <NodeInspector
        v-if="selectedNode"
        :node="selectedNode"
        @close="selectedNode = null"
        @expand-node="onExpandNode"
      />
    </div>

    <!-- Bottom sheet drawer -->
    <template v-if="activeDrawer">
      <div class="drawer-backdrop" @click="activeDrawer = null"></div>
      <div class="drawer">
        <IngestionDrawer   v-if="activeDrawer === 'ingestion'" />
        <DatabaseDrawer    v-if="activeDrawer === 'database'" />
        <FilesystemDrawer  v-if="activeDrawer === 'filesystem'" />
        <KGBuilderDrawer   v-if="activeDrawer === 'kgbuilder'" />
      </div>
    </template>

    <!-- Toast -->
    <transition name="toast-fade">
      <div v-if="toast" class="toast" :class="toast.type">{{ toast.message }}</div>
    </transition>
  </div>
</template>

<script>
import { ref, reactive, computed } from 'vue'
import GraphCanvas, { NODE_COLORS, EDGE_COLORS } from '@/components/kb/GraphCanvas.vue'
import NodeInspector  from '@/components/kb/NodeInspector.vue'
import SearchOverlay  from '@/components/kb/SearchOverlay.vue'
import IngestionDrawer from '@/components/kb/IngestionDrawer.vue'
import DatabaseDrawer  from '@/components/kb/DatabaseDrawer.vue'
import FilesystemDrawer from '@/components/kb/FilesystemDrawer.vue'
import KGBuilderDrawer  from '@/components/kb/KGBuilderDrawer.vue'
import { vizAPI } from '@/utils/kbApi'

export default {
  name: 'KnowledgeBuilderView',
  components: {
    GraphCanvas, NodeInspector, SearchOverlay,
    IngestionDrawer, DatabaseDrawer, FilesystemDrawer, KGBuilderDrawer,
  },
  setup() {
    const schemas          = ref([])
    const selectedSchemaId = ref('')
    const is3D             = ref(false)
    const graphStats       = ref(null)
    const selectedNode     = ref(null)
    const activeDrawer     = ref(null)
    const rebuilding       = ref(false)
    const toast            = ref(null)
    const graphCanvasRef   = ref(null)
    const minWeight        = ref(0)   // confidence threshold 0–1

    // Task 1: color mode toggle
    const colorMode = ref('type')

    // Filter state — populated after graph loads
    const presentNodeTypes = ref([])
    const presentEdgeTypes = ref([])
    const hiddenNodeTypes  = reactive(new Set())
    const hiddenEdgeTypes  = reactive(new Set())

    // Task 2: cluster filter state
    const presentClusters  = ref([])
    const hiddenClusters   = reactive(new Set())

    // Color maps exposed to template
    const nodeColors = NODE_COLORS
    const edgeColors = EDGE_COLORS

    // Task 3: schema name computed from selected schema
    const schemaName = computed(() => {
      const s = schemas.value.find(s => s._id === selectedSchemaId.value)
      return s ? s.name : ''
    })

    function applyDegreeGravity() {
      graphCanvasRef.value?.relayout(degreeGravity.value)
    }

    function onSchemasLoaded(list) {
      schemas.value = list
    }

    function onSchemaChange() {
      selectedNode.value = null
      graphStats.value   = null
      degreeGravity.value = 0
      minWeight.value     = 0
      presentNodeTypes.value = []
      presentEdgeTypes.value = []
      hiddenNodeTypes.clear()
      hiddenEdgeTypes.clear()
      presentClusters.value = []
      hiddenClusters.clear()
    }

    function onLayoutChange() {
      // GraphCanvas watches selectedLayout via prop — no extra action needed
    }

    function onNodeSelected(node) {
      selectedNode.value = node
    }

    function onStatsUpdated(stats) {
      graphStats.value = stats
      // Refresh cluster list after graph loads (Task 2)
      presentClusters.value = graphCanvasRef.value?.getClusters() || []
    }

    function onGraphTypesUpdated({ nodeTypes, edgeTypes }) {
      presentNodeTypes.value = nodeTypes
      presentEdgeTypes.value = edgeTypes
    }

    function onSearch(query) {
      graphCanvasRef.value?.applySearch(query)
    }

    function toggleDrawer(name) {
      activeDrawer.value = activeDrawer.value === name ? null : name
    }

    function toggleNodeType(type) {
      if (hiddenNodeTypes.has(type)) {
        hiddenNodeTypes.delete(type)
        graphCanvasRef.value?.setNodeTypeVisible(type, true)
      } else {
        hiddenNodeTypes.add(type)
        graphCanvasRef.value?.setNodeTypeVisible(type, false)
      }
    }

    function toggleEdgeType(type) {
      if (hiddenEdgeTypes.has(type)) {
        hiddenEdgeTypes.delete(type)
        graphCanvasRef.value?.setEdgeTypeVisible(type, true)
      } else {
        hiddenEdgeTypes.add(type)
        graphCanvasRef.value?.setEdgeTypeVisible(type, false)
      }
    }

    // Task 2: toggle cluster visibility
    function toggleCluster(id) {
      if (hiddenClusters.has(id)) {
        hiddenClusters.delete(id)
        graphCanvasRef.value?.setClusterVisible(id, true)
      } else {
        hiddenClusters.add(id)
        graphCanvasRef.value?.setClusterVisible(id, false)
      }
    }

    // Task 3: expand by type
    function expandType(nodeType) {
      graphCanvasRef.value?.expandType(nodeType)
    }

    // Task 4: expand node by ID (called from NodeInspector's expand-node event)
    function onExpandNode(id) {
      graphCanvasRef.value?.expandNodeById(id)
    }

    async function rebuildGraph() {
      if (!selectedSchemaId.value) return
      rebuilding.value = true
      try {
        const res = await vizAPI.rebuildSchema(selectedSchemaId.value, {})
        const { nodes, edges } = res.data
        showToast(`Rebuilt: ${nodes} nodes, ${edges} edges`, 'success')
        // Reload the graph
        const prev = selectedSchemaId.value
        selectedSchemaId.value = ''
        await new Promise(r => setTimeout(r, 50))
        selectedSchemaId.value = prev
      } catch (e) {
        showToast(e.response?.data?.detail || 'Rebuild failed', 'error')
      } finally {
        rebuilding.value = false
      }
    }

    let toastTimer = null
    function showToast(message, type = 'success') {
      toast.value = { message, type }
      if (toastTimer) clearTimeout(toastTimer)
      toastTimer = setTimeout(() => { toast.value = null }, 4000)
    }

    return {
      schemas, selectedSchemaId, selectedLayout, is3D,
      graphStats, selectedNode, activeDrawer, rebuilding, toast,
      graphCanvasRef, degreeGravity, minWeight,
      colorMode,
      presentNodeTypes, presentEdgeTypes, hiddenNodeTypes, hiddenEdgeTypes,
      presentClusters, hiddenClusters,
      nodeColors, edgeColors,
      schemaName,
      onSchemasLoaded, onSchemaChange, onLayoutChange,
      onNodeSelected, onStatsUpdated, onGraphTypesUpdated, onSearch,
      toggleDrawer, rebuildGraph,
      applyDegreeGravity,
      toggleNodeType, toggleEdgeType,
      toggleCluster,
      expandType,
      onExpandNode,
    }
  },
}
</script>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ── Toolbar ───────────────────────────────────────────────────────────────── */
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 48px;
  padding: 0 12px;
  background: #1a1f2e;
  color: #e0e0e0;
  flex-shrink: 0;
  overflow: hidden;
}

.brand {
  font-weight: 700;
  font-size: 14px;
  color: #fff;
  letter-spacing: 0.3px;
  white-space: nowrap;
  margin-right: 4px;
}

.toolbar-select {
  padding: 4px 8px;
  border: 1px solid #3a3f50;
  border-radius: 4px;
  background: #2a2f3e;
  color: #e0e0e0;
  font-size: 12px;
  cursor: pointer;
}
.toolbar-select:focus { outline: none; border-color: #4a90e2; }

.stats {
  font-size: 11px;
  color: #9aa;
  white-space: nowrap;
}

.partial-badge {
  font-size: 9px;
  color: #f59e0b;
  background: #1c1200;
  border: 1px solid #78350f;
  border-radius: 3px;
  padding: 1px 5px;
  vertical-align: middle;
  margin-left: 4px;
}

.spacer { flex: 1; }

.gravity-ctrl {
  display: flex;
  align-items: center;
  gap: 6px;
}

.color-mode-ctrl {
  display: flex;
  align-items: center;
  gap: 4px;
}

.ctrl-label {
  font-size: 10px;
  color: #7a8a9a;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.slider { width: 80px; accent-color: #4a90e2; cursor: pointer; }
.slider-val { font-size: 10px; color: #9aa; min-width: 28px; }

.apply-btn { padding: 4px 8px !important; font-size: 13px !important; }

.toolbar-btn {
  padding: 5px 11px;
  border: 1px solid #3a3f50;
  border-radius: 4px;
  background: #2a2f3e;
  color: #ccc;
  cursor: pointer;
  font-size: 12px;
  white-space: nowrap;
  transition: background 0.15s;
}
.toolbar-btn:hover:not(:disabled) { background: #3a4055; color: #fff; }
.toolbar-btn.active { background: #4a90e2; border-color: #4a90e2; color: #fff; }
.toolbar-btn:disabled { opacity: 0.5; cursor: default; }

/* ── Filter bar ────────────────────────────────────────────────────────────── */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 4px 12px;
  background: #12151f;
  border-bottom: 1px solid #2a2f3e;
  flex-shrink: 0;
  flex-wrap: wrap;
  min-height: 30px;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.edge-group {
  margin-left: 12px;
  padding-left: 12px;
  border-left: 1px solid #2a2f3e;
}

.cluster-group {
  margin-left: 12px;
  padding-left: 12px;
  border-left: 1px solid #2a2f3e;
}

.filter-label {
  font-size: 9px;
  color: #5a6a7a;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  white-space: nowrap;
  margin-right: 2px;
}

.filter-chip {
  display: flex;
  align-items: center;
  gap: 3px;
  cursor: pointer;
  white-space: nowrap;
}

.filter-chip input[type="checkbox"] {
  width: 11px;
  height: 11px;
  accent-color: #4a90e2;
  cursor: pointer;
  margin: 0;
}

.chip-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.edge-dot { border-radius: 2px; }

.chip-label {
  font-size: 10px;
  color: #8a9aaa;
  letter-spacing: 0.2px;
}

/* ── LOD hint pills ─────────────────────────────────────────────────────────── */
.lod-hint { margin-left: 12px; padding-left: 12px; border-left: 1px solid #2a2f3e; }

.lod-pill {
  font-size: 9px;
  padding: 1px 6px;
  border-radius: 3px;
  letter-spacing: 0.3px;
  opacity: 0.7;
}
.fact-pill  { background: #1a1200; color: #e67e22; border: 1px solid #e67e2240; }
.doc-pill   { background: #1a0000; color: #e74c3c; border: 1px solid #e74c3c40; }

/* ── Schema controls (Task 3) ──────────────────────────────────────────────── */
.schema-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: #0e1118;
  border-bottom: 1px solid #2a2f3e;
  flex-shrink: 0;
  flex-wrap: wrap;
  min-height: 32px;
}

/* ── Canvas area ───────────────────────────────────────────────────────────── */
.canvas-area {
  flex: 1;
  position: relative;
  overflow: hidden;
  min-height: 0;
}

/* ── Drawer ────────────────────────────────────────────────────────────────── */
.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.15);
  z-index: 20;
}

.drawer {
  height: 50vh;
  flex-shrink: 0;
  background: #fff;
  border-top: 2px solid #ddd;
  z-index: 21;
  position: relative;
  overflow: hidden;
}

/* ── Toast ─────────────────────────────────────────────────────────────────── */
.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 10px 18px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  z-index: 100;
  box-shadow: 0 4px 12px rgba(0,0,0,0.2);
}

.toast.success { background: #27ae60; color: #fff; }
.toast.error   { background: #e74c3c; color: #fff; }

.toast-fade-enter-active, .toast-fade-leave-active { transition: opacity 0.3s; }
.toast-fade-enter-from, .toast-fade-leave-to { opacity: 0; }
</style>
