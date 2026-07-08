<template>
  <div class="llm-config">
    <div class="row">
      <label>Model source</label>
      <select v-model="selectedSource" @change="emitConfig">
        <option value="default">Nemotron (default)</option>
        <option v-for="k in keys" :key="k.id" :value="k.id">
          {{ providerLabel(k.provider) }}{{ k.label ? ` · ${k.label}` : '' }} ••••{{ k.key_last_4 }}
        </option>
      </select>
    </div>

    <div class="row" v-if="modelOptions.length">
      <label>Model<span v-if="loadingModels" class="loading-dot" title="Loading models…"> …</span></label>
      <select v-model="selectedModel" :disabled="loadingModels" @change="emitConfig">
        <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
      </select>
    </div>

    <p v-if="selectedSource === 'default'" class="hint">
      Using <strong>{{ defaultModelInfo?.model || 'Nemotron' }}</strong> via NVIDIA NIM —
      shared across all users, rate-limited at {{ defaultModelInfo?.rpm ?? 40 }} req/min.
      <router-link to="/settings/llm-keys">Add your own key</router-link> for higher throughput.
    </p>
    <p v-else class="hint">
      Your {{ providerLabel(selectedProviderName) }} model will run the full
      multi-step agent (retrieval → reasoning → cited answer) over the knowledge base.
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { fetchDefaultModel, fetchKeyModels, listKeys, listProviders } from '@/utils/llmKeysApi'
import type { DefaultModelInfo, LLMKey, LLMProvider, LLMSessionConfig, Provider } from '@/types/llm'

const props = defineProps<{ modelValue?: LLMSessionConfig | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', cfg: LLMSessionConfig): void }>()

const keys = ref<LLMKey[]>([])
const providers = ref<Provider[]>([])
const defaultModelInfo = ref<DefaultModelInfo | null>(null)

// selectedSource: "default" | <key-id>
const selectedSource = ref<string>('default')
const selectedModel = ref<string>('')

const modelsByKey = ref<Record<string, string[]>>({})
const loadingModels = ref(false)

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Claude',
  openai: 'ChatGPT',
  gemini: 'Gemini',
  github_models: 'GitHub Models',
  nvidia: 'NVIDIA',
  default: 'Nemotron (default)',
}
function providerLabel(name: string): string {
  return PROVIDER_LABELS[name] || name
}

const selectedKey = computed<LLMKey | null>(() => {
  if (selectedSource.value === 'default') return null
  return keys.value.find((k) => k.id === selectedSource.value) ?? null
})

const selectedProviderName = computed<string>(() =>
  selectedKey.value?.provider ?? 'default',
)

const modelOptions = computed(() => {
  const key = selectedKey.value
  if (!key) return []
  if (modelsByKey.value[key.id]) return modelsByKey.value[key.id]
  const p = providers.value.find((x) => x.name === selectedProviderName.value)
  return p?.available_models ?? []
})

function emitConfig() {
  const key = selectedKey.value
  const cfg: LLMSessionConfig = {
    provider: (selectedSource.value === 'default' ? 'default' : selectedProviderName.value) as LLMProvider,
    mode: 'react',
    model: key ? (selectedModel.value || undefined) : undefined,
    key_id: key?.id,
  }
  emit('update:modelValue', cfg)
}

function chooseModel(models: string[], ...preferred: (string | null | undefined)[]): string {
  for (const p of preferred) {
    if (p && models.includes(p)) return p
  }
  return models[0] ?? ''
}

async function loadModelsForSource() {
  if (selectedSource.value === 'default') {
    emitConfig()
    return
  }

  const key = selectedKey.value
  if (!key) {
    emitConfig()
    return
  }

  const cached = modelsByKey.value[key.id]
  if (cached) {
    selectedModel.value = chooseModel(cached, selectedModel.value, key.default_model)
    emitConfig()
    return
  }

  selectedModel.value = chooseModel(modelOptions.value, selectedModel.value, key.default_model)
  emitConfig()

  loadingModels.value = true
  try {
    const res = await fetchKeyModels(key.id)
    if (res.models.length) {
      modelsByKey.value[key.id] = res.models
      selectedModel.value = chooseModel(res.models, selectedModel.value, key.default_model, res.default_model)
      emitConfig()
    }
  } catch {
    // curated fallback stays
  } finally {
    loadingModels.value = false
  }
}

watch(selectedSource, loadModelsForSource)

onMounted(async () => {
  const initialSource = selectedSource.value
  try {
    ;[keys.value, providers.value] = await Promise.all([listKeys(), listProviders()])
  } catch {
    // interceptor toasts
  }
  try {
    defaultModelInfo.value = await fetchDefaultModel()
  } catch {
    // leave null; option stays visible
  }

  if (props.modelValue) {
    if (props.modelValue.provider === 'default' || props.modelValue.provider === 'ollama') {
      // ollama sessions from before this change are reassigned to default
      selectedSource.value = 'default'
    } else if (props.modelValue.key_id) {
      selectedSource.value = props.modelValue.key_id
    }
    if (props.modelValue.model) selectedModel.value = props.modelValue.model
  }

  if (selectedSource.value === initialSource) {
    await loadModelsForSource()
  }
})
</script>

<style scoped>
.llm-config {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}
.row { display: flex; align-items: center; gap: 0.6rem; }
.row label {
  font-size: 0.78rem;
  font-weight: 600;
  color: #4b5563;
  width: 96px;
  flex-shrink: 0;
}
.row select {
  flex: 1;
  padding: 0.35rem 0.5rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 0.85rem;
}
.loading-dot { color: #3b82f6; font-weight: 700; }
.hint { font-size: 0.78rem; color: #6b7280; margin: 0; }
.hint a { color: #3b82f6; }
</style>
