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
          <select id="provider" v-model="form.provider">
            <option v-for="p in providers" :key="p.name" :value="p.name">
              {{ providerLabel(p.name) }}
            </option>
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

    <!-- Connect an account via a sanctioned OAuth device flow -->
    <section v-if="oauthConfig.github_enabled" class="card">
      <h2>Connect with GitHub</h2>
      <p class="muted connect-note">
        Authorize with your GitHub account to use <strong>GitHub Models</strong> —
        no API key to paste. This uses GitHub's free, rate-limited model catalog
        (not a paid Copilot subscription).
      </p>
      <button class="btn primary" :disabled="connecting" @click="onConnectGithub">
        {{ connecting ? 'Waiting for authorization…' : 'Connect with GitHub' }}
      </button>
    </section>

    <!-- Device-flow modal -->
    <div v-if="device" class="modal-backdrop" @click.self="cancelDevice">
      <div class="modal">
        <h3>Authorize on GitHub</h3>
        <p class="muted">Enter this code on GitHub to connect your account:</p>
        <div class="user-code">{{ device.user_code }}</div>
        <a class="btn primary open-link" :href="device.verification_uri" target="_blank" rel="noopener">
          Open github.com/login/device
        </a>
        <p class="device-status">{{ deviceStatus }}</p>
        <button class="btn small" @click="cancelDevice">Cancel</button>
      </div>
    </div>

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
            <td>
              <code v-if="k.credential_type === 'oauth'" title="Connected via GitHub OAuth">
                @{{ k.account_label || 'connected' }}
              </code>
              <code v-else>••••{{ k.key_last_4 }}</code>
            </td>
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
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useNotificationsStore } from '@/stores/notifications'
import {
  createKey,
  deleteKey,
  getOauthConfig,
  listKeys,
  listProviders,
  pollGithubOauth,
  startGithubOauth,
  testKey,
} from '@/utils/llmKeysApi'
import type {
  DeviceFlowStart,
  LLMKey,
  LLMProvider,
  OAuthConfig,
  Provider,
} from '@/types/llm'

const notifs = useNotificationsStore()

const providers = ref<Provider[]>([])
const keys = ref<LLMKey[]>([])
const loading = ref(true)
const creating = ref(false)
const testingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)

// OAuth "Connect with GitHub" device flow.
const oauthConfig = ref<OAuthConfig>({ github_enabled: false })
const connecting = ref(false)
const device = ref<DeviceFlowStart | null>(null)
const deviceStatus = ref('')
let pollTimer: number | undefined

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic (Claude)',
  openai: 'OpenAI (ChatGPT)',
  gemini: 'Google Gemini',
  github_models: 'GitHub Models',
  ollama: 'Ollama (local)',
}

const form = reactive<{
  provider: LLMProvider
  label: string
  api_key: string
}>({
  provider: 'anthropic',
  label: '',
  api_key: '',
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
    const created = await createKey({
      provider: form.provider,
      api_key: form.api_key,
      label: form.label || undefined,
    })
    const modelNote = created.default_model ? ` (model: ${created.default_model})` : ''
    notifs.success(`${providerLabel(form.provider)} key validated and saved${modelNote}`)
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

async function onConnectGithub() {
  connecting.value = true
  try {
    device.value = await startGithubOauth()
    deviceStatus.value = 'Waiting for you to authorize on GitHub…'
    window.open(device.value.verification_uri, '_blank', 'noopener')
    schedulePoll(device.value.flow_id, device.value.interval)
  } catch {
    // interceptor toasts the failure
    connecting.value = false
  }
}

function schedulePoll(flowId: string, intervalSec: number) {
  pollTimer = window.setTimeout(async () => {
    if (!device.value) return
    try {
      const res = await pollGithubOauth(flowId)
      if (res.status === 'complete') {
        const who = res.key?.account_label ? ` as @${res.key.account_label}` : ''
        notifs.success(`GitHub connected${who} — GitHub Models is ready`)
        cancelDevice()
        await refreshKeys()
        return
      }
      if (res.status === 'denied') {
        deviceStatus.value = 'Authorization was denied on GitHub.'
        stopPolling()
        return
      }
      if (res.status === 'expired') {
        deviceStatus.value = 'The code expired. Close this and try again.'
        stopPolling()
        return
      }
      // pending / slow_down → keep polling (respect a bumped interval).
      const next = res.status === 'slow_down' && res.interval ? res.interval : intervalSec
      schedulePoll(flowId, next)
    } catch {
      deviceStatus.value = 'Connection check failed. Close this and try again.'
      stopPolling()
    }
  }, intervalSec * 1000)
}

function stopPolling() {
  connecting.value = false
  if (pollTimer) {
    window.clearTimeout(pollTimer)
    pollTimer = undefined
  }
}

function cancelDevice() {
  device.value = null
  deviceStatus.value = ''
  stopPolling()
}

onUnmounted(stopPolling)

onMounted(async () => {
  try {
    providers.value = await listProviders()
  } catch {
    // interceptor toasts
  }
  try {
    oauthConfig.value = await getOauthConfig()
  } catch {
    // leave disabled on failure
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

.connect-note { margin-bottom: 1rem; max-width: 560px; line-height: 1.5; }

.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(17, 24, 39, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  background: #fff;
  border-radius: 10px;
  padding: 1.75rem 2rem;
  width: min(420px, 90vw);
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  align-items: center;
}
.modal h3 { font-size: 1.15rem; font-weight: 700; color: #111827; }
.user-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 1.9rem;
  font-weight: 700;
  letter-spacing: 0.25em;
  color: #111827;
  background: #f3f4f6;
  border-radius: 8px;
  padding: 0.6rem 1rem;
}
.open-link { text-decoration: none; display: inline-block; }
.device-status { color: #6b7280; font-size: 0.85rem; min-height: 1.2em; }
</style>
