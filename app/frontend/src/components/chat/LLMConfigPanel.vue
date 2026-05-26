<template>
  <div class="llm-config">
    <div class="row">
      <label>Model source</label>
      <select v-model="selectedSource" @change="emitConfig">
        <option value="ollama">Ollama (local default)</option>
        <option v-for="k in keys" :key="k.id" :value="k.id">
          {{ providerLabel(k.provider) }}{{ k.label ? ` · ${k.label}` : '' }} ••••{{ k.key_last_4 }}
        </option>
      </select>
    </div>

    <div class="row" v-if="modelOptions.length">
      <label>Model</label>
      <select v-model="selectedModel" @change="emitConfig">
        <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
      </select>
    </div>

    <div class="row">
      <label>Reasoning</label>
      <select v-model="selectedMode" @change="emitConfig">
        <option value="final">Final answer (fast)</option>
        <option value="react">ReAct (multi-step, Ollama only)</option>
      </select>
    </div>

    <p v-if="reactWithByok" class="hint warn">
      ReAct multi-step reasoning currently runs on local Ollama. Your selected key
      will be used for the final-answer mode instead.
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
import { listKeys, listProviders } from '@/utils/llmKeysApi'
import type { LLMKey, LLMMode, LLMSessionConfig, Provider } from '@/types/llm'

const props = defineProps<{ modelValue?: LLMSessionConfig | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', cfg: LLMSessionConfig): void }>()

const keys = ref<LLMKey[]>([])
const providers = ref<Provider[]>([])

// selectedSource is either "ollama" or a stored key id.
const selectedSource = ref<string>('ollama')
const selectedModel = ref<string>('')
const selectedMode = ref<LLMMode>('final')

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
  const p = providers.value.find((x) => x.name === selectedProviderName.value)
  return p?.available_models ?? []
})

const reactWithByok = computed(
  () => selectedMode.value === 'react' && selectedSource.value !== 'ollama',
)

function emitConfig() {
  const cfg: LLMSessionConfig = {
    provider: selectedProviderName.value,
    mode: selectedMode.value,
    model: selectedModel.value || undefined,
    key_id: selectedKey.value?.id,
  }
  emit('update:modelValue', cfg)
}

// When the source changes, default the model to the key's default or first option.
watch(selectedSource, () => {
  const key = selectedKey.value
  const p = providers.value.find((x) => x.name === selectedProviderName.value)
  selectedModel.value = key?.default_model || p?.default_model || p?.available_models?.[0] || ''
})

onMounted(async () => {
  try {
    ;[keys.value, providers.value] = await Promise.all([listKeys(), listProviders()])
  } catch {
    // interceptor toasts; panel still works with the Ollama default
  }
  // Hydrate from an existing session config if provided.
  if (props.modelValue) {
    selectedMode.value = props.modelValue.mode
    if (props.modelValue.key_id) selectedSource.value = props.modelValue.key_id
    if (props.modelValue.model) selectedModel.value = props.modelValue.model
  }
  emitConfig()
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
.hint { font-size: 0.78rem; color: #6b7280; margin: 0; }
.hint.warn { color: #b45309; }
.hint a { color: #3b82f6; }
</style>
