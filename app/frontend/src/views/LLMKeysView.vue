<template>
  <div class="llm-keys-view">
    <header class="page-header">
      <h1>LLM API Keys</h1>
      <p class="subtitle">
        Bring your own keys for Claude, ChatGPT, Gemini, or GitHub Models. Your key is
        used only to power chat reasoning over the AdvanDEB knowledge base, and is
        encrypted at rest. We store and display only the last four characters.
      </p>
    </header>

    <!-- Add-key form -->
    <section class="card">
      <h2>Add a key</h2>
      <form class="add-form" @submit.prevent="onCreate">
        <div class="field">
          <label for="provider">Provider</label>
          <select id="provider" v-model="form.provider" @change="onProviderChange">
            <option v-for="p in providers" :key="p.name" :value="p.name">
              {{ providerLabel(p.name) }}
            </option>
          </select>
        </div>

        <div class="field">
          <label for="model">Default model</label>
          <select id="model" v-model="form.default_model">
            <option v-for="m in modelsForSelected" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>

        <div class="field">
          <label for="label">Label <span class="optional">(optional)</span></label>
          <input id="label" v-model="form.label" type="text" placeholder="e.g. work key" />
        </div>

        <div class="field grow">
          <label for="apikey">API key {{ form.provider === 'github_models' ? '(GitHub PAT)' : '' }}</label>
          <input
            id="apikey"
            v-model="form.api_key"
            type="password"
            autocomplete="off"
            placeholder="Paste your key — it is validated, encrypted, then forgotten"
          />
        </div>

        <button type="submit" class="btn primary" :disabled="creating || !form.api_key">
          {{ creating ? 'Validating…' : 'Validate & save' }}
        </button>
      </form>
    </section>

    <!-- Stored keys -->
    <section class="card">
      <h2>Stored keys</h2>
      <p v-if="loading" class="muted">Loading…</p>
      <p v-else-if="keys.length === 0" class="muted">No keys yet. Add one above.</p>
      <table v-else class="keys-table">
        <thead>
          <tr>
            <th>Provider</th>
            <th>Label</th>
            <th>Model</th>
            <th>Key</th>
            <th>Last used</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="k in keys" :key="k.id">
            <td>{{ providerLabel(k.provider) }}</td>
            <td>{{ k.label || '—' }}</td>
            <td>{{ k.default_model || '—' }}</td>
            <td><code>••••{{ k.key_last_4 }}</code></td>
            <td>{{ k.last_used_at ? formatDate(k.last_used_at) : 'never' }}</td>
            <td class="actions">
              <button class="btn small" :disabled="testingId === k.id" @click="onTest(k)">
                {{ testingId === k.id ? 'Testing…' : 'Test' }}
              </button>
              <button class="btn small danger" :disabled="deletingId === k.id" @click="onDelete(k)">
                Delete
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useNotificationsStore } from '@/stores/notifications'
import {
  createKey,
  deleteKey,
  listKeys,
  listProviders,
  testKey,
} from '@/utils/llmKeysApi'
import type { LLMKey, LLMProvider, Provider } from '@/types/llm'

const notifs = useNotificationsStore()

const providers = ref<Provider[]>([])
const keys = ref<LLMKey[]>([])
const loading = ref(true)
const creating = ref(false)
const testingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic (Claude)',
  openai: 'OpenAI (ChatGPT)',
  gemini: 'Google Gemini',
  github_models: 'GitHub Models',
  ollama: 'Ollama (local)',
}

const form = reactive<{
  provider: LLMProvider
  default_model: string
  label: string
  api_key: string
}>({
  provider: 'anthropic',
  default_model: '',
  label: '',
  api_key: '',
})

const modelsForSelected = computed(() => {
  const p = providers.value.find((x) => x.name === form.provider)
  return p?.available_models ?? []
})

