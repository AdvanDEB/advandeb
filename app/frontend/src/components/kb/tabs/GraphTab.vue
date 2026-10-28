<template>
  <div class="tab-content graph-tab" role="tabpanel" aria-label="Graph">
    <SchemaPanel
      v-model="selectedSchema"
      :schemas="schemas"
      :stats-by-schema="statsBySchema"
      :selected-stats="selectedStats"
      :type-counts="typeCounts"
      :hidden-types="hiddenTypes"
      :hidden-edge-types="hiddenEdgeTypes"
      :display="displayConfig"
      @fit-view="canvasRef?.fitView()"
      @toggle-type="toggleType"
      @toggle-edge-type="toggleEdgeType"
      @update:display="displayConfig = $event"
    />

    <div class="graph-center">
      <div v-if="!selectedSchema" class="graph-empty">
        Select a graph schema to visualise
      </div>
      <div v-else class="graph-stage">
        <CosmographCanvas
          v-if="hasGraphData"
          ref="canvasRef"
          :bundle="graphBundle"
          :hidden-types="hiddenTypes"
          :hidden-edge-types="hiddenEdgeTypes"
          :display="displayConfig"
          @node-click="selectNode"
          @background-click="selectedNode = null"
        />
        <div v-else class="graph-empty">
          {{ graphEmptyMessage }}
        </div>

        <GraphLegendPanel
          v-if="hasGraphData && graphBundle"
          :schema-name="graphBundle.schemaName"
          :layout-mode="displayConfig.layoutMode ?? 'auto'"
          :has-stored-layout="graphBundle.hasLayout"
          @update:layout-mode="displayConfig = { ...displayConfig, layoutMode: $event }"
        />

        <div v-if="graphOverlayVisible" class="graph-loading-overlay">
          <div class="graph-loading-card">
            <div class="graph-loading-title">{{ graphLoad.message }}</div>
            <div
              :class="[
                'progress-bar',
                'graph-progress-bar',
                { 'progress-bar--indeterminate': graphLoad.indeterminate },
              ]"
            >
              <div
                class="progress-fill"
                :class="{ 'progress-fill--indeterminate': graphLoad.indeterminate }"
                :style="graphLoad.indeterminate ? undefined : { width: `${graphProgressPercent}%` }"
              />
            </div>
            <div class="graph-loading-meta">
              <span>{{ graphProgressDetail }}</span>
              <span v-if="!graphLoad.indeterminate">{{ graphProgressLabel }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Collapsible node table panel -->
      <NodeTablePanel
        v-if="tableOpen && graphBundle"
        :nodes="bundleToNodeList"
        :selectedNode="selectedNode"
        @select="selectNode"
      />

      <div class="graph-status-bar">
        <span>{{ formatCount(graphBundle?.nodeCount ?? 0) }} nodes · {{ formatCount(graphBundle?.edgeCount ?? 0) }} edges</span>
        <span v-if="selectedSchema" class="schema-tag">{{ selectedSchema.name }}</span>
        <div
          v-if="graphLoading"
          class="graph-inline-progress"
          :title="graphProgressDetail"
        >
          <span class="graph-inline-label">{{ graphLoad.message }}</span>
          <div
            :class="[
              'progress-bar',
              'graph-inline-progress-bar',
              { 'progress-bar--indeterminate': graphLoad.indeterminate },
            ]"
          >
            <div
              class="progress-fill"
              :class="{ 'progress-fill--indeterminate': graphLoad.indeterminate }"
              :style="graphLoad.indeterminate ? undefined : { width: `${graphProgressPercent}%` }"
            />
          </div>
          <span class="progress-label">{{ graphProgressLabel }}</span>
        </div>
        <button
          v-if="selectedSchema"
          type="button"
          class="graph-table-btn"
          :class="{ active: tableOpen }"
          :aria-pressed="tableOpen"
          :disabled="!graphBundle"
          title="Toggle node table"
          @click="tableOpen = !tableOpen"
        >☰ Table</button>
        <button
          v-if="selectedSchema"
          type="button"
          class="graph-refresh-btn"
          :disabled="graphLoading"
          title="Reload graph data from server"
          aria-label="Reload graph data from server"
          @click="refreshGraph"
        >{{ graphLoading ? '↻' : '↺' }}</button>
      </div>
    </div>

    <NodeInspector
      :node="selectedNode"
      :loading="graphLoading"
      @close="selectedNode = null"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import CosmographCanvas from '@/components/kb/CosmographCanvas.vue'
