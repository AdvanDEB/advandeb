<template>
  <section class="card guidelines" :class="{ open }">
    <button class="disclose" @click="open = !open">
      {{ open ? '▾' : '▸' }} Guidelines — {{ spec.title }}
      <span v-if="version" class="version">v{{ version }}</span>
    </button>

    <div v-if="open" class="body">
      <p class="intro">{{ spec.help }}</p>

      <dl class="labels">
        <template v-for="o in spec.options" :key="o.value">
          <dt>{{ o.label }}</dt>
          <dd>
            <p>{{ remote(o.value)?.description || o.hint }}</p>
            <p v-if="remote(o.value)?.positive_example" class="ex yes">
              <span class="tag">Yes</span> {{ remote(o.value)?.positive_example }}
            </p>
            <p v-if="remote(o.value)?.negative_example" class="ex no">
              <span class="tag">No</span> {{ remote(o.value)?.negative_example }}
            </p>
          </dd>
        </template>
      </dl>

      <p v-if="unavailable" class="fallback">
        Showing the built-in summaries — the full guidelines document could not
        be loaded. Your judgment is still recorded normally.
      </p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import api from '@/utils/api'
import { taskSpec, type TaskType } from './taskOptions'

const props = defineProps<{ task: TaskType }>()

const open = ref(false)
const version = ref<string | null>(null)
const unavailable = ref(false)
// task -> label value -> { description, positive_example, negative_example }
const remoteLabels = ref<Record<string, Record<string, any>>>({})

const spec = computed(() => taskSpec(props.task))

function remote(value: string) {
  return remoteLabels.value?.[props.task]?.[value]
}

async function fetchGuidelines() {
  try {
    const { data } = await api.get('/elicitation/guidelines')
    version.value = data?.version ?? null
    const byTask: Record<string, Record<string, any>> = {}
    for (const [task, block] of Object.entries<any>(data?.tasks ?? {})) {
      byTask[task] = {}
      for (const l of block?.labels ?? []) byTask[task][l.value] = l
    }
    remoteLabels.value = byTask
    unavailable.value = false
  } catch {
    // Guidelines are an aid, not a gate. If the endpoint is missing the expert
    // still sees the built-in hints and can judge; failing the whole view here
    // would block elicitation over a help text.
    unavailable.value = true
  }
}

watch(() => props.task, () => {}, { immediate: false })
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

.ex { margin-top: 0.25rem; font-size: 0.8rem; }
.tag { display: inline-block; border-radius: 4px; padding: 0 0.3rem; font-size: 0.7rem; font-weight: 600; margin-right: 0.35rem; }
.ex.yes .tag { background: #dcfce7; color: #166534; }
.ex.no .tag { background: #fee2e2; color: #991b1b; }

.fallback { margin-top: 0.8rem; font-size: 0.78rem; color: #9ca3af; }
</style>
