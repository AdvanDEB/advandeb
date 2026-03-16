<template>
  <div class="inspector">
    <div class="inspector-header">
      <span class="inspector-title">Node Inspector</span>
      <button class="close-btn" @click="$emit('close')">✕</button>
    </div>
    <div class="inspector-body">
      <div class="node-label">{{ node.label || node.id }}</div>
      <span class="badge" :style="{ background: typeColor }">{{ node.nodeType || node.node_type }}</span>
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
    </div>
  </div>
</template>

<script>
import { computed } from 'vue'

const NODE_COLORS = {
  stylized_fact: '#4a90e2',
  taxon: '#27ae60',
  fact: '#e67e22',
  document: '#e74c3c',
  species: '#8e44ad',
  concept: '#16a085',
  default: '#7f8c8d',
}

export default {
  name: 'NodeInspector',
  props: {
    node: { type: Object, required: true },
  },
  emits: ['close'],
  setup(props) {
    const typeColor = computed(() => {
      const t = props.node.nodeType || props.node.node_type || 'default'
      return NODE_COLORS[t] || NODE_COLORS.default
    })

    const nodeProps = computed(() => props.node.properties || null)

    function formatVal(v) {
      if (v === null || v === undefined) return '—'
      if (Array.isArray(v)) return v.join(', ') || '—'
      return String(v)
    }

    return { nodeProps, typeColor, formatVal }
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

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
  font-size: 11px;
  font-weight: 500;
  margin-bottom: 10px;
}

.field {
  display: flex;
  gap: 8px;
  padding: 3px 0;
  border-bottom: 1px solid #f0f0f0;
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
</style>
