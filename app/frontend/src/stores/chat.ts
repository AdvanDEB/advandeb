import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/utils/api'
import type { ChatMessage, CitationRef, CitationSourceType } from '@/types/chat'
import type { LLMSessionConfig, LLMKey } from '@/types/llm'

export interface AgentStatus {
  name: string
  displayName: string
  status: 'idle' | 'working' | 'completed' | 'error'
  currentTask?: string
  resultSummary?: string
  startedAt?: number
}

export interface WorkflowStep {
  agent: string
  action: string
  timestamp: number
}

export interface Session {
  id: string
  title: string
  updated_at?: string
}

const AGENT_DISPLAY: Record<string, string> = {
  retrieval_agent: 'Retrieval',
  chatbot: 'Chatbot',
  synthesis_agent: 'Synthesis',
  claim_consensus: 'Claim Consensus',
  taxon_scope: 'Taxon Scope',
}

function agentDisplayName(name: string): string {
  return AGENT_DISPLAY[name] || name
}

function mapRawCitation(raw: Record<string, unknown>): CitationRef {
  const legacyNumber = raw.number as number | undefined
  const legacyMarker = typeof legacyNumber === 'number' ? String(legacyNumber) : ''
  const citationId =
    (raw.citation_id as string) ||
    (raw.chunk_id as string) ||
    (raw.fact_id as string) ||
    (raw.document_id as string) ||
    ''
  const marker = (raw.marker as string) || legacyMarker || citationId.slice(0, 8)
  const rawSourceType = (raw.source_type as string) || ''
  const source_type: CitationSourceType = (
    ['chunk', 'fact', 'stylized_fact', 'external_document'].includes(rawSourceType)
      ? rawSourceType
      : 'chunk'
  ) as CitationSourceType

  const rawAuthors = raw.authors
  const authors: string[] =
    Array.isArray(rawAuthors)
      ? rawAuthors.map(String)
      : typeof rawAuthors === 'string' && rawAuthors
        ? [rawAuthors]
        : []

  return {
    citation_id: citationId,
    marker,
    source_type,
    document_id: (raw.document_id as string) || undefined,
    chunk_id: (raw.chunk_id as string) || undefined,
    fact_id: (raw.fact_id as string) || undefined,
    stylized_fact_id: (raw.stylized_fact_id as string) || undefined,
    evidence_text: (raw.evidence_text as string) || (raw.text as string) || '',
    title: (raw.title as string) || undefined,
    authors,
    year: raw.year as string | number | undefined,
    journal: (raw.journal as string) || undefined,
    doi: (raw.doi as string) || undefined,
    url: (raw.url as string) || undefined,
  }
}

