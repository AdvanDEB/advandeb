<template>
  <div class="chat-interface">
    <div class="chat-layout">
      <!-- Session sidebar -->
      <aside class="session-sidebar">
        <div class="sidebar-header">
          <span class="sidebar-title">Conversations</span>
          <button class="new-session-btn" title="New conversation" @click="startNewSession">+</button>
        </div>

        <!-- Item 10: Session search -->
        <div class="sidebar-search">
          <input
            v-model="store.sessionSearchQuery"
            placeholder="Search…"
            class="search-input"
          />
        </div>

        <ul class="session-list">
          <li
            v-for="session in store.filteredSessions"
            :key="session.id"
            :class="['session-item', { active: session.id === store.currentSessionId }]"
            @click="handleLoadSession(session.id)"
            @mouseenter="hoveredSessionId = session.id"
            @mouseleave="hoveredSessionId = null"
          >
            <div class="session-item-body">
              <!-- Item 6: Inline session rename on double-click -->
              <input
                v-if="renamingId === session.id"
                ref="renameInput"
                v-model="renameTitle"
                class="rename-input"
                @blur="commitRename(session.id)"
                @keydown.enter.prevent="commitRename(session.id)"
                @keydown.esc.prevent="renamingId = null"
                @click.stop
              />
              <span v-else class="session-title" @dblclick.stop="startRename(session)">
                {{ session.title || 'Untitled' }}
              </span>
              <span class="session-date">{{ formatDate(session.updated_at) }}</span>
            </div>
            <button
              v-if="hoveredSessionId === session.id && renamingId !== session.id"
              class="delete-session-btn"
              title="Delete conversation"
              @click.stop="confirmDeleteSession(session.id, session.title)"
            >✕</button>
          </li>
        </ul>
      </aside>

      <!-- Main chat area -->
      <div class="chat-main">
        <!-- Chat toolbar -->
        <div class="chat-toolbar">
          <span class="session-title-display">{{ store.currentSessionTitle }}</span>
          <div class="toolbar-actions">
            <button
              class="toolbar-btn"
              :class="{ active: showLLMConfig }"
              title="Choose which model answers"
              @click="showLLMConfig = !showLLMConfig"
            >
              {{ llmConfigLabel }}
            </button>
            <!-- Item 12: System prompt toggle -->
            <button
              class="toolbar-btn"
              :class="{ active: showSystemPrompt }"
              title="Custom instructions for this session"
              @click="showSystemPrompt = !showSystemPrompt"
            >
              Instructions
            </button>
            <button class="toolbar-btn" title="Export conversation" @click="exportConversation">Export</button>
          </div>
        </div>

        <LLMConfigPanel
          v-if="showLLMConfig"
          :model-value="store.llmConfig"
          @update:model-value="onLLMConfigUpdate"
        />

        <!-- Item 12: System prompt panel -->
        <div v-if="showSystemPrompt" class="system-prompt-panel">
          <label class="sp-label">Custom instructions (applied to every reply in this session)</label>
          <textarea
            v-model="store.systemPrompt"
            class="sp-textarea"
            rows="3"
            placeholder="E.g. Always answer in bullet points. Focus on marine organisms."
            @blur="saveSystemPrompt"
          ></textarea>
        </div>

        <!-- Item 9: Prompt library (positioned relative to input area) -->
        <div class="messages-and-input">
          <MessageList
            :messages="store.messages"
            @show-provenance="openProvenance"
            @retry="handleRetry"
            @feedback="handleFeedback"
          />

          <!-- Suggested follow-up questions -->
          <div v-if="store.suggestedQuestions.length > 0 && !store.responding" class="suggestions">
            <button
              v-for="q in store.suggestedQuestions"
              :key="q"
              class="suggestion-chip"
              @click="handleSendMessage(q)"
            >
              {{ q }}
            </button>
          </div>

          <!-- Input wrapper holds prompt library popup -->
          <div class="input-wrapper">
            <PromptLibrary
              v-if="showPromptLibrary"
              @select="onPromptSelect"
              @close="showPromptLibrary = false"
            />
            <div class="input-row">
              <button
                class="prompt-lib-btn"
                :class="{ active: showPromptLibrary }"
                title="Starter prompts"
                @click="showPromptLibrary = !showPromptLibrary"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              </button>
              <MessageInput :disabled="store.responding" @send="handleSendMessage" />
            </div>
          </div>
        </div>
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
          :agents="store.activeAgents"
          :workflow-trace="store.workflowTrace"
        />
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import MessageList from './MessageList.vue'
import MessageInput from './MessageInput.vue'
import AgentActivity from './AgentActivity.vue'
import LLMConfigPanel from './LLMConfigPanel.vue'
import PromptLibrary from './PromptLibrary.vue'
import ProvenanceTrail from '@/components/provenance/ProvenanceTrail.vue'
import type { CitationRef as Citation } from '@/types/chat'
import type { LLMSessionConfig } from '@/types/llm'
import api from '@/utils/api'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'

const authStore = useAuthStore()
const store = useChatStore()

