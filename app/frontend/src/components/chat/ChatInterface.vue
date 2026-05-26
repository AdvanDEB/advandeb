<template>
  <div class="chat-interface">
    <div class="chat-layout">
      <!-- Session sidebar -->
      <aside class="session-sidebar">
        <div class="sidebar-header">
          <span class="sidebar-title">Conversations</span>
          <button class="new-session-btn" @click="startNewSession">+</button>
        </div>
        <ul class="session-list">
          <li
            v-for="session in sessions"
            :key="session.id"
            :class="['session-item', { active: session.id === currentSessionId }]"
            @click="loadSession(session.id)"
          >
            <span class="session-title">{{ session.title || 'Untitled' }}</span>
            <span class="session-date">{{ formatDate(session.updated_at) }}</span>
          </li>
        </ul>
      </aside>

      <!-- Main chat area -->
      <div class="chat-main">
        <!-- Chat toolbar -->
        <div class="chat-toolbar">
          <span class="session-title-display">{{ currentSessionTitle }}</span>
          <div class="toolbar-actions">
            <button
              class="toolbar-btn"
              :class="{ active: showLLMConfig }"
              title="Choose which model answers"
              @click="showLLMConfig = !showLLMConfig"
            >
              🔑 {{ llmConfigLabel }}
            </button>
            <button class="toolbar-btn" title="Export conversation" @click="exportConversation">⬇ Export</button>
          </div>
        </div>

        <LLMConfigPanel
          v-if="showLLMConfig"
          :model-value="llmConfig"
          @update:model-value="onLLMConfigUpdate"
        />

        <MessageList :messages="messages" @show-provenance="openProvenance" />

        <!-- Suggested follow-up questions -->
        <div v-if="suggestedQuestions.length > 0 && !responding" class="suggestions">
          <button
            v-for="q in suggestedQuestions"
            :key="q"
            class="suggestion-chip"
            @click="handleSendMessage(q)"
          >
            {{ q }}
          </button>
        </div>

        <MessageInput :disabled="responding" @send="handleSendMessage" />
      </div>

      <!-- Right panel: Agent activity or Provenance -->
      <aside class="activity-panel">
        <div v-if="activeProvenanceId" class="panel-tab-bar">
          <button :class="['tab', { active: rightPanel === 'provenance' }]" @click="rightPanel = 'provenance'">Provenance</button>
          <button :class="['tab', { active: rightPanel === 'activity' }]" @click="rightPanel = 'activity'">Agents</button>
        </div>
        <ProvenanceTrail
          v-if="rightPanel === 'provenance'"
          :citation-id="activeProvenanceId"
          @close="rightPanel = 'activity'; activeProvenanceId = null"
        />
        <AgentActivity
          v-else
          :agents="activeAgents"
          :workflow-trace="workflowTrace"
        />
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import MessageList from './MessageList.vue'
import MessageInput from './MessageInput.vue'
import AgentActivity from './AgentActivity.vue'
import LLMConfigPanel from './LLMConfigPanel.vue'
import ProvenanceTrail from '@/components/provenance/ProvenanceTrail.vue'
import type { ChatMessage as Message, CitationRef as Citation } from '@/types/chat'
import type { LLMSessionConfig } from '@/types/llm'
import api from '@/utils/api'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

interface AgentStatus {
  name: string
  displayName: string
  status: 'idle' | 'working' | 'completed' | 'error'
  currentTask?: string
  resultSummary?: string
  startedAt?: number
}

interface WorkflowStep {
  agent: string
  action: string
  timestamp: number
}

interface Session {
  id: string
  title: string
  updated_at?: string
}

const messages = ref<Message[]>([])
const activeAgents = ref<AgentStatus[]>([])
const workflowTrace = ref<WorkflowStep[]>([])
const sessions = ref<Session[]>([])
const currentSessionId = ref<string>('new')
const responding = ref(false)
const rightPanel = ref<'activity' | 'provenance'>('activity')
const activeProvenanceId = ref<string | null>(null)
const suggestedQuestions = ref<string[]>([])
// Map from server message_id → local message array index for reconnect catch-up
const generatingMessageIds = ref<Set<string>>(new Set())
let ws: WebSocket | null = null

