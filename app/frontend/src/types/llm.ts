/**
 * Type definitions for the BYOK (Bring-Your-Own-Key) LLM feature.
 *
 * The plaintext api_key only flows from the form to the backend via
 * `LLMKeyCreate`; it is never returned by the API or kept in any
 * client-side store. The backend always returns `key_last_4` instead.
 */

export type LLMProvider =
  | 'ollama'
  | 'anthropic'
  | 'openai'
  | 'gemini'
  | 'github_models'

export type LLMMode = 'final' | 'react'

export interface LLMKey {
  id: string
  provider: LLMProvider
  label: string | null
  default_model: string | null
  /** Last 4 characters of the original key, e.g. "abcd". Safe to display. */
  key_last_4: string
  /** ISO timestamp. */
  created_at: string
  /** ISO timestamp; null if the key has not been used yet. */
  last_used_at: string | null
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

export interface LLMSessionConfig {
  provider: LLMProvider
  mode: LLMMode
  model?: string
  key_id?: string
}