// UI state
const showLLMConfig = ref(false)
const showSystemPrompt = ref(false)
const showPromptLibrary = ref(false)
const rightPanel = ref<'activity' | 'provenance'>('activity')
const activeProvenanceId = ref<string | null>(null)

// Inline rename state
const renamingId = ref<string | null>(null)
const renameTitle = ref('')
const renameInput = ref<HTMLInputElement | null>(null)

// Sidebar hover (for delete button visibility)
const hoveredSessionId = ref<string | null>(null)

// Item 13: pending message if session creation race
const pendingMessage = ref<string | null>(null)

let ws: WebSocket | null = null

const PROVIDER_SHORT: Record<string, string> = {
  default: 'Nemotron', nvidia: 'NVIDIA',
  ollama: 'Local', anthropic: 'Claude', openai: 'ChatGPT',
  gemini: 'Gemini', github_models: 'GitHub',
}

const llmConfigLabel = computed(() =>
  PROVIDER_SHORT[store.llmConfig?.provider || 'default'] || 'Nemotron',
)

onMounted(async () => {
  store.resetConversation()
  store.llmConfig = store.defaultLLMConfig()
  store.pendingLLMConfig = store.defaultLLMConfig()
  await store.fetchSessions()
  connectWebSocket()
})

onUnmounted(() => {
  ws?.close()
})

function connectWebSocket() {
  const sessionId = store.currentSessionId
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = authStore.accessToken
  const tokenParam = token ? `?token=${encodeURIComponent(token)}` : ''
  const wsUrl = `${proto}//${window.location.host}/ws/chat/${sessionId}${tokenParam}`
  ws = new WebSocket(wsUrl)

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data) as Record<string, unknown>
    const result = store.handleServerEvent(data)
    if (result?.newSessionId && result.newSessionId !== store.currentSessionId) {
      const newId = result.newSessionId
      store.currentSessionId = newId

      // Persist LLM config and system prompt made before session existed
      if (store.pendingLLMConfig) {
        api.put(`/chat/sessions/${newId}/llm`, store.pendingLLMConfig).catch(() => {})
        store.pendingLLMConfig = null
      }
      if (store.systemPrompt) {
        api.put(`/chat/sessions/${newId}/system-prompt`, {
          system_prompt: store.systemPrompt,
        }).catch(() => {})
      }
      store.fetchSessions()

      // Item 13: flush a message that was queued WHILE session creation was in
      // flight. The sentinel '' means "in-flight, nothing queued" — don't
      // re-send in that case (that would duplicate the first message).
      const queued = pendingMessage.value
      pendingMessage.value = null
      if (queued) {
        nextTick(() => sendOverWs(queued))
      }
    }
  }

  ws.onclose = (ev) => {
    if (ev.code === 4401) {
      store.messages.push({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: 'Session expired. Please log in again.',
      })
      return
    }
    setTimeout(() => {
      if (store.currentSessionId) connectWebSocket()
    }, 2000)
  }
}

function sendOverWs(text: string) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(
      JSON.stringify({
        type: 'user_message',
        text,
        llm_config: store.llmConfig || undefined,
      }),
    )
  }
}

async function handleSendMessage(text: string) {
  if (!text.trim() || store.responding) return

  // Item 13: If session creation is already in flight (pendingMessage !== null),
  // queue this message so it goes out on the correct session after the session
  // is created. '' means "in-flight, nothing queued yet" (falsy → not re-sent).
  if (store.currentSessionId === 'new' && pendingMessage.value !== null) {
    pendingMessage.value = text
    return
  }

  store.addUserMessage(text)
  store.responding = true
  store.workflowTrace = []
  store.suggestedQuestions = []
  showPromptLibrary.value = false

  // Mark "session creation in flight" with an empty-string sentinel so that
  // a concurrent second message gets queued, but the first message itself is
  // NOT re-sent when the session_id arrives.
  if (store.currentSessionId === 'new') {
    pendingMessage.value = ''
  }

  sendOverWs(text)
}

async function handleRetry(messageId: string) {
  // Find the last user message before this assistant message
  const idx = store.messages.findIndex((m) => m.id === messageId)
  if (idx <= 0) return
  const precedingUser = [...store.messages].slice(0, idx).reverse().find((m) => m.role === 'user')
  if (!precedingUser) return
  // Remove the assistant message being retried
  store.messages.splice(idx, 1)
  // Re-send
  handleSendMessage(precedingUser.content)
}

async function handleFeedback(messageId: string, rating: 1 | -1) {
  await store.submitFeedback(messageId, rating)
}

function onPromptSelect(text: string) {
  showPromptLibrary.value = false
  handleSendMessage(text)
}

async function onLLMConfigUpdate(cfg: LLMSessionConfig) {
  store.llmConfig = cfg
  if (store.currentSessionId && store.currentSessionId !== 'new') {
    try {
      await api.put(`/chat/sessions/${store.currentSessionId}/llm`, cfg)
    } catch {
      // interceptor surfaces error
    }
  } else {
    store.pendingLLMConfig = cfg
  }
}