// Per-session LLM (BYOK) config. `pendingLLMConfig` holds a choice made before
// a brand-new session exists; it is persisted once the session_id arrives.
const showLLMConfig = ref(false)
const llmConfig = ref<LLMSessionConfig | null>(null)
const pendingLLMConfig = ref<LLMSessionConfig | null>(null)

const PROVIDER_SHORT: Record<string, string> = {
  ollama: 'Local', anthropic: 'Claude', openai: 'ChatGPT',
  gemini: 'Gemini', github_models: 'GitHub',
}

const currentSessionTitle = computed(() => {
  const s = sessions.value.find((s) => s.id === currentSessionId.value)
  return s?.title || 'New conversation'
})

const llmConfigLabel = computed(() =>
  PROVIDER_SHORT[llmConfig.value?.provider || 'ollama'] || 'Local',
)

async function onLLMConfigUpdate(cfg: LLMSessionConfig) {
  llmConfig.value = cfg
  if (currentSessionId.value && currentSessionId.value !== 'new') {
    try {
      await api.put(`/chat/sessions/${currentSessionId.value}/llm`, cfg)
    } catch {
      // interceptor surfaces the error
    }
  } else {
    // No session yet — apply once one is created.
    pendingLLMConfig.value = cfg
  }
}

const AGENT_DISPLAY_NAMES: Record<string, string> = {
  // Legacy names
  planner: 'Query Planner',
  retrieval: 'Retrieval Agent',
  synthesis: 'Synthesis Agent',
  validator: 'Validator',
  // Actual names emitted by chatbot_agent ReAct loop
  chatbot: 'Chatbot',
  retrieval_agent: 'Retrieval Agent',
  graph_explorer: 'Graph Explorer',
  synthesis_agent: 'Synthesis Agent',
  knowledge_agent: 'Knowledge Agent',
}

onMounted(async () => {
  await fetchSessions()
  connectWebSocket()
})

onUnmounted(() => {
  ws?.close()
})

function connectWebSocket() {
  const sessionId = currentSessionId.value
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = authStore.accessToken
  const tokenParam = token ? `?token=${encodeURIComponent(token)}` : ''
  const wsUrl = `${proto}//${window.location.host}/ws/chat/${sessionId}${tokenParam}`
  ws = new WebSocket(wsUrl)

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    handleServerEvent(data)
  }

  ws.onclose = (ev) => {
    // 4401 = invalid/expired token — don't reconnect, surface the error
    if (ev.code === 4401) {
      messages.value.push({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: 'Session expired. Please log in again.',
      })
      return
    }
    // Attempt reconnect after 2s if session is active
    setTimeout(() => {
      if (currentSessionId.value) connectWebSocket()
    }, 2000)
  }
}

