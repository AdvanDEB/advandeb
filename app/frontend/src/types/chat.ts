export type CitationSourceType =
  | 'chunk'
  | 'fact'
  | 'stylized_fact'
  | 'external_document'

export type EvidenceMode =
  | 'local'
  | 'local_plus_external'
  | 'external_fallback_labeled'

export interface CitationRef {
  citation_id: string
  marker: string
  source_type: CitationSourceType
  document_id?: string
  chunk_id?: string
  fact_id?: string
  stylized_fact_id?: string
  evidence_text: string
  title?: string
  authors?: string[]
  year?: string | number
  journal?: string
  doi?: string
  url?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: CitationRef[]
  timestamp?: string
  generating?: boolean
  evidence_mode?: EvidenceMode
}