export function mapCitations(rawList: unknown[]): CitationRef[] {
  if (!Array.isArray(rawList)) return []
  return rawList.map((r) => mapRawCitation(r as Record<string, unknown>))
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const sessions = ref<Session[]>([])
  const currentSessionId = ref<string>('new')
  const responding = ref(false)
  const activeAgents = ref<AgentStatus[]>([])
  const workflowTrace = ref<WorkflowStep[]>([])
  const suggestedQuestions = ref<string[]>([])
  const streamingMessageId = ref<string | null>(null)
  const generatingMessageIds = ref<Set<string>>(new Set())

  const llmConfig = ref<LLMSessionConfig | null>(null)
  const pendingLLMConfig = ref<LLMSessionConfig | null>(null)
  const systemPrompt = ref<string>('')
  const userKeys = ref<LLMKey[]>([])

  const sessionSearchQuery = ref<string>('')

  const currentSessionTitle = computed(() => {
    const s = sessions.value.find((s) => s.id === currentSessionId.value)
    return s?.title || 'New conversation'
  })

  const filteredSessions = computed(() => {
    const q = sessionSearchQuery.value.trim().toLowerCase()
    if (!q) return sessions.value
    return sessions.value.filter((s) => s.title.toLowerCase().includes(q))
  })

  const lastUserMessage = computed(() => {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') return messages.value[i]
    }
    return null
  })

  function defaultLLMConfig(): LLMSessionConfig {
    return { provider: 'default', mode: 'react' }
  }

  function _findOrCreateStreamingMsg(): string {
    if (streamingMessageId.value) return streamingMessageId.value
    const id = crypto.randomUUID()
    streamingMessageId.value = id
    messages.value.push({
      id,
      role: 'assistant',
      content: '',
      streaming: true,
      generating: true,
    })
    return id
  }

  function appendToken(text: string) {
    const id = _findOrCreateStreamingMsg()
    const idx = messages.value.findIndex((m) => m.id === id)
    if (idx !== -1) {
      messages.value[idx] = { ...messages.value[idx], content: messages.value[idx].content + text }
    }
  }

  function _updateAgentStatus(event: Record<string, unknown>) {
    const name = (event.agent as string) || 'chatbot'
    const status = (event.status as AgentStatus['status']) || 'working'
    const existing = activeAgents.value.find((a) => a.name === name)
    const task = (event.task as string) || ''
    const result = (event.result as string) || ''

    if (existing) {
      existing.status = status
      existing.currentTask = task || existing.currentTask
      if (status === 'working') existing.startedAt = Date.now()
      if (result) existing.resultSummary = result
    } else {
      activeAgents.value.push({
        name,
        displayName: agentDisplayName(name),
        status,
        currentTask: task,
        resultSummary: result,
        startedAt: status === 'working' ? Date.now() : undefined,
      })
    }
  }

  function handleServerEvent(event: Record<string, unknown>): { newSessionId?: string } | void {
    const ctype = event.type as string

    if (ctype === 'token') {
      appendToken(event.text as string)
      return
    }

    if (ctype === 'agent_activity') {
      _updateAgentStatus(event)
      workflowTrace.value.push({
        agent: (event.agent as string) || 'unknown',
        action: (event.task as string) || (event.status as string) || '',
        timestamp: Date.now(),
      })
      return
    }

    if (ctype === 'generating') {
      const mid = event.message_id as string
      if (mid && !generatingMessageIds.value.has(mid)) {
        generatingMessageIds.value.add(mid)
        messages.value.push({ id: mid, role: 'assistant', content: '', generating: true })
      }
      responding.value = true
      return
    }

    if (ctype === 'message') {
      const citations = mapCitations((event.citations as unknown[]) || [])
      const incomingId = event.message_id as string | undefined
      const msg: ChatMessage = {
        id: incomingId || crypto.randomUUID(),
        role: event.role as 'user' | 'assistant',
        content: event.content as string,
        citations,
        generating: false,
        streaming: false,
        evidence_mode: event.evidence_mode as ChatMessage['evidence_mode'],
        timestamp: new Date().toISOString(),
      }

      if (streamingMessageId.value) {
        const idx = messages.value.findIndex((m) => m.id === streamingMessageId.value)
        if (idx !== -1) {
          messages.value[idx] = { ...msg, id: messages.value[idx].id }
        } else {
          messages.value.push(msg)
        }
        streamingMessageId.value = null
      } else if (incomingId && generatingMessageIds.value.has(incomingId)) {
        const idx = messages.value.findIndex((m) => m.id === incomingId)
        if (idx !== -1) {
          messages.value[idx] = msg
        } else {
          messages.value.push(msg)
        }
        generatingMessageIds.value.delete(incomingId)
      } else {
        messages.value.push(msg)
      }

      responding.value = false
      activeAgents.value = activeAgents.value.map((a) => ({ ...a, status: 'idle' as const }))
      suggestedQuestions.value = (event.suggested_questions as string[]) || []

      const newSid = event.session_id as string | undefined
      return newSid ? { newSessionId: newSid } : undefined
    }

    if (ctype === 'error') {
      if (streamingMessageId.value) {
        const idx = messages.value.findIndex((m) => m.id === streamingMessageId.value)
        if (idx !== -1) messages.value.splice(idx, 1)
        streamingMessageId.value = null
      }
      generatingMessageIds.value.forEach((mid) => {
        const idx = messages.value.findIndex((m) => m.id === mid)
        if (idx !== -1) messages.value.splice(idx, 1)
      })
      generatingMessageIds.value.clear()
      messages.value.push({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `Error: ${event.detail || 'Unknown error'}`,
      })
      responding.value = false
    }
  }

  function addUserMessage(text: string): string {
    const id = crypto.randomUUID()
    messages.value.push({
      id,
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    })
    return id
  }

  function setMessageFeedback(messageId: string, rating: 1 | -1) {
    const idx = messages.value.findIndex((m) => m.id === messageId)
    if (idx !== -1) {
      messages.value[idx] = { ...messages.value[idx], feedback: rating }
    }
  }

  function resetConversation() {
    messages.value = []
    activeAgents.value = []
    workflowTrace.value = []
    streamingMessageId.value = null
    generatingMessageIds.value.clear()
    suggestedQuestions.value = []
    responding.value = false
    systemPrompt.value = ''
    llmConfig.value = null
    pendingLLMConfig.value = null
  }

  async function fetchSessions() {
    try {
      const { data } = await api.get('/chat/sessions')
      sessions.value = data
    } catch {
      // interceptor toasts
    }
  }

  async function loadSession(sessionId: string) {
    try {
      const { data } = await api.get(`/chat/sessions/${sessionId}`)
      llmConfig.value = (data.llm_config as LLMSessionConfig) || defaultLLMConfig()
      systemPrompt.value = data.system_prompt || ''
      pendingLLMConfig.value = null
      messages.value = (data.messages || []).map((m: Record<string, unknown>) => ({
        id: (m.id as string) || crypto.randomUUID(),
        role: m.role as 'user' | 'assistant',
        content: m.content as string,
        citations: mapCitations((m.citations as unknown[]) || []),
        timestamp: m.timestamp as string | undefined,
        evidence_mode: m.evidence_mode as ChatMessage['evidence_mode'],
      }))
    } catch {
      messages.value = []
    }
  }

  async function renameSession(sessionId: string, title: string) {
    try {
      await api.put(`/chat/sessions/${sessionId}/rename`, { title })
      const idx = sessions.value.findIndex((s) => s.id === sessionId)
      if (idx !== -1) sessions.value[idx] = { ...sessions.value[idx], title }
    } catch {
      // no-op
    }
  }

  async function deleteSession(sessionId: string) {
    try {
      await api.delete(`/chat/sessions/${sessionId}`)
      sessions.value = sessions.value.filter((s) => s.id !== sessionId)
    } catch {
      // no-op
    }
  }

  async function submitFeedback(messageId: string, rating: 1 | -1) {
    try {
      await api.post(`/chat/messages/${messageId}/feedback`, { rating })
      setMessageFeedback(messageId, rating)
    } catch {
      // no-op
    }
  }

  async function persistSystemPrompt(sessionId: string) {
    if (!sessionId || sessionId === 'new') return
    try {
      await api.put(`/chat/sessions/${sessionId}/system-prompt`, {
        system_prompt: systemPrompt.value,
      })
    } catch {
      // no-op
    }
  }

  return {
    messages,
    sessions,
    currentSessionId,
    responding,
    activeAgents,
    workflowTrace,
    suggestedQuestions,
    streamingMessageId,
    llmConfig,
    pendingLLMConfig,
    systemPrompt,
    userKeys,
    sessionSearchQuery,
    currentSessionTitle,
    filteredSessions,
    lastUserMessage,
    defaultLLMConfig,
    appendToken,
    handleServerEvent,
    addUserMessage,
    setMessageFeedback,
    resetConversation,
    fetchSessions,
    loadSession,
    renameSession,
    deleteSession,
    submitFeedback,
    persistSystemPrompt,
  }
})
