<template>
  <div class="equations">
    <!-- ── Editor ── -->
    <section class="eq-editor">
      <header class="eq-editor-head">
        <h3>Equation editor</h3>
        <div class="eq-actions">
          <button class="btn-primary" :disabled="saving" @click="saveAll">
            {{ saving ? 'Saving…' : 'Save equations' }}
          </button>
          <button class="btn-ghost" :disabled="saving" @click="reset">Reset to defaults</button>
        </div>
      </header>
      <p class="eq-desc">
        These formulas are yours alone — editing them changes how your models are
        solved and leaves everyone else's untouched.
      </p>
      <p v-if="status" class="eq-status" :class="statusKind">{{ status }}</p>

      <div v-if="draft" class="eq-fields">
        <div class="eq-group">
          <h4>Transport kinetics</h4>
          <div v-for="(entry, key) in draft.transport" :key="key" class="eq-field">
            <label>{{ kineticsLabel(String(key)) }}</label>
            <p v-if="entry.description" class="eq-field-desc">{{ entry.description }}</p>
            <textarea
              v-model="entry.formula"
              rows="1"
              spellcheck="false"
              :class="{ invalid: errors[`transport.${key}`] }"
              @blur="check(`transport.${key}`, entry.formula)"
            ></textarea>
            <p v-if="entry.variables?.length" class="eq-field-vars">
              Variables: {{ entry.variables.join(', ') }}
            </p>
            <p v-if="errors[`transport.${key}`]" class="eq-field-error">
              {{ errors[`transport.${key}`] }}
            </p>
          </div>
        </div>

        <div v-for="section in SIMPLE_SECTIONS" :key="section.key" class="eq-group">
          <h4>{{ section.label }}</h4>
          <div class="eq-field">
            <p v-if="sectionEntry(section.key)?.description" class="eq-field-desc">
              {{ sectionEntry(section.key)?.description }}
            </p>
            <label v-if="section.key === 'non_negativity'" class="eq-toggle">
              <input v-model="nonNegEnabled" type="checkbox" />
              <span>Enabled</span>
            </label>
            <textarea
              v-model="sectionEntry(section.key)!.formula"
              rows="1"
              spellcheck="false"
              :class="{ invalid: errors[section.key] }"
              @blur="check(section.key, sectionEntry(section.key)!.formula)"
            ></textarea>
            <p v-if="errors[section.key]" class="eq-field-error">{{ errors[section.key] }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- ── Rendered model equations ── -->
    <section class="eq-rendered">
      <p v-if="!hasModel" class="eq-empty">Load a model to see its equations.</p>
      <template v-else>
        <div v-for="block in renderedSections" :key="block.title" class="eq-section">
          <div class="eq-section-title">{{ block.title }}</div>
          <div v-for="(item, i) in block.items" :key="i" class="eq-block">
            <div v-if="item.label" class="eq-label">
              {{ item.label }}
              <span v-if="item.sublabel" class="eq-label-dim">({{ item.sublabel }})</span>
            </div>
            <div class="eq-render" v-html="renderLatex(item.latex, true)"></div>
            <div v-if="item.params" class="eq-params" v-html="renderLatex(item.params, false)"></div>
          </div>
        </div>

        <div v-if="legend.length" class="eq-section">
          <div class="eq-section-title">Flow legend</div>
          <div v-for="item in legend" :key="item.latex" class="eq-legend-item">
            <span class="eq-legend-sym" v-html="renderLatex(item.latex, false)"></span>
            <span class="eq-legend-text">— {{ item.text }}</span>
          </div>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import type { EquationDocument, EquationEntry, TDebEdge, TDebNode } from '@/utils/tdebApi'
import { TRANSPORT_TYPES, formatNumber } from '@/utils/tdebConstants'
import { resetEquations, updateEquation, validateFormula } from '@/utils/tdebApi'

const props = defineProps<{
  equations: EquationDocument | null
  nodes: Record<string, TDebNode>
  edges: Record<string, TDebEdge>
}>()

const emit = defineEmits<{ (e: 'saved', doc: EquationDocument): void }>()

const SIMPLE_SECTIONS = [
  { key: 'arrhenius', label: 'Arrhenius correction' },
  { key: 'maintenance', label: 'Somatic maintenance' },
  { key: 'efficiency', label: 'Efficiency' },
  { key: 'non_negativity', label: 'Non-negativity clamp' },
] as const

// A local copy so typing in a textarea does not mutate the parent's document
// before the user commits with Save.
const draft = ref<EquationDocument | null>(null)
const nonNegEnabled = ref(true)
const errors = reactive<Record<string, string>>({})
const saving = ref(false)
const status = ref('')
const statusKind = ref<'ok' | 'err'>('ok')

watch(() => props.equations, (doc) => {
  draft.value = doc ? JSON.parse(JSON.stringify(doc)) as EquationDocument : null
  nonNegEnabled.value = doc?.non_negativity?.enabled ?? true
  for (const k of Object.keys(errors)) delete errors[k]
}, { immediate: true, deep: false })

function sectionEntry(key: string): EquationEntry | null {
  const doc = draft.value as Record<string, unknown> | null
  return (doc?.[key] as EquationEntry) ?? null
}

function kineticsLabel(key: string): string {
  return TRANSPORT_TYPES.find(t => t.value === key)?.label ?? key
}

function flash(message: string, kind: 'ok' | 'err' = 'ok') {
  status.value = message
  statusKind.value = kind
  window.setTimeout(() => { if (status.value === message) status.value = '' }, 4000)
}

async function check(key: string, formula: string): Promise<boolean> {
  if (!formula?.trim()) {
    delete errors[key]
    return true
  }
  try {
    const { valid, error } = await validateFormula(formula)
    if (valid) delete errors[key]
    else errors[key] = error
    return valid
  } catch {
    errors[key] = 'Could not validate the formula'
    return false
  }
}

async function saveAll() {
  if (!draft.value) return
  saving.value = true
  try {
    const updates: { section: string; key: string | null; formula: string }[] = []
    for (const [key, entry] of Object.entries(draft.value.transport)) {
      updates.push({ section: 'transport', key, formula: entry.formula })
    }
    for (const section of SIMPLE_SECTIONS) {
      const entry = sectionEntry(section.key)
      if (entry) updates.push({ section: section.key, key: null, formula: entry.formula })
    }

    const results = await Promise.all(
      updates.map(u => check(u.key ? `${u.section}.${u.key}` : u.section, u.formula)),
    )
    if (results.some(ok => !ok)) {
      flash('Some formulas are invalid — check the highlighted fields.', 'err')
      return
    }

    let latest: EquationDocument | null = null
    for (const u of updates) {
      latest = await updateEquation(u.section, u.key, { formula: u.formula })
    }
    latest = await updateEquation('non_negativity', null, {
      formula: sectionEntry('non_negativity')?.formula ?? '',
      enabled: nonNegEnabled.value,
    })

    if (latest) emit('saved', latest)
    flash('Equations saved.')
  } catch (err) {
    flash(err instanceof Error ? err.message : 'Save failed.', 'err')
  } finally {
    saving.value = false
  }
}

async function reset() {
  if (!window.confirm('Reset every formula to the shipped defaults?')) return
  saving.value = true
  try {
    emit('saved', await resetEquations())
    flash('Equations reset to defaults.')
  } catch (err) {
    flash(err instanceof Error ? err.message : 'Reset failed.', 'err')
  } finally {
    saving.value = false
  }
}

// ─── Rendered model equations ────────────────────────────────────────

const hasModel = computed(() => Object.keys(props.nodes).length > 0)

/** A node's display symbol: the parenthesised part of its name if it has one. */
function symbolOf(node: TDebNode): string {
  const match = node.name.match(/\(([^)]+)\)/)
  return match ? match[1] : node.name.replace(/\s+/g, '\\_')
}