function providerLabel(name: string): string {
  return PROVIDER_LABELS[name] || name
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function onProviderChange() {
  // Default the model picker to the provider's first/default model.
  const p = providers.value.find((x) => x.name === form.provider)
  form.default_model = p?.default_model || p?.available_models?.[0] || ''
}

async function refreshKeys() {
  loading.value = true
  try {
    keys.value = await listKeys()
  } catch {
    // api interceptor already toasts non-401 errors
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  if (!form.api_key) return
  creating.value = true
  try {
    await createKey({
      provider: form.provider,
      api_key: form.api_key,
      label: form.label || undefined,
      default_model: form.default_model || undefined,
    })
    notifs.success(`${providerLabel(form.provider)} key validated and saved`)
    form.api_key = ''
    form.label = ''
    await refreshKeys()
  } catch {
    // interceptor surfaces the sanitized backend detail
  } finally {
    creating.value = false
  }
}

async function onTest(k: LLMKey) {
  testingId.value = k.id
  try {
    const res = await testKey(k.id)
    if (res.ok) {
      notifs.success(`${providerLabel(k.provider)} key is valid (${res.model})`)
      await refreshKeys()
    }
  } catch {
    // interceptor toasts the failure
  } finally {
    testingId.value = null
  }
}

async function onDelete(k: LLMKey) {
  if (!confirm(`Delete the ${providerLabel(k.provider)} key ending ${k.key_last_4}?`)) return
  deletingId.value = k.id
  try {
    await deleteKey(k.id)
    notifs.info('Key deleted')
    await refreshKeys()
  } catch {
    // interceptor toasts the failure
  } finally {
    deletingId.value = null
  }
}

onMounted(async () => {
  try {
    providers.value = await listProviders()
    onProviderChange()
  } catch {
    // interceptor toasts
  }
  await refreshKeys()
})
</script>

<style scoped>
.llm-keys-view {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  max-width: 900px;
}
.page-header h1 { font-size: 1.5rem; font-weight: 700; color: #111827; }
.subtitle { color: #6b7280; line-height: 1.6; max-width: 640px; margin-top: 0.4rem; }

.card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 1.25rem 1.5rem;
}
.card h2 { font-size: 1.05rem; font-weight: 600; color: #374151; margin-bottom: 1rem; }

.add-form {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: flex-end;
}
.field { display: flex; flex-direction: column; gap: 0.3rem; min-width: 160px; }
.field.grow { flex: 1; min-width: 240px; }
.field label { font-size: 0.8rem; font-weight: 600; color: #4b5563; }
.optional { font-weight: 400; color: #9ca3af; }
.field input, .field select {
  padding: 0.5rem 0.6rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 0.9rem;
}
.field input:focus, .field select:focus { outline: none; border-color: #3b82f6; }

.btn {
  border: 1px solid #d1d5db;
  background: #fff;
  color: #374151;
  border-radius: 6px;
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.btn:hover:not(:disabled) { background: #f9fafb; }
.btn:disabled { opacity: 0.6; cursor: default; }
.btn.primary { background: #3b82f6; border-color: #3b82f6; color: #fff; }
.btn.primary:hover:not(:disabled) { background: #2563eb; }
.btn.small { padding: 0.3rem 0.7rem; font-size: 0.78rem; }
.btn.danger { color: #ef4444; border-color: #fecaca; }
.btn.danger:hover:not(:disabled) { background: #fef2f2; }

.keys-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
.keys-table th {
  text-align: left;
  font-weight: 600;
  color: #6b7280;
  font-size: 0.75rem;
  text-transform: uppercase;
  padding: 0.5rem 0.6rem;
  border-bottom: 1px solid #e5e7eb;
}
.keys-table td { padding: 0.6rem; border-bottom: 1px solid #f3f4f6; color: #374151; }
.keys-table code { background: #f3f4f6; padding: 0.1rem 0.35rem; border-radius: 4px; }
.actions { display: flex; gap: 0.4rem; }
.muted { color: #9ca3af; font-size: 0.9rem; }
</style>