import GraphLegendPanel from '@/components/kb/GraphLegendPanel.vue'
import NodeInspector from '@/components/kb/NodeInspector.vue'
import NodeTablePanel from '@/components/kb/NodeTablePanel.vue'
import SchemaPanel from '@/components/kb/SchemaPanel.vue'
import type { DisplayConfig } from '@/components/kb/CosmographCanvas.vue'
import type { GraphNode } from '@/utils/kbApi'
import { useKnowledgeBuilderStore } from '@/stores/knowledgeBuilder'
import { formatCount } from '@/utils/format'

const kb = useKnowledgeBuilderStore()
const {
  schemas, selectedSchema, statsBySchema, selectedStats, typeCounts,
  graphBundle, selectedNode, graphLoading, graphLoad,
} = storeToRefs(kb)
const { refreshGraph } = kb

// ---- View-only state (filters, display, table) ------------------------------

const hiddenTypes     = ref<Set<string>>(new Set())
const hiddenEdgeTypes = ref<Set<string>>(new Set())
const canvasRef       = ref<InstanceType<typeof CosmographCanvas> | null>(null)
const tableOpen       = ref(false)
const displayConfig   = ref<Partial<DisplayConfig>>({})

const hasGraphData = computed(() => graphBundle.value !== null)

// Derive a flat GraphNode[] from the bundle for NodeTablePanel
const bundleToNodeList = computed<GraphNode[]>(() => {
  const bundle = graphBundle.value
  if (!bundle) return []
  return bundle.nodeSummaries.map(s => ({
    _id: s.id,
    schema_id: bundle.schemaId,
    node_type: s.type,
    entity_collection: s.entity_collection,
    entity_id: s.entity_id,
    label: s.label,
    properties: s.props,
    degree: s.degree,
    supports: s.supports,
    opposes: s.opposes,
  }))
})

// ---- Load progress -----------------------------------------------------------

const graphOverlayVisible = computed(() => graphLoad.value.active && graphLoad.value.overlay)

const graphProgressPercent = computed(() => {
  const { active, indeterminate, total, completed } = graphLoad.value
  if (!active || indeterminate || !total || total <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((completed / total) * 100)))
})

const graphProgressLabel = computed(() => (
  graphLoad.value.indeterminate || !graphLoad.value.total
    ? 'Loading'
    : `${graphProgressPercent.value}%`
))

const graphProgressDetail = computed(() => {
  if (graphLoad.value.detail) return graphLoad.value.detail
  if (graphLoad.value.indeterminate || !graphLoad.value.total) return 'Working…'
  return `${graphLoad.value.completed}/${graphLoad.value.total} steps`
})

const graphEmptyMessage = computed(() => (
  graphLoading.value ? 'Preparing graph data…' : 'This graph is empty'
))

// ---- Selection and filters ---------------------------------------------------

/** From a canvas click or a node-table row. */
function selectNode(node: GraphNode) {
  selectedNode.value = node
}

// Focus/unfocus the canvas whenever selectedNode changes
watch(selectedNode, (node) => {
  canvasRef.value?.focusNode(node ? node._id : null)
})

function toggleType(type: string) {
  const next = new Set(hiddenTypes.value)
  if (next.has(type)) next.delete(type)
  else next.add(type)
  hiddenTypes.value = next
}

function toggleEdgeType(type: string) {
  const next = new Set(hiddenEdgeTypes.value)
  if (next.has(type)) next.delete(type)
  else next.add(type)
  hiddenEdgeTypes.value = next
}
</script>

<style scoped>
.tab-content { flex: 1; min-height: 0; overflow: hidden; }

.graph-tab {
  display: flex;
  height: 100%;
}

.graph-center {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.graph-stage {
  flex: 1;
  min-height: 0;
  position: relative;
}

.graph-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #475569;
  font-size: 0.9rem;
}

