<template>
  <section class="card guidelines" :class="{ open }">
    <button class="disclose" @click="open = !open">
      {{ open ? '▾' : '▸' }} Guidelines — {{ spec.title }}
      <span v-if="version" class="version">v{{ version }}</span>
    </button>

    <div v-if="open" class="body">
      <template v-if="sections.length">
        <div v-for="sec in sections" :key="sec.task" class="section">
          <h4 v-if="sections.length > 1">{{ sec.title }}</h4>
          <p class="intro">{{ sec.help }}</p>
          <dl v-if="sec.options.length" class="labels">
            <template v-for="o in sec.options" :key="o.value">
              <dt>{{ o.label }}</dt>
              <dd><p>{{ o.hint }}</p></dd>
            </template>
          </dl>
        </div>
      </template>

      <template v-else>
        <p class="intro">{{ spec.help }}</p>
        <dl class="labels">
          <template v-for="o in spec.options" :key="o.value">
            <dt>{{ o.label }}</dt>
            <dd><p>{{ o.hint }}</p></dd>
          </template>
        </dl>
        <p v-if="unavailable" class="fallback">
          Showing the built-in summaries — the served guidelines could not be
          loaded. Your judgment is still recorded normally.
        </p>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import api from '@/utils/api'
import type {
  GuidelineSection, Guidelines, TaskGuideline,
} from '@/types/elicitation.generated'
import { taskSpec, type TaskType } from './taskOptions'

const props = defineProps<{ task: TaskType }>()

const open = ref(false)
const version = ref<string | null>(null)
const unavailable = ref(false)
const served = ref<TaskGuideline[]>([])

// The evidence task is defined in four served sections: the task, the
// passage role, and the two fact-level scores.
const SECTIONS: Partial<Record<TaskType, GuidelineSection[]>> = {
  evidence: ['evidence', 'evidence_role', 'evidence_strength', 'consensus_direction'],
}

const spec = computed(() => taskSpec(props.task))
const sections = computed(() => {
  const want = SECTIONS[props.task] ?? [props.task]
  return want
    .map((k) => served.value.find((t) => t.task === k))
    .filter((t): t is TaskGuideline => !!t)
})

async function fetchGuidelines() {
  try {
    const { data } = await api.get<Guidelines>('/elicitation/guidelines')
    version.value = data.version
    served.value = data.tasks
    unavailable.value = false
  } catch {
    // Guidelines are an aid, not a gate. If the endpoint fails the expert
    // still sees the built-in hints and can judge; failing the whole view
    // here would block elicitation over a help text.
    unavailable.value = true
  }
}

fetchGuidelines()

defineExpose({ toggle: () => { open.value = !open.value } })
</script>

<style scoped>
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 0.6rem 1rem; }
.guidelines.open { padding-bottom: 1rem; }
.disclose { background: none; border: none; cursor: pointer; font-size: 0.85rem; color: #4b5563; padding: 0.2rem 0; text-align: left; width: 100%; }
.version { color: #9ca3af; margin-left: 0.4rem; font-size: 0.75rem; }

.body { margin-top: 0.7rem; }
.intro { font-size: 0.85rem; color: #4b5563; line-height: 1.55; margin-bottom: 0.8rem; }

.labels { display: grid; grid-template-columns: max-content 1fr; gap: 0.35rem 0.9rem; font-size: 0.85rem; }
.labels dt { font-weight: 600; color: #111827; white-space: nowrap; }
.labels dd { color: #4b5563; line-height: 1.5; margin: 0 0 0.5rem; }

.section + .section { margin-top: 0.9rem; }
.section h4 { font-size: 0.85rem; font-weight: 600; color: #111827; margin-bottom: 0.3rem; }
.intro { white-space: pre-line; }

.fallback { margin-top: 0.8rem; font-size: 0.78rem; color: #9ca3af; }
</style>
