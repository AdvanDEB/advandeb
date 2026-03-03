<template>
  <div class="app">
    <!-- Toolbar -->
    <header class="toolbar">
      <span class="brand">AdvanDEB KB</span>

      <select v-model="selectedSchemaId" class="toolbar-select" @change="onSchemaChange">
        <option value="" disabled>schema ▾</option>
        <option v-for="s in schemas" :key="s._id" :value="s._id">{{ s.name }}</option>
      </select>

      <select v-model="selectedLayout" class="toolbar-select" @change="onLayoutChange">
        <option value="force">force ▾</option>
        <option value="circular">circular</option>
        <option value="random">random</option>
      </select>

      <span v-if="graphStats" class="stats">
        {{ graphStats.nodes.toLocaleString() }} nodes &nbsp; {{ graphStats.edges.toLocaleString() }} edges
      </span>

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
    </header>

    <!-- Canvas area -->
    <div class="canvas-area">
      <SearchOverlay @search="onSearch" />
      <GraphCanvas
        ref="graphCanvasRef"
        :schemaId="selectedSchemaId"
        :layout="selectedLayout"
        @node-selected="onNodeSelected"
        @stats-updated="onStatsUpdated"
        @schemas-loaded="onSchemasLoaded"
      />
      <NodeInspector
        v-if="selectedNode"
        :node="selectedNode"
        @close="selectedNode = null"
      />
    </div>

    <!-- Bottom sheet drawer -->
    <template v-if="activeDrawer">
      <div class="drawer-backdrop" @click="activeDrawer = null"></div>
      <div class="drawer">
        <IngestionDrawer v-if="activeDrawer === 'ingestion'" />
        <DatabaseDrawer v-if="activeDrawer === 'database'" />
        <FilesystemDrawer v-if="activeDrawer === 'filesystem'" />
      </div>
    </template>

    <!-- Toast -->
    <transition name="toast-fade">
      <div v-if="toast" class="toast" :class="toast.type">{{ toast.message }}</div>
    </transition>
  </div>
</template>

<script>
import { ref } from 'vue'
import GraphCanvas from './components/GraphCanvas.vue'
import NodeInspector from './components/NodeInspector.vue'
import SearchOverlay from './components/SearchOverlay.vue'
import IngestionDrawer from './drawers/IngestionDrawer.vue'
import DatabaseDrawer from './drawers/DatabaseDrawer.vue'
import FilesystemDrawer from './drawers/FilesystemDrawer.vue'
import { vizAPI } from './services/api.js'

export default {
  name: 'App',
  components: {
    GraphCanvas, NodeInspector, SearchOverlay,
    IngestionDrawer, DatabaseDrawer, FilesystemDrawer,
  },
  setup() {
    const schemas = ref([])
    const selectedSchemaId = ref('')
    const selectedLayout = ref('force')
    const graphStats = ref(null)
    const selectedNode = ref(null)
    const activeDrawer = ref(null)
    const rebuilding = ref(false)
    const toast = ref(null)
    const graphCanvasRef = ref(null)

    function onSchemasLoaded(list) {
      schemas.value = list
    }

    function onSchemaChange() {
      selectedNode.value = null
      graphStats.value = null
    }

    function onLayoutChange() {
      // GraphCanvas watches selectedLayout via prop
    }

    function onNodeSelected(node) {
      selectedNode.value = node
    }

    function onStatsUpdated(stats) {
      graphStats.value = stats
    }

    function onSearch(query) {
      graphCanvasRef.value?.applySearch(query)
    }

    function toggleDrawer(name) {
      activeDrawer.value = activeDrawer.value === name ? null : name
    }

    async function rebuildGraph() {
      if (!selectedSchemaId.value) return
      rebuilding.value = true
      try {
        const res = await vizAPI.rebuildSchema(selectedSchemaId.value, {})
        const { nodes, edges } = res.data
        showToast(`Rebuilt: ${nodes} nodes, ${edges} edges`, 'success')
        // Reload the graph after rebuild
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
      schemas, selectedSchemaId, selectedLayout,
      graphStats, selectedNode, activeDrawer, rebuilding, toast,
      graphCanvasRef,
      onSchemasLoaded, onSchemaChange, onLayoutChange,
      onNodeSelected, onStatsUpdated, onSearch,
      toggleDrawer, rebuildGraph,
    }
  },
}
</script>

<style>
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html, body, #app, .app {
  width: 100%;
  height: 100%;
  overflow: hidden;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px;
  color: #333;
}
</style>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* Toolbar */
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

.spacer { flex: 1; }

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

/* Canvas area — fills remaining space */
.canvas-area {
  flex: 1;
  position: relative;
  overflow: hidden;
  min-height: 0;
}

/* Drawer */
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

/* Toast */
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
.toast.error { background: #e74c3c; color: #fff; }

.toast-fade-enter-active, .toast-fade-leave-active { transition: opacity 0.3s; }
.toast-fade-enter-from, .toast-fade-leave-to { opacity: 0; }
</style>
