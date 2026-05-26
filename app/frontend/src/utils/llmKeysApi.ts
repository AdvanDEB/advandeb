/**
 * Typed helpers for the BYOK LLM key API (/api/users/me/llm-keys).
 *
 * The plaintext api_key is only ever sent (on createKey); it is never returned.
 * Responses carry `key_last_4` for display.
 */
import api from './api'
import type { LLMKey, LLMKeyCreate, Provider } from '@/types/llm'

const BASE = '/users/me/llm-keys'

/** Catalog of BYOK providers + their selectable models (excludes ollama). */
export async function listProviders(): Promise<Provider[]> {
  const { data } = await api.get<Provider[]>(`${BASE}/providers`)
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
