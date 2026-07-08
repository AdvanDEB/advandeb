/**
 * Type definitions for the BYOK (Bring-Your-Own-Key) LLM feature.
 *
 * The plaintext api_key only flows from the form to the backend via
 * `LLMKeyCreate`; it is never returned by the API or kept in any
 * client-side store. The backend always returns `key_last_4` instead.
 */

export type LLMProvider =
  | 'default'
  | 'ollama'
  | 'anthropic'
  | 'openai'
  | 'gemini'
  | 'github_models'
  | 'nvidia'

export type LLMMode = 'final' | 'react'

export type CredentialType = 'api_key' | 'oauth'

export interface LLMKey {
  id: string
  provider: LLMProvider
  /** "api_key" (pasted secret) or "oauth" (e.g. GitHub device-flow connection). */
  credential_type: CredentialType
  label: string | null
  default_model: string | null
  /** Last 4 chars of a pasted key. Null for OAuth connections. */
  key_last_4: string | null
  /** Connected account (e.g. GitHub login). Present for OAuth connections. */
  account_label: string | null
  /** ISO timestamp. */
  created_at: string
  /** ISO timestamp; null if the key has not been used yet. */
  last_used_at: string | null
}

/** Whether sanctioned OAuth connect flows are configured on the server. */
export interface OAuthConfig {
  github_enabled: boolean
}

/** Response from starting a GitHub device flow. */
export interface DeviceFlowStart {
  flow_id: string
  user_code: string
  verification_uri: string
  interval: number
  expires_in: number
}

/** Response from polling a GitHub device flow. */
export interface DeviceFlowPoll {
  status: 'pending' | 'slow_down' | 'expired' | 'denied' | 'complete'
  interval?: number
  key?: LLMKey
}

export interface LLMKeyCreate {
  provider: LLMProvider
  api_key: string
  label?: string
  default_model?: string
}

export interface Provider {
  name: LLMProvider
  default_model: string
  available_models: string[]
}

/** Live model catalog fetched for a pasted (provider, api_key) pair. */
export interface ProviderModels {
  models: string[]
  default_model: string
}

export interface LLMSessionConfig {
  provider: LLMProvider
  mode: LLMMode
  model?: string
  key_id?: string
}

export interface DefaultModelInfo {
  available: boolean
  provider: string
  model: string
  rpm: number
}