/** J_1, J_2, … in stable edge order, shared by the ODEs and the legend. */
const edgeLabels = computed(() => {
  const map: Record<string, string> = {}
  Object.keys(props.edges).forEach((id, i) => { map[id] = `J_{${i + 1}}` })
  return map
})

interface EqItem { latex: string; params?: string; label?: string; sublabel?: string }

const renderedSections = computed<{ title: string; items: EqItem[] }[]>(() => {
  if (!hasModel.value) return []

  const nodes = props.nodes
  const edges = props.edges
  const labels = edgeLabels.value

  const incoming: Record<string, string[]> = {}
  const outgoing: Record<string, string[]> = {}
  for (const id of Object.keys(nodes)) { incoming[id] = []; outgoing[id] = [] }
  for (const [eid, edge] of Object.entries(edges)) {
    outgoing[edge.source_id]?.push(eid)
    incoming[edge.target_id]?.push(eid)
  }

  const sections: { title: string; items: EqItem[] }[] = []

  // ODE system — food nodes are boundary conditions, not states.
  const stateNodes = Object.values(nodes).filter(n => n.node_type !== 'food')
  sections.push({
    title: 'ODE system',
    items: stateNodes.map((node) => {
      const sym = symbolOf(node)
      const terms: string[] = []
      for (const eid of incoming[node.id] ?? []) terms.push(labels[eid])
      const rhsIn = terms.join(' + ')
      const rhsOut = (outgoing[node.id] ?? []).map(eid => ` - ${labels[eid]}`).join('')
      const maint = node.node_type === 'structure' ? ` - \\dot{r}_{${sym}}` : ''
      const rhs = `${rhsIn}${rhsOut}${maint}`.trim() || '0'
      return { latex: `\\frac{d${sym}}{dt} = ${rhs}` }
    }),
  })

  // Flux laws
  const fluxItems: EqItem[] = Object.entries(edges).map(([eid, edge]) => {
    const J = labels[eid]
    const src = nodes[edge.source_id]
    const tgt = nodes[edge.target_id]
    const s = src ? symbolOf(src) : '?'
    const t = tgt ? symbolOf(tgt) : '?'
    const p = edge.params
    const etaSuffix = p.efficiency !== 1 ? ' \\cdot \\eta' : ''

    let latex = `${J} = ?`
    let params = ''

    switch (edge.transport_type) {
      case 'linear':
        latex = `${J} = k \\cdot ${s} \\cdot T_{corr}${etaSuffix}`
        params = `k = ${formatNumber(p.rate_constant)}`
        break
      case 'michaelis_menten':
        if (p.hill_coeff !== 1) {
          latex = `${J} = \\frac{V_{max} \\cdot ${s}^{n}}{${s}^{n} + K_m^{n}} \\cdot T_{corr}${etaSuffix}`
          params = `V_{max} = ${formatNumber(p.V_max)},\\; K_m = ${formatNumber(p.K_m)},\\; n = ${formatNumber(p.hill_coeff)}`
        } else {
          latex = `${J} = \\frac{V_{max} \\cdot ${s}}{${s} + K_m} \\cdot T_{corr}${etaSuffix}`
          params = `V_{max} = ${formatNumber(p.V_max)},\\; K_m = ${formatNumber(p.K_m)}`
        }
        break
      case 'gradient':
        latex = `${J} = \\max\\!\\left(0,\\; k \\cdot (${s} - ${t}) \\cdot T_{corr}\\right)${etaSuffix}`
        params = `k = ${formatNumber(p.rate_constant)}`
        break
      case 'kappa_split':
        latex = `${J} = \\kappa \\cdot k \\cdot ${s} \\cdot T_{corr}${etaSuffix}`
        params = `\\kappa = ${formatNumber(p.kappa)},\\; k = ${formatNumber(p.rate_constant)}`
        break
      case 'regulated':
        latex = `${J} = V_{max} \\cdot \\sigma \\cdot s \\cdot \\frac{${s}}{${s} + K_m} \\cdot T_{corr}${etaSuffix}`
        params = `V_{max} = ${formatNumber(p.V_max)},\\; K_m = ${formatNumber(p.K_m)},\\; s = ${formatNumber(p.signal_strength)}`
        break
      case 'threshold':
        latex = `${J} = k \\cdot \\max\\!\\left(0,\\; ${s} - X_{thr}\\right) \\cdot T_{corr}${etaSuffix}`
        params = `k = ${formatNumber(p.rate_constant)},\\; X_{thr} = ${formatNumber(p.threshold)}`
        break
      case 'fixed':
        latex = `${J} = k \\cdot T_{corr}${etaSuffix}`
        params = `k = ${formatNumber(p.rate_constant)}`
        break
      case 'custom': {
        // A user expression is code, not maths — typeset it verbatim.
        const escaped = (p.custom_formula || '?')
          .replace(/\\/g, '\\textbackslash ')
          .replace(/([_{}$&#%])/g, '\\$1')
        latex = `${J} = \\texttt{${escaped}}`
        params = usedParams(p.custom_formula, edge)
        break
      }
    }

    if (p.efficiency !== 1) {
      params = params ? `${params},\\; \\eta = ${formatNumber(p.efficiency)}` : `\\eta = ${formatNumber(p.efficiency)}`
    }

    return {
      latex,
      params,
      label: edge.name || 'transport',
      sublabel: `${src?.name ?? '?'} → ${tgt?.name ?? '?'}`,
    }
  })
  if (fluxItems.length) sections.push({ title: 'Flux laws', items: fluxItems })

  // Somatic maintenance
  const structureNodes = Object.values(nodes).filter(n => n.node_type === 'structure')
  if (structureNodes.length) {
    sections.push({
      title: 'Somatic maintenance',
      items: structureNodes.map((node) => {
        const sym = symbolOf(node)
        return {
          latex: `\\dot{r}_{${sym}} = p_M \\cdot ${sym} \\cdot T_{corr}`,
          params: `p_M = ${formatNumber(node.params.maintenance_rate)} \\; \\text{J/d/cm}^3`,
        }
      }),
    })
  }

  // Arrhenius correction — reported from the first node that carries a T_A.
  const reference = Object.values(nodes).find(n => n.params?.T_A) ?? null
  sections.push({
    title: 'Temperature correction (Arrhenius)',
    items: [{
      latex: 'T_{corr} = \\exp\\!\\left(\\frac{T_A}{T_{ref}} - \\frac{T_A}{T}\\right)',
      params: `T_A = ${formatNumber(reference?.params.T_A ?? 8000)} \\; \\text{K},\\; `
        + `T_{ref} = ${formatNumber(reference?.params.T_ref ?? 293.15)} \\; \\text{K}`,
    }],
  })

  return sections
})

function usedParams(formula: string, edge: TDebEdge): string {
  const p = edge.params
  const parts: string[] = []
  if (/\bk\b/.test(formula)) parts.push(`k = ${formatNumber(p.rate_constant)}`)
  if (formula.includes('V_max')) parts.push(`V_{max} = ${formatNumber(p.V_max)}`)
  if (formula.includes('K_m')) parts.push(`K_m = ${formatNumber(p.K_m)}`)
  if (/\bkappa\b/.test(formula)) parts.push(`\\kappa = ${formatNumber(p.kappa)}`)
  if (/\bthreshold\b/.test(formula)) parts.push(`X_{thr} = ${formatNumber(p.threshold)}`)
  if (/\bn\b/.test(formula)) parts.push(`n = ${formatNumber(p.hill_coeff)}`)
  if (/\bs\b/.test(formula)) parts.push(`s = ${formatNumber(p.signal_strength)}`)
  return parts.join(',\\; ')
}

const legend = computed(() =>
  Object.entries(props.edges).map(([eid, edge]) => ({
    latex: edgeLabels.value[eid],
    text: `${edge.name || 'transport'} `
      + `(${props.nodes[edge.source_id]?.name ?? '?'} → ${props.nodes[edge.target_id]?.name ?? '?'})`,
  })),
)

/**
 * KaTeX output is inserted with v-html. That is safe here because every string
 * passed in is LaTeX we generated, and KaTeX in non-trust mode escapes the
 * user-supplied fragments (node names, custom formulas) that reach it.
 */
function renderLatex(latex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(latex, { displayMode, throwOnError: false, trust: false })
  } catch {
    return latex
  }
}

defineExpose({ renderedSections, legend })
</script>

<style scoped>
.equations { display: flex; flex-direction: column; gap: 1.25rem; }

.eq-editor {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 0.9rem;
  background: #f9fafb;
}
.eq-editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.eq-editor-head h3 { font-size: 0.9rem; font-weight: 600; color: #111827; margin: 0; }
.eq-actions { display: flex; gap: 0.4rem; }
.eq-desc { font-size: 0.75rem; color: #6b7280; line-height: 1.5; margin: 0.4rem 0 0; }

.eq-status {
  font-size: 0.75rem;
  border-radius: 4px;
  padding: 0.3rem 0.5rem;
  margin: 0.5rem 0 0;
}
.eq-status.ok { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
.eq-status.err { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }

.eq-fields { display: flex; flex-direction: column; gap: 1rem; margin-top: 0.8rem; }
.eq-group { display: flex; flex-direction: column; gap: 0.6rem; }
.eq-group h4 {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
  margin: 0;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 0.25rem;
}
.eq-field { display: flex; flex-direction: column; gap: 0.2rem; }
.eq-field label { font-size: 0.75rem; font-weight: 600; color: #374151; }
.eq-field-desc { font-size: 0.68rem; color: #9ca3af; margin: 0; }
.eq-field-vars { font-size: 0.65rem; color: #9ca3af; margin: 0; word-break: break-word; }
.eq-field-error { font-size: 0.68rem; color: #b91c1c; margin: 0; }
.eq-field textarea {
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 0.3rem 0.45rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.75rem;
  color: #111827;
  background: #fff;
  resize: vertical;
  min-height: 2rem;
}
.eq-field textarea.invalid { border-color: #f87171; background: #fef2f2; }
.eq-toggle {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  color: #374151;
  font-weight: 500;
}
.eq-toggle input { width: auto; }

.eq-rendered { display: flex; flex-direction: column; gap: 1rem; }
.eq-empty { font-size: 0.85rem; color: #6b7280; text-align: center; padding: 1.5rem 0; }
.eq-section { display: flex; flex-direction: column; gap: 0.5rem; }
.eq-section-title {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 0.25rem;
}
.eq-block {
  border-left: 2px solid #e5e7eb;
  padding-left: 0.7rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.eq-label { font-size: 0.76rem; font-weight: 600; color: #374151; }
.eq-label-dim { font-weight: 400; color: #9ca3af; }
.eq-render { overflow-x: auto; font-size: 0.95rem; }
.eq-params { font-size: 0.78rem; color: #6b7280; overflow-x: auto; }
.eq-legend-item {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  font-size: 0.78rem;
  color: #4b5563;
}
.eq-legend-sym { color: #111827; }

.btn-primary {
  background: #3b82f6;
  color: #fff;
  border: none;
  border-radius: 5px;
  padding: 0.3rem 0.75rem;
  font-size: 0.76rem;
  cursor: pointer;
}
.btn-primary:disabled { opacity: 0.6; cursor: default; }
.btn-primary:hover:not(:disabled) { background: #2563eb; }
.btn-ghost {
  background: #fff;
  color: #4b5563;
  border: 1px solid #d1d5db;
  border-radius: 5px;
  padding: 0.3rem 0.75rem;
  font-size: 0.76rem;
  cursor: pointer;
}
.btn-ghost:disabled { opacity: 0.6; cursor: default; }
.btn-ghost:hover:not(:disabled) { background: #f3f4f6; }
</style>
