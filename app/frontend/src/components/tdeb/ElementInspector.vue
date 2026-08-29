<template>
  <div class="inspector">
    <p v-if="!node && !edge" class="inspector-empty">
      Click a compartment or a transport channel to edit its parameters.
    </p>

    <!-- ── Node ── -->
    <div v-else-if="node" class="inspector-body">
      <h3 class="inspector-title">
        <span class="type-dot" :style="{ background: nodeColor(node.node_type) }"></span>
        {{ node.name }}
      </h3>

      <label class="field">
        <span>Name</span>
        <input v-model="nodeForm.name" type="text" @change="pushNode" />
      </label>

      <label class="field">
        <span>Type</span>
        <select v-model="nodeForm.node_type" @change="pushNode">
          <option v-for="t in NODE_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
        </select>
      </label>

      <p v-if="nodeForm.node_type === 'food'" class="field-note">
        Food compartments are boundary conditions, not state variables — their
        value comes from the food availability slider rather than the ODE system.
      </p>

      <label class="field">
        <span>Initial value</span>
        <input v-model.number="nodeForm.initial_value" type="number" step="any" @change="pushNode" />
      </label>

      <label class="field">
        <span>Maintenance p_M [J/d/cm³]</span>
        <input v-model.number="nodeForm.maintenance_rate" type="number" step="any" @change="pushNode" />
      </label>
      <p v-if="nodeForm.maintenance_rate && nodeForm.node_type !== 'structure'" class="field-note warn">
        Somatic maintenance is only drawn from structure compartments, so this
        rate has no effect on a {{ nodeForm.node_type }} node.
      </p>

      <label class="field">
        <span>Specific cost E_G [J/cm³]</span>
        <input v-model.number="nodeForm.specific_cost" type="number" step="any" @change="pushNode" />
      </label>

      <label class="field">
        <span>Arrhenius T_A [K]</span>
        <input v-model.number="nodeForm.T_A" type="number" step="any" @change="pushNode" />
      </label>

      <button class="btn-danger" @click="emit('delete')">Delete compartment</button>
    </div>

    <!-- ── Edge ── -->
    <div v-else-if="edge" class="inspector-body">
      <h3 class="inspector-title">{{ edge.name }}</h3>
      <p class="inspector-sub">{{ sourceName }} → {{ targetName }}</p>

      <label class="field">
        <span>Name</span>
        <input v-model="edgeForm.name" type="text" @change="pushEdge" />
      </label>

      <label class="field">
        <span>Transport kinetics</span>
        <select v-model="edgeForm.transport_type" @change="onKineticsChange">
          <option v-for="t in TRANSPORT_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
        </select>
      </label>

      <!-- Only the parameters the selected kinetics actually reads are shown;
           the rest are still stored, just not surfaced as noise. -->
      <label v-if="usesParam('rate_constant')" class="field">
        <span>Rate constant k [1/d]</span>
        <input v-model.number="edgeForm.rate_constant" type="number" step="any" @change="pushEdge" />
      </label>

      <label v-if="usesParam('V_max')" class="field">
        <span>V_max [J/d]</span>
        <input v-model.number="edgeForm.V_max" type="number" step="any" @change="pushEdge" />
      </label>

      <label v-if="usesParam('K_m')" class="field">
        <span>K_m [J]</span>
        <input v-model.number="edgeForm.K_m" type="number" step="any" @change="pushEdge" />
      </label>

      <label v-if="usesParam('hill_coeff')" class="field">
        <span>Hill coefficient n</span>
        <input v-model.number="edgeForm.hill_coeff" type="number" step="any" @change="pushEdge" />
      </label>

      <label v-if="usesParam('kappa')" class="field">
        <span>κ (allocation fraction)</span>
        <input v-model.number="edgeForm.kappa" type="number" step="0.05" min="0" max="1" @change="pushEdge" />
      </label>

      <label v-if="usesParam('threshold')" class="field">
        <span>Activation threshold</span>
        <input v-model.number="edgeForm.threshold" type="number" step="any" @change="pushEdge" />
      </label>

      <label v-if="usesParam('signal_strength')" class="field">
        <span>Signal strength s</span>
        <input v-model.number="edgeForm.signal_strength" type="number" step="any" @change="pushEdge" />
      </label>

      <label class="field">
        <span>Efficiency η (0–1)</span>
        <input v-model.number="edgeForm.efficiency" type="number" step="0.05" min="0" max="1" @change="pushEdge" />
      </label>

      <label class="field">
        <span>Arrhenius T_A [K]</span>
        <input v-model.number="edgeForm.T_A" type="number" step="any" @change="pushEdge" />
      </label>

      <!-- Custom kinetics: editable expression. Other kinetics: read-only
           preview of whatever formula the Equations tab currently defines. -->
      <div v-if="edgeForm.transport_type === 'custom'" class="field">
        <span>Formula</span>
        <textarea
          v-model="edgeForm.custom_formula"
          rows="3"
          spellcheck="false"
          placeholder="e.g. k * X_source / (X_source + K_m) * T_corr"
          @change="pushEdge"
        ></textarea>
        <p class="formula-help">Variables: {{ FORMULA_VARIABLES }}</p>
        <p class="formula-help">Functions: {{ FORMULA_FUNCTIONS }}</p>
        <p v-if="formulaError" class="formula-error">{{ formulaError }}</p>
      </div>
      <div v-else-if="activeFormula" class="field">
        <span>Active formula (from the Equations tab)</span>
        <code class="formula-preview">{{ activeFormula }}</code>
      </div>

      <button class="btn-danger" @click="emit('delete')">Delete channel</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type {
  EquationDocument, TDebEdge, TDebEdgeParams, TDebNode, NodeTypeId, TransportTypeId,
} from '@/utils/tdebApi'
import {
  FORMULA_FUNCTIONS, FORMULA_VARIABLES, NODE_TYPES, TRANSPORT_TYPES, nodeColor,
} from '@/utils/tdebConstants'