async function saveSystemPrompt() {
  await store.persistSystemPrompt(store.currentSessionId)
}

function startNewSession() {
  ws?.close()
  store.currentSessionId = 'new'
  store.resetConversation()
  store.llmConfig = store.defaultLLMConfig()
  store.pendingLLMConfig = store.defaultLLMConfig()
  pendingMessage.value = null
  connectWebSocket()
}

async function handleLoadSession(sessionId: string) {
  ws?.close()
  store.currentSessionId = sessionId
  pendingMessage.value = null
  await store.loadSession(sessionId)
  connectWebSocket()
}

async function confirmDeleteSession(sessionId: string, title: string) {
  const label = title?.trim() || 'this conversation'
  if (!window.confirm(`Delete "${label}"? This cannot be undone.`)) return
  const wasActive = store.currentSessionId === sessionId
  await store.deleteSession(sessionId)
  if (wasActive) {
    startNewSession()
  }
}

// Item 6: Inline rename
async function startRename(session: { id: string; title: string }) {
  renamingId.value = session.id
  renameTitle.value = session.title || ''
  await nextTick()
  renameInput.value?.focus()
  renameInput.value?.select()
}

async function commitRename(sessionId: string) {
  const title = renameTitle.value.trim()
  if (title) {
    await store.renameSession(sessionId, title)
  }
  renamingId.value = null
}

function exportConversation() {
  if (store.messages.length === 0) return
  const payload = store.messages.map((m) => ({
    role: m.role,
    content: m.content,
    citations: m.citations || [],
    timestamp: m.timestamp,
  }))
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `conversation-${store.currentSessionId}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function openProvenance(citation: Citation) {
  activeProvenanceId.value = citation.citation_id
  rightPanel.value = 'provenance'
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

/* Sidebar */
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
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e5e7eb;
  font-weight: 600;
  font-size: 0.875rem;
  flex-shrink: 0;
}

.sidebar-title { flex: 1; }

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
  flex-shrink: 0;
}

.sidebar-search {
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.search-input {
  width: 100%;
  padding: 0.3rem 0.5rem;
  font-size: 0.8rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  box-sizing: border-box;
}
.search-input:focus { outline: none; border-color: #3b82f6; }

.session-list {
  list-style: none;
  overflow-y: auto;
  flex: 1;
  padding: 0.4rem 0;
  margin: 0;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.45rem 0.5rem 0.45rem 0.75rem;
  cursor: pointer;
  border-radius: 5px;
  margin: 0 0.25rem;
}
.session-item:hover { background: #e5e7eb; }
.session-item.active { background: #dbeafe; }

.session-item-body {
  flex: 1;
  min-width: 0;
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

.delete-session-btn {
  flex-shrink: 0;
  background: none;
  border: none;
  color: #9ca3af;
  font-size: 0.75rem;
  padding: 0.1rem 0.25rem;
  border-radius: 3px;
  cursor: pointer;
  line-height: 1;
  opacity: 0.7;
}
.delete-session-btn:hover {
  background: #fee2e2;
  color: #dc2626;
  opacity: 1;
}

.rename-input {
  width: 100%;
  font-size: 0.8rem;
  padding: 0.1rem 0.25rem;
  border: 1px solid #3b82f6;
  border-radius: 3px;
  background: white;
}

/* Main area */
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
  flex-shrink: 0;
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

/* System prompt */
.system-prompt-panel {
  padding: 0.5rem 1rem;
  border-bottom: 1px solid #f3f4f6;
  background: #fffbeb;
  flex-shrink: 0;
}

.sp-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #92400e;
  display: block;
  margin-bottom: 0.3rem;
}

.sp-textarea {
  width: 100%;
  font-size: 0.83rem;
  padding: 0.4rem 0.5rem;
  border: 1px solid #fcd34d;
  border-radius: 6px;
  resize: vertical;
  font-family: inherit;
  background: white;
  box-sizing: border-box;
}
.sp-textarea:focus { outline: none; border-color: #f59e0b; }

/* Messages + input as a column that fills remaining space */
.messages-and-input {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.suggestions {
  padding: 0.5rem 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  border-top: 1px solid #f3f4f6;
  flex-shrink: 0;
}

.suggestion-chip {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
  border-radius: 9999px;
  padding: 0.25rem 0.75rem;
  font-size: 0.78rem;
  cursor: pointer;
}
.suggestion-chip:hover { background: #dbeafe; }

/* Input wrapper + prompt library */
.input-wrapper {
  position: relative;
  flex-shrink: 0;
}

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 0.4rem;
  padding: 0 0.5rem 0.5rem;
}

.prompt-lib-btn {
  background: none;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0.35rem 0.4rem;
  cursor: pointer;
  color: #6b7280;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  height: 38px;
}
.prompt-lib-btn:hover { background: #f3f4f6; color: #374151; }
.prompt-lib-btn.active { background: #eff6ff; border-color: #bfdbfe; color: #2563eb; }

/* Right panel */
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
  flex-shrink: 0;
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
.tab.active { color: #3b82f6; border-bottom-color: #3b82f6; font-weight: 600; }
</style>
