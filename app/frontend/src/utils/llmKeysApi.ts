/**
 * Typed helpers for the BYOK LLM key API (/api/users/me/llm-keys).
 *
 * The plaintext api_key is only ever sent (on createKey); it is never returned.
 * Responses carry `key_last_4` for display.
 */
import api from './api'
import type {
  DefaultModelInfo,
  DeviceFlowPoll,
  DeviceFlowStart,
  LLMKey,
  LLMKeyCreate,
  OAuthConfig,
  Provider,
  ProviderModels,
} from '@/types/llm'

const BASE = '/users/me/llm-keys'

/** Catalog of BYOK providers + their selectable models (excludes ollama). */
export async function listProviders(): Promise<Provider[]> {
  const { data } = await api.get<Provider[]>(`${BASE}/providers`)
  return data
}

/**
 * Fetch the live model catalog a stored key can actually use. The plaintext
 * secret stays on the server; the UI asks by key id.
 */
export async function fetchKeyModels(keyId: string): Promise<ProviderModels> {
  const { data } = await api.get<ProviderModels>(`${BASE}/${keyId}/models`)
  return data
}

/** Locally-available Ollama models (for the chat model picker, "Local" source). */
export async function fetchLocalModels(): Promise<ProviderModels> {
  const { data } = await api.get<ProviderModels>('/chat/local-models')
  return data
}

/** Info about the operator-configured default model (Nemotron). */
export async function fetchDefaultModel(): Promise<DefaultModelInfo> {
  const { data } = await api.get<DefaultModelInfo>('/chat/default-model')
  return data
}

/** List the current user's stored keys (no plaintext). */
export async function listKeys(): Promise<LLMKey[]> {
  const { data } = await api.get<LLMKey[]>(BASE)
  return data
}

/** Validate, encrypt, and store a new key. Returns the stored key (no plaintext). */
export async function createKey(body: LLMKeyCreate): Promise<LLMKey> {
  const { data } = await api.post<LLMKey>(BASE, body)
  return data
}

/** Re-validate a stored key against its provider. */
export async function testKey(keyId: string): Promise<{ ok: boolean; model: string }> {
  const { data } = await api.post<{ ok: boolean; model: string }>(`${BASE}/${keyId}/test`)
  return data
}

/** Delete a stored key. */
export async function deleteKey(keyId: string): Promise<void> {
  await api.delete(`${BASE}/${keyId}`)
}

/** Which sanctioned OAuth connect flows the server has configured. */
export async function getOauthConfig(): Promise<OAuthConfig> {
  const { data } = await api.get<OAuthConfig>(`${BASE}/oauth/config`)
  return data
}

/** Begin the GitHub device flow. Returns the user code + verification URI. */
export async function startGithubOauth(): Promise<DeviceFlowStart> {
  const { data } = await api.post<DeviceFlowStart>(`${BASE}/oauth/github/start`)
  return data
}

/** Poll a pending GitHub device flow once. */
export async function pollGithubOauth(flowId: string): Promise<DeviceFlowPoll> {
  const { data } = await api.post<DeviceFlowPoll>(`${BASE}/oauth/github/poll`, {
    flow_id: flowId,
  })
  return data
}