const props = defineProps<{
  node: TDebNode | null
  edge: TDebEdge | null
  nodes: Record<string, TDebNode>
  equations: EquationDocument | null
  formulaError: string
}>()

const emit = defineEmits<{
  (e: 'update-node', payload: {
    name: string; node_type: NodeTypeId; initial_value: number; value: number
    color: string; params: Partial<TDebNode['params']>
  }): void
  (e: 'update-edge', payload: {
    name: string; transport_type: TransportTypeId; params: Partial<TDebEdgeParams>
  }): void
  (e: 'delete'): void
}>()

const nodeForm = reactive({
  name: '',
  node_type: 'custom' as NodeTypeId,
  initial_value: 0,
  maintenance_rate: 0,
  specific_cost: 0,
  T_A: 8000,
})

const edgeForm = reactive({
  name: '',
  transport_type: 'linear' as TransportTypeId,
  rate_constant: 1,
  V_max: 1,
  K_m: 1,
  kappa: 0.8,
  threshold: 0,
  efficiency: 1,
  hill_coeff: 1,
  signal_strength: 1,
  custom_formula: '',
  T_A: 8000,
})

watch(() => props.node, (n) => {
  if (!n) return
  nodeForm.name = n.name
  nodeForm.node_type = n.node_type
  nodeForm.initial_value = n.initial_value
  nodeForm.maintenance_rate = n.params.maintenance_rate
  nodeForm.specific_cost = n.params.specific_cost
  nodeForm.T_A = n.params.T_A
}, { immediate: true })

watch(() => props.edge, (e) => {
  if (!e) return
  edgeForm.name = e.name
  edgeForm.transport_type = e.transport_type
  edgeForm.rate_constant = e.params.rate_constant
  edgeForm.V_max = e.params.V_max
  edgeForm.K_m = e.params.K_m
  edgeForm.kappa = e.params.kappa
  edgeForm.threshold = e.params.threshold
  edgeForm.efficiency = e.params.efficiency
  edgeForm.hill_coeff = e.params.hill_coeff
  edgeForm.signal_strength = e.params.signal_strength
  edgeForm.custom_formula = e.params.custom_formula
  edgeForm.T_A = e.params.T_A
}, { immediate: true })

const sourceName = computed(() =>
  props.edge ? props.nodes[props.edge.source_id]?.name ?? '?' : '')
const targetName = computed(() =>
  props.edge ? props.nodes[props.edge.target_id]?.name ?? '?' : '')

const activeFormula = computed(() => {
  const type = edgeForm.transport_type
  if (type === 'custom') return ''
  return props.equations?.transport?.[type]?.formula ?? ''
})