.graph-status-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.3rem 0.75rem;
  background: #0f1117;
  border-top: 1px solid rgba(255,255,255,0.06);
  font-size: 0.7rem;
  color: #4a5270;
  flex-shrink: 0;
}

.graph-loading-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: rgba(15, 23, 42, 0.72);
  backdrop-filter: blur(2px);
  z-index: 2;
}

.graph-loading-card {
  width: min(360px, 100%);
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  padding: 1rem;
  border: 1px solid #334155;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.94);
  box-shadow: 0 20px 40px rgba(2, 6, 23, 0.45);
}

.graph-loading-title {
  font-size: 0.92rem;
  font-weight: 600;
  color: #e2e8f0;
}

.graph-loading-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  font-size: 0.72rem;
  color: #94a3b8;
}

/* .graph-progress-bar and .graph-inline-progress-bar carry no rules of their
   own: the sizes they once set were always overridden by .progress-bar below. */

.graph-inline-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  max-width: 360px;
}

.graph-inline-label {
  min-width: 0;
  font-size: 0.68rem;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.graph-refresh-btn {
  background: none;
  border: 1px solid #334155;
  border-radius: 4px;
  color: #64748b;
  font-size: 0.85rem;
  line-height: 1;
  padding: 0.1rem 0.4rem;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.graph-refresh-btn:hover:not(:disabled) { color: #e2e8f0; border-color: #60a5fa; }
.graph-refresh-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.graph-table-btn {
  background: none;
  border: 1px solid #334155;
  border-radius: 4px;
  color: #64748b;
  font-size: 0.7rem;
  line-height: 1;
  padding: 0.15rem 0.5rem;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
  margin-left: auto;
}
.graph-table-btn:hover:not(:disabled) { color: #e2e8f0; border-color: #60a5fa; }
.graph-table-btn.active { background: #1d4ed8; border-color: var(--app-primary); color: var(--app-primary-line); }
.graph-table-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.schema-tag {
  font-weight: 600;
  color: #60a5fa;
}

/* ---- Progress bars ---------------------------------------------------------- */
.progress-bar { height: 6px; background: #1e293b; border-radius: 3px; width: 100%; flex: 1; }
.progress-fill { height: 100%; background: var(--app-primary); border-radius: 3px; transition: width 0.3s; }
.progress-bar--indeterminate { position: relative; overflow: hidden; }
.progress-fill--indeterminate {
  width: 38%;
  transition: none;
  animation: graph-progress-indeterminate 1.2s ease-in-out infinite;
}
.progress-label { font-size: 0.65rem; color: #64748b; white-space: nowrap; flex-shrink: 0; }

@keyframes graph-progress-indeterminate {
  0% { transform: translateX(-120%); }
  100% { transform: translateX(320%); }
}

/* ---- Touch ------------------------------------------------------------------ */
@media (pointer: coarse) {
  .graph-table-btn,
  .graph-refresh-btn { min-height: var(--app-touch); min-width: var(--app-touch); }
}

/* ---- Narrow screens -----------------------------------------------------------
   Side by side, the schema panel (220px) and inspector (300px) leave a phone
   no canvas at all. Below 900px the schema panel stacks above the canvas with a
   capped height, and the inspector becomes a sheet over the bottom of it.
   The panels' own widths are overridden from here; their internals are not
   touched. The `aside` in these selectors outranks the panels' scoped rules
   (including the inspector's slide-in transition widths). */
@media (max-width: 900px) {
  .graph-tab {
    flex-direction: column;
    position: relative;
  }

  .graph-tab :deep(aside.ob-panel) {
    width: 100%;
    max-height: 32vh;
    flex-shrink: 0;
    border-right: none;
    border-bottom: 1px solid rgba(255,255,255,0.07);
  }

  .graph-center { flex: 1; min-height: 0; }

  .graph-tab :deep(aside.node-inspector) {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 5;
    width: 100%;
    /* A definite height: the inspector's body is a flex:1 scroller and would
       collapse to nothing under height:auto. */
    height: min(55%, 420px);
    border-left: none;
    border-top: 1px solid #334155;
    box-shadow: 0 -12px 32px rgba(2, 6, 23, 0.55);
  }

  .graph-inline-progress { max-width: 100%; }
}
</style>