function handleServerEvent(event: Record<string, unknown>) {
  if (event.type === 'agent_activity') {
    updateAgentStatus(event)
    workflowTrace.value.push({
      agent: (event.agent as string) || 'unknown',
      action: (event.task as string) || (event.status as string) || '',
      timestamp: Date.now(),
    })
  } else if (event.type === 'generating') {
    // Reconnect catch-up: the server found an in-progress generation.
    // Insert a spinner placeholder message so the user sees something while
    // the ReAct loop finishes in the background.
    const mid = event.message_id as string
    if (mid && !generatingMessageIds.value.has(mid)) {
      generatingMessageIds.value.add(mid)
      messages.value.push({
        id: mid,
        role: 'assistant',
        content: '',
        generating: true,
      })
      responding.value = true
    }
  } else if (event.type === 'message') {
    const citations = mapCitations((event.citations as Record<string, unknown>[]) || [])

    const incomingId = event.message_id as string | undefined
    const msg: Message = {
      id: incomingId || crypto.randomUUID(),
      role: event.role as 'user' | 'assistant',
      content: event.content as string,
      citations,
      generating: false,
      evidence_mode: event.evidence_mode as Message['evidence_mode'],
    }

    // Replace a spinner placeholder if one exists for this message_id
    if (incomingId && generatingMessageIds.value.has(incomingId)) {
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

    if (event.session_id && event.session_id !== currentSessionId.value) {
      const newId = event.session_id as string
      currentSessionId.value = newId
      // Persist any LLM choice made before this session existed.
      if (pendingLLMConfig.value) {
        api.put(`/chat/sessions/${newId}/llm`, pendingLLMConfig.value).catch(() => {})
        pendingLLMConfig.value = null
      }
      fetchSessions()
    }

    // Reset agents to idle after response
    activeAgents.value = activeAgents.value.map((a) => ({ ...a, status: 'idle' as const }))

    // Extract suggested follow-up questions from event if provided
    if (Array.isArray(event.suggested_questions)) {
      suggestedQuestions.value = event.suggested_questions as string[]
    }
  } else if (event.type === 'error') {
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: `Error: ${event.detail}`,
    })
    responding.value = false
  }
}

function updateAgentStatus(event: Record<string, unknown>) {
  const agentName = event.agent as string
  const existing = activeAgents.value.find((a) => a.name === agentName)

  // Map 'thinking' → 'working' so the spinner and elapsed timer show
  const rawStatus = (event.status as string) || 'working'
  const mappedStatus = rawStatus === 'thinking' ? 'working' : rawStatus

  const updated: AgentStatus = {
    name: agentName,
    displayName: AGENT_DISPLAY_NAMES[agentName] || agentName,
    status: mappedStatus as AgentStatus['status'],
    currentTask: event.task as string | undefined,
    resultSummary: event.result as string | undefined,
    startedAt: existing?.startedAt ?? Date.now(),
  }

  if (existing) {
    const idx = activeAgents.value.indexOf(existing)
    activeAgents.value[idx] = updated
  } else {
    activeAgents.value.push(updated)
  }
}

async function handleSendMessage(text: string) {
  if (!text.trim() || responding.value) return

  const userMsg: Message = {
    id: crypto.randomUUID(),
    role: 'user',
    content: text,
    timestamp: new Date().toISOString(),
  }
  messages.value.push(userMsg)
  responding.value = true
  workflowTrace.value = []
  suggestedQuestions.value = []

  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(
      JSON.stringify({
        type: 'user_message',
        text,
      })
    )
  }
}

function startNewSession() {
  ws?.close()
  currentSessionId.value = 'new'
  messages.value = []
  activeAgents.value = []
  workflowTrace.value = []
  connectWebSocket()
}

async function loadSession(sessionId: string) {
  ws?.close()
  currentSessionId.value = sessionId

  try {
    const { data } = await api.get(`/chat/sessions/${sessionId}`)
    llmConfig.value = (data.llm_config as LLMSessionConfig) || null
    pendingLLMConfig.value = null
    messages.value = (data.messages || []).map((m: Record<string, unknown>) => {
      return {
        id: (m.id as string) || crypto.randomUUID(),
        role: m.role as 'user' | 'assistant',
        content: m.content as string,
        citations: mapCitations((m.citations as Record<string, unknown>[]) || []),
        timestamp: m.timestamp as string | undefined,
        evidence_mode: m.evidence_mode as Message['evidence_mode'],
      }
    })
  } catch {
    messages.value = []
  }

  connectWebSocket()
}

async function fetchSessions() {
  try {
    const { data } = await api.get('/chat/sessions')
    sessions.value = data
  } catch {
    sessions.value = []
  }
}

