<template>
  <div class="inspector">
    <div class="inspector-header">
      <span class="inspector-title">Node Inspector</span>
      <button class="close-btn" @click="$emit('close')">✕</button>
    </div>
    <div class="inspector-body">
      <div class="node-label">{{ node.label || node.id }}</div>

      <!-- Type badge + cluster badge (Task 4) -->
      <div class="badge-row">
        <span class="badge" :style="{ background: typeColor }">{{ node.nodeType || node.node_type }}</span>
        <span v-if="clusterId !== null" class="badge cluster-badge" :title="'Cluster ' + clusterId">
          cluster {{ clusterId }}
        </span>
      </div>

      <!-- Degree display (Task 4) -->
      <div v-if="degree !== null" class="field degree-field">
        <span class="field-key">degree</span>
        <span class="field-val">{{ degree }}</span>
      </div>

      <div v-if="node.entityCollection || node.entity_collection" class="field">
        <span class="field-key">collection</span>
        <span class="field-val">{{ node.entityCollection || node.entity_collection }}</span>
      </div>
      <div v-if="nodeProps" class="props-section">
        <div class="props-title">Properties</div>
        <div v-for="(val, key) in nodeProps" :key="key" class="field">
          <span class="field-key">{{ key }}</span>
          <span class="field-val">{{ formatVal(val) }}</span>
        </div>
      </div>

      <!-- Load neighbors button (Task 4) -->
      <button class="load-neighbors-btn" @click="$emit('expand-node', node.id)">
        Load neighbors
      </button>
    </div>
  </div>
</template>

<script>
import { computed } from 'vue'

const NODE_COLORS = {
  stylized_fact: '#4a90e2',
  taxon:         '#27ae60',
  fact:          '#e67e22',
  document:      '#e74c3c',
  species:       '#8e44ad',
  genus:         '#9b59b6',
  family:        '#1abc9c',
  order:         '#2ecc71',
  class:         '#27ae60',
  phylum:        '#16a085',
  concept:       '#16a085',
  default:       '#7f8c8d',
}

export default {
  name: 'NodeInspector',
  props: {
    node: { type: Object, required: true },
  },
  emits: ['close', 'expand-node'],
  setup(props) {
    const typeColor = computed(() => {
      const t = props.node.nodeType || props.node.node_type || 'default'
      return NODE_COLORS[t] || NODE_COLORS.default
    })

    const nodeProps = computed(() => props.node.properties || null)

    // cluster_id: check top-level first, then properties (Task 4)
    const clusterId = computed(() => {
      const cid = props.node.cluster_id ?? props.node.properties?.cluster_id ?? null
      return cid !== null && cid !== undefined ? cid : null
    })

    // degree from __degree property (Task 4)
    const degree = computed(() => {
      const d = props.node.__degree ?? null
      return d !== null ? d : null
    })

    function formatVal(v) {
      if (v === null || v === undefined) return '—'
      if (Array.isArray(v)) return v.join(', ') || '—'
      return String(v)
    }

    return { nodeProps, typeColor, clusterId, degree, formatVal }
  },
}
</script>

<style scoped>
.inspector {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 280px;
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.15);
  z-index: 10;
  font-size: 13px;
  max-height: calc(100% - 24px);
  overflow-y: auto;
}

.inspector-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid #eee;
  background: #f8f9fa;
  border-radius: 8px 8px 0 0;
}

.inspector-title {
  font-weight: 600;
  color: #333;
}

.close-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  color: #666;
  padding: 0 4px;
  line-height: 1;
}

.close-btn:hover { color: #333; }

.inspector-body {
  padding: 12px;
}

.node-label {
  font-weight: 600;
  font-size: 14px;
  color: #222;
  margin-bottom: 8px;
  word-break: break-word;
}

.badge-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
  font-size: 11px;
  font-weight: 500;
}

.cluster-badge {
  background: #3a4055;
  color: #e0e0e0;
  border: 1px solid #4a5068;
}

.field {
  display: flex;
  gap: 8px;
  padding: 3px 0;
  border-bottom: 1px solid #f0f0f0;
}

.degree-field {
  margin-bottom: 4px;
}

.field-key {
  color: #888;
  min-width: 80px;
  flex-shrink: 0;
  font-size: 11px;
  padding-top: 1px;
}

.field-val {
  color: #333;
  word-break: break-word;
}

.props-section {
  margin-top: 10px;
}

.props-title {
  font-weight: 600;
  color: #555;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.load-neighbors-btn {
  margin-top: 12px;
  width: 100%;
  padding: 7px 12px;
  background: #4a90e2;
  color: #fff;
  border: none;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}

.load-neighbors-btn:hover { background: #357abd; }
</style>
