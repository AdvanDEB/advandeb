<template>
  <div class="llm-config">
    <div class="row">
      <label>Model source</label>
      <select v-model="selectedSource" @change="emitConfig">
        <option value="ollama">Ollama (local)</option>
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

    <div class="row">
      <label>Reasoning</label>
      <select v-model="selectedMode" @change="emitConfig">
        <option value="final">Final answer (fast)</option>
        <option value="react">ReAct (multi-step)</option>
      </select>
    </div>

    <p v-if="selectedSource !== 'ollama'" class="hint">
      Your {{ providerLabel(selectedProviderName) }} model will run the full
      multi-step agent (retrieval → reasoning → cited answer) over the knowledge base.
    </p>
    <p v-else-if="keys.length === 0" class="hint">
      No personal keys yet —
      <router-link to="/settings/llm-keys">add one</router-link>
      to use Claude, ChatGPT, Gemini, or GitHub Models.
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { fetchKeyModels, fetchLocalModels, listKeys, listProviders } from '@/utils/llmKeysApi'
import type { LLMKey, LLMMode, LLMSessionConfig, Provider } from '@/types/llm'

const props = defineProps<{ modelValue?: LLMSessionConfig | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', cfg: LLMSessionConfig): void }>()

const keys = ref<LLMKey[]>([])
const providers = ref<Provider[]>([])

// selectedSource is either "ollama" or a stored key id.
const selectedSource = ref<string>('ollama')
const selectedModel = ref<string>('')
const selectedMode = ref<LLMMode>('react')

// Live model catalog per stored key id, fetched on demand and cached.
const modelsByKey = ref<Record<string, string[]>>({})
const loadingModels = ref(false)

// Locally-available Ollama models (the "Local" source), fetched once and cached.
const ollamaModels = ref<string[]>([])
const ollamaDefault = ref<string>('')

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Claude',
  openai: 'ChatGPT',
  gemini: 'Gemini',
  github_models: 'GitHub Models',
  ollama: 'Ollama',
}
function providerLabel(name: string): string {
  return PROVIDER_LABELS[name] || name
}

const selectedKey = computed<LLMKey | null>(() =>
  selectedSource.value === 'ollama'
    ? null
    : keys.value.find((k) => k.id === selectedSource.value) ?? null,
)

const selectedProviderName = computed(() => selectedKey.value?.provider ?? 'ollama')

const modelOptions = computed(() => {
  const key = selectedKey.value
  // Ollama (Local): the locally-installed models reported by the backend.
  if (!key) return ollamaModels.value
  // Prefer the live catalog for the selected key; fall back to curated list
  // (e.g. while the catalog is still loading).
  if (modelsByKey.value[key.id]) return modelsByKey.value[key.id]
  const p = providers.value.find((x) => x.name === selectedProviderName.value)
  return p?.available_models ?? []
})

function emitConfig() {
  const cfg: LLMSessionConfig = {
    provider: selectedProviderName.value,
    mode: selectedMode.value,
    model: selectedModel.value || undefined,
    key_id: selectedKey.value?.id,
  }
  emit('update:modelValue', cfg)
}

/** Pick the best model from a list, preferring an already-chosen valid one. */
function chooseModel(models: string[], ...preferred: (string | null | undefined)[]): string {
  for (const p of preferred) {
    if (p && models.includes(p)) return p
  }
  return models[0] ?? ''
}

/**
 * Load (and cache) the live model catalog for the selected source, then pick a
 * sensible model. Ollama has no per-key catalog, so it uses the curated list.
 */
async function loadModelsForSource() {
  const key = selectedKey.value
  if (!key) {
    // Ollama (Local): fetch the installed models once, then pick one. An empty
    // selection means "let the backend use its default model".
    if (!ollamaModels.value.length) {
      loadingModels.value = true
      try {
        const res = await fetchLocalModels()
        ollamaModels.value = res.models
        ollamaDefault.value = res.default_model
      } catch {
        // interceptor toasts; empty list falls back to the backend default
      } finally {
        loadingModels.value = false
      }
    }
    selectedModel.value = chooseModel(ollamaModels.value, selectedModel.value, ollamaDefault.value)
    emitConfig()
    return
  }

  const cached = modelsByKey.value[key.id]
  if (cached) {
    selectedModel.value = chooseModel(cached, selectedModel.value, key.default_model)
    emitConfig()
    return
  }

  // Show a provisional pick from the curated list while the catalog loads.
  selectedModel.value = chooseModel(modelOptions.value, selectedModel.value, key.default_model)
  emitConfig()

  loadingModels.value = true
  try {
    const res = await fetchKeyModels(key.id)
    if (res.models.length) {
      modelsByKey.value[key.id] = res.models
      selectedModel.value = chooseModel(
        res.models,
        selectedModel.value,
        key.default_model,
        res.default_model,
      )
      emitConfig()
    }
  } catch {
    // interceptor toasts; the curated fallback remains usable
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
    // interceptor toasts; panel still works with the Ollama default
  }
  // Hydrate from an existing session config if provided, else default to the
  // user's most recent key (so a key holder gets their own model by default).
  if (props.modelValue) {
    selectedMode.value = props.modelValue.mode
    if (props.modelValue.key_id) selectedSource.value = props.modelValue.key_id
    if (props.modelValue.model) selectedModel.value = props.modelValue.model
  } else if (keys.value.length > 0) {
    selectedSource.value = keys.value[0].id // listKeys() returns most-recent first
  }
  // If selectedSource changed above, the watcher already loads the catalog;
  // otherwise (still Ollama) emit the initial config ourselves.
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
.hint.warn { color: #b45309; }
.hint a { color: #3b82f6; }
</style>