function exportConversation() {
  if (messages.value.length === 0) return
  const payload = messages.value.map((m) => ({
    role: m.role,
    content: m.content,
    citations: m.citations || [],
    timestamp: m.timestamp,
  }))
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `conversation-${currentSessionId.value}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function openProvenance(citation: Citation) {
  activeProvenanceId.value = citation.citation_id
  rightPanel.value = 'provenance'
}

function mapCitations(rawCitations: Record<string, unknown>[]): Citation[] {
  return rawCitations.map((citation) => mapCitation(citation))
}

function mapCitation(citation: Record<string, unknown>): Citation {
  const legacyNumber = citation.number as number | undefined
  const legacyMarker = typeof legacyNumber === 'number' ? String(legacyNumber) : ''
  const citationId =
    (citation.citation_id as string | undefined) ||
    (citation.chunk_id as string | undefined) ||
    (citation.document_id as string | undefined) ||
    legacyMarker ||
    crypto.randomUUID()

  return {
    citation_id: citationId,
    marker: (citation.marker as string | undefined) || legacyMarker || '?',
    source_type: (citation.source_type as Citation['source_type'] | undefined) || 'chunk',
    document_id: citation.document_id as string | undefined,
    chunk_id: citation.chunk_id as string | undefined,
    fact_id: citation.fact_id as string | undefined,
    stylized_fact_id: citation.stylized_fact_id as string | undefined,
    evidence_text:
      (citation.evidence_text as string | undefined) ||
      (citation.text_snippet as string | undefined) ||
      '',
    title: citation.title as string | undefined,
    authors: citation.authors as string[] | undefined,
    year: citation.year as string | number | undefined,
    journal: citation.journal as string | undefined,
    doi: citation.doi as string | undefined,
    url: citation.url as string | undefined,
  }
}

function formatDate(iso?: string): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString()
}
</script>

<style scoped>
.chat-interface {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.chat-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.session-sidebar {
  width: 220px;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  background: #f9fafb;
  overflow: hidden;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem;
  border-bottom: 1px solid #e5e7eb;
  font-weight: 600;
  font-size: 0.875rem;
}

.new-session-btn {
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 4px;
  width: 24px;
  height: 24px;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
}

.session-list {
  list-style: none;
  overflow-y: auto;
  flex: 1;
  padding: 0.5rem 0;
}

.session-item {
  padding: 0.5rem 1rem;
  cursor: pointer;
  border-radius: 4px;
  margin: 0 0.25rem;
}

.session-item:hover {
  background: #e5e7eb;
}

.session-item.active {
  background: #dbeafe;
}

.session-title {
  display: block;
  font-size: 0.8rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-date {
  font-size: 0.7rem;
  color: #9ca3af;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 1rem;
  border-bottom: 1px solid #f3f4f6;
  background: #fafafa;
}

.session-title-display {
  font-size: 0.8rem;
  color: #6b7280;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 60%;
}

.toolbar-btn {
  background: none;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
  cursor: pointer;
  color: #374151;
}

.toolbar-btn:hover { background: #f3f4f6; }
.toolbar-btn.active { background: #eff6ff; border-color: #bfdbfe; color: #2563eb; }

.toolbar-actions { display: flex; gap: 0.4rem; align-items: center; }

.suggestions {
  padding: 0.5rem 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  border-top: 1px solid #f3f4f6;
}

.suggestion-chip {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
  border-radius: 9999px;
  padding: 0.25rem 0.75rem;
  font-size: 0.78rem;
  cursor: pointer;
  transition: background 0.15s;
}

.suggestion-chip:hover { background: #dbeafe; }

.activity-panel {
  width: 300px;
  border-left: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-tab-bar {
  display: flex;
  border-bottom: 1px solid #e5e7eb;
}

.tab {
  flex: 1;
  padding: 0.4rem;
  font-size: 0.78rem;
  border: none;
  background: none;
  cursor: pointer;
  color: #6b7280;
  border-bottom: 2px solid transparent;
}

.tab.active {
  color: #3b82f6;
  border-bottom-color: #3b82f6;
  font-weight: 600;
}
</style>