/** Which edge parameters the currently selected kinetics reads. */
const PARAMS_BY_KINETICS: Record<string, string[]> = {
  linear: ['rate_constant'],
  michaelis_menten: ['V_max', 'K_m', 'hill_coeff'],
  gradient: ['rate_constant'],
  kappa_split: ['rate_constant', 'kappa'],
  regulated: ['V_max', 'K_m', 'signal_strength'],
  threshold: ['rate_constant', 'threshold'],
  fixed: ['rate_constant'],
}

function usesParam(param: string): boolean {
  // A custom formula can reference anything, so show every field for it.
  if (edgeForm.transport_type === 'custom') return true
  return (PARAMS_BY_KINETICS[edgeForm.transport_type] ?? []).includes(param)
}

function pushNode() {
  emit('update-node', {
    name: nodeForm.name,
    node_type: nodeForm.node_type,
    initial_value: nodeForm.initial_value,
    value: nodeForm.initial_value,
    color: nodeColor(nodeForm.node_type),
    params: {
      maintenance_rate: nodeForm.maintenance_rate,
      specific_cost: nodeForm.specific_cost,
      T_A: nodeForm.T_A,
    },
  })
}

function pushEdge() {
  emit('update-edge', {
    name: edgeForm.name,
    transport_type: edgeForm.transport_type,
    params: {
      rate_constant: edgeForm.rate_constant,
      V_max: edgeForm.V_max,
      K_m: edgeForm.K_m,
      kappa: edgeForm.kappa,
      threshold: edgeForm.threshold,
      efficiency: edgeForm.efficiency,
      hill_coeff: edgeForm.hill_coeff,
      signal_strength: edgeForm.signal_strength,
      custom_formula: edgeForm.custom_formula,
      T_A: edgeForm.T_A,
    },
  })
}

function onKineticsChange() {
  // Switching to a custom formula starts from the kinetics the edge was just
  // using, so the user edits a working expression instead of a blank box.
  if (edgeForm.transport_type === 'custom' && !edgeForm.custom_formula.trim()) {
    const previous = props.edge?.transport_type
    const seed = previous && previous !== 'custom'
      ? props.equations?.transport?.[previous]?.formula
      : ''
    if (seed) edgeForm.custom_formula = seed
  }
  pushEdge()
}
</script>

<style scoped>
.inspector { display: flex; flex-direction: column; gap: 0.75rem; }
.inspector-empty {
  color: #6b7280;
  font-size: 0.85rem;
  line-height: 1.6;
  padding: 1.5rem 0.25rem;
  text-align: center;
}
.inspector-body { display: flex; flex-direction: column; gap: 0.7rem; }
.inspector-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  font-weight: 600;
  color: #111827;
  margin: 0;
}
.inspector-sub { font-size: 0.75rem; color: #6b7280; margin: -0.4rem 0 0; }
.type-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }

.field { display: flex; flex-direction: column; gap: 0.25rem; }
.field > span { font-size: 0.72rem; font-weight: 600; color: #4b5563; }
.field input,
.field select,
.field textarea {
  border: 1px solid #d1d5db;
  border-radius: 5px;
  padding: 0.35rem 0.5rem;
  font-size: 0.82rem;
  color: #111827;
  background: #fff;
  width: 100%;
}
.field textarea {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.78rem;
  resize: vertical;
}
.field input:focus,
.field select:focus,
.field textarea:focus { outline: 2px solid #bfdbfe; outline-offset: -1px; }

.field-note {
  font-size: 0.7rem;
  color: #6b7280;
  line-height: 1.5;
  margin: -0.3rem 0 0;
}
.field-note.warn { color: #b45309; }

.formula-help {
  font-size: 0.66rem;
  color: #6b7280;
  margin: 0;
  word-break: break-word;
}
.formula-error {
  font-size: 0.7rem;
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 4px;
  padding: 0.3rem 0.45rem;
  margin: 0.2rem 0 0;
}
.formula-preview {
  display: block;
  font-size: 0.74rem;
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  padding: 0.35rem 0.5rem;
  color: #374151;
  word-break: break-word;
}

.btn-danger {
  margin-top: 0.4rem;
  align-self: flex-start;
  border: 1px solid #fecaca;
  background: #fef2f2;
  color: #b91c1c;
  border-radius: 5px;
  padding: 0.35rem 0.8rem;
  font-size: 0.78rem;
  cursor: pointer;
}
.btn-danger:hover { background: #fee2e2; }
</style>
