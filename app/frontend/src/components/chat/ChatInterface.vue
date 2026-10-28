<template>
  <div class="chat-interface" @keydown.esc="closeDrawers">
    <div class="chat-layout">
      <!-- Below the tablet breakpoint the two side panels become drawers over
           the conversation; the scrim closes whichever is open. -->
      <div
        v-if="showSessions || showActivity"
        class="drawer-scrim"
        aria-hidden="true"
        @click="closeDrawers"
      ></div>

      <!-- Session sidebar -->
      <aside
        id="chat-sessions"
        ref="sessionsEl"
        :class="['session-sidebar', { open: showSessions }]"
        aria-label="Conversations"
      >
        <div class="sidebar-header">
          <h2 class="sidebar-title">Conversations</h2>
          <button
            type="button"
            class="new-session-btn"
            title="New conversation"
            aria-label="New conversation"
            @click="startNewSession"
          >+</button>
        </div>

        <!-- Item 10: Session search -->
        <div class="sidebar-search">
          <input
            v-model="store.sessionSearchQuery"
            type="search"
            placeholder="Search…"
            aria-label="Search conversations"
            class="search-input"
          />
        </div>

        <ul class="session-list">
          <li
            v-for="session in store.filteredSessions"
            :key="session.id"
            :class="['session-item', { active: session.id === store.currentSessionId }]"
          >
            <!-- Item 6: Inline session rename (double-click, or the ✎ button) -->
            <input
              v-if="renamingId === session.id"
              :ref="setRenameInput"
              v-model="renameTitle"
              class="rename-input"
              aria-label="Conversation title"
              @blur="commitRename(session.id)"
              @keydown.enter.prevent="commitRename(session.id)"
              @keydown.esc.prevent.stop="renamingId = null"
            />
            <!-- A real button: the row used to be a clickable <li>, which a
                 keyboard could not reach and a screen reader did not announce
                 as actionable. -->
            <button
              v-else
              type="button"
              class="session-open"
              :aria-current="session.id === store.currentSessionId ? 'true' : undefined"
              @click="handleLoadSession(session.id)"
              @dblclick="startRename(session)"
            >
              <span class="session-title">{{ session.title || 'Untitled' }}</span>
              <span class="session-date">{{ formatDate(session.updated_at) }}</span>
            </button>
            <div v-if="renamingId !== session.id" class="session-actions">
              <button
                type="button"
                class="session-action"
                title="Rename"
                :aria-label="`Rename ${session.title || 'Untitled'}`"
                @click="startRename(session)"
              >✎</button>
              <button
                type="button"
                class="session-action danger"
                title="Delete conversation"
                :aria-label="`Delete ${session.title || 'Untitled'}`"
                @click="confirmDeleteSession(session.id, session.title)"
              >✕</button>
            </div>
          </li>
        </ul>
      </aside>

      <!-- Main chat area -->
      <div class="chat-main">
        <!-- Chat toolbar -->
        <div class="chat-toolbar">
          <button
            ref="sessionsToggle"
            type="button"
            class="toolbar-btn drawer-toggle sessions-toggle"
            :aria-expanded="showSessions"
            aria-controls="chat-sessions"
            @click="toggleSessions"
          >☰ <span>Chats</span></button>
          <span class="session-title-display">{{ store.currentSessionTitle }}</span>
          <div class="toolbar-actions">
            <button
              type="button"
              class="toolbar-btn"
              :class="{ active: showLLMConfig }"
              title="Choose which model answers"
              :aria-expanded="showLLMConfig"
              @click="showLLMConfig = !showLLMConfig"
            >
              {{ llmConfigLabel }}
            </button>
            <!-- Item 12: System prompt toggle -->
            <button
              type="button"
              class="toolbar-btn"
              :class="{ active: showSystemPrompt }"
              title="Custom instructions for this session"
              :aria-expanded="showSystemPrompt"
              @click="showSystemPrompt = !showSystemPrompt"
            >
              Instructions
            </button>
            <button type="button" class="toolbar-btn" title="Export conversation" @click="exportConversation">Export</button>
            <button
              ref="activityToggle"
              type="button"
              class="toolbar-btn drawer-toggle activity-toggle"
              :aria-expanded="showActivity"
              aria-controls="chat-activity"
              @click="toggleActivity"
            >{{ rightPanel === 'provenance' ? 'Sources' : 'Agents' }}</button>
          </div>
        </div>

        <LLMConfigPanel
          v-if="showLLMConfig"
          :model-value="store.llmConfig"
          @update:model-value="onLLMConfigUpdate"
        />

        <!-- Item 12: System prompt panel -->
        <div v-if="showSystemPrompt" class="system-prompt-panel">
          <label class="sp-label" for="chat-system-prompt">Custom instructions (applied to every reply in this session)</label>
          <textarea
            id="chat-system-prompt"
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
              type="button"
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
                type="button"
                class="prompt-lib-btn"
                :class="{ active: showPromptLibrary }"
                title="Starter prompts"
                aria-label="Starter prompts"
                :aria-expanded="showPromptLibrary"
                @click="showPromptLibrary = !showPromptLibrary"
              >
                <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              </button>
              <MessageInput :disabled="store.responding" @send="handleSendMessage" />
            </div>
          </div>
        </div>
      </div>

      <!-- Right panel: Agent activity or Provenance -->
      <aside
        id="chat-activity"
        ref="activityEl"
        :class="['activity-panel', { open: showActivity }]"
        aria-label="Agent activity and sources"
      >
        <div :class="['panel-tab-bar', { 'only-narrow': !activeProvenanceId }]">
          <template v-if="activeProvenanceId">
            <button
              type="button"
              :class="['tab', { active: rightPanel === 'provenance' }]"
              :aria-pressed="rightPanel === 'provenance'"
              @click="rightPanel = 'provenance'"
            >Provenance</button>
            <button
              type="button"
              :class="['tab', { active: rightPanel === 'activity' }]"
              :aria-pressed="rightPanel === 'activity'"
              @click="rightPanel = 'activity'"
            >Agents</button>
          </template>
          <button
            type="button"
            class="tab drawer-close only-narrow"
            aria-label="Close panel"
            @click="showActivity = false"
          >✕</button>
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
import { ref, computed, onMounted, onUnmounted, nextTick, watch, type ComponentPublicInstance } from 'vue'
import MessageList from './MessageList.vue'
import MessageInput from './MessageInput.vue'
import AgentActivity from './AgentActivity.vue'
import LLMConfigPanel from './LLMConfigPanel.vue'
import PromptLibrary from './PromptLibrary.vue'
import ProvenanceTrail from '@/components/provenance/ProvenanceTrail.vue'
import type { CitationRef as Citation } from '@/types/chat'
import type { LLMSessionConfig } from '@/types/llm'
import api from '@/utils/api'
import { fetchSocketTicket } from '@/utils/authRefresh'
import { useChatStore } from '@/stores/chat'
import { useChatSocket } from '@/composables/useChatSocket'
import { useDialogStore } from '@/stores/dialog'
import { formatDate } from '@/utils/format'

const store = useChatStore()
const dialog = useDialogStore()

// UI state
const showLLMConfig = ref(false)
const showSystemPrompt = ref(false)
const showPromptLibrary = ref(false)
const rightPanel = ref<'activity' | 'provenance'>('activity')
const activeProvenanceId = ref<string | null>(null)

// Drawers: only meaningful below the tablet breakpoint, where the session
// list and the agents/provenance panel no longer fit beside the conversation.
// On a wide screen both panels are always shown and these flags do nothing.
const showSessions = ref(false)
const showActivity = ref(false)

function toggleSessions() {
  showSessions.value = !showSessions.value
  if (showSessions.value) showActivity.value = false
}

function toggleActivity() {
  showActivity.value = !showActivity.value
  if (showActivity.value) showSessions.value = false
}

function closeDrawers() {
  showSessions.value = false
  showActivity.value = false
}

// A drawer that opens takes focus, and gives it back to its toggle when it
// closes — otherwise a keyboard user keeps tabbing through the page behind it.
const sessionsEl = ref<HTMLElement | null>(null)
const activityEl = ref<HTMLElement | null>(null)
const sessionsToggle = ref<HTMLButtonElement | null>(null)
const activityToggle = ref<HTMLButtonElement | null>(null)

function isDrawer(el: HTMLElement | null): boolean {
  return !!el && getComputedStyle(el).position === 'absolute'
}

function drawerFocus(panel: () => HTMLElement | null, toggle: () => HTMLButtonElement | null) {
  return async (open: boolean) => {
    await nextTick()
    const el = panel()
    if (!isDrawer(el)) return   // wide layout: the panel is not a drawer
    if (open) el?.querySelector<HTMLElement>('button, input, a[href]')?.focus()
    else if (el?.contains(document.activeElement)) toggle()?.focus()
  }
}

watch(showSessions, drawerFocus(() => sessionsEl.value, () => sessionsToggle.value))
watch(showActivity, drawerFocus(() => activityEl.value, () => activityToggle.value))

// Inline rename state. A function ref: a plain ref="" inside v-for collects an
// array, so focus() on it silently did nothing.
const renamingId = ref<string | null>(null)
const renameTitle = ref('')
let renameInput: HTMLInputElement | null = null

function setRenameInput(el: Element | ComponentPublicInstance | null) {
  renameInput = el instanceof HTMLInputElement ? el : null
}

// Item 13: pending message if session creation race
const pendingMessage = ref<string | null>(null)

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
  chatSocket.close()
})

/**
 * Socket lifecycle lives in useChatSocket, which owns the single-socket
 * invariant, reconnect timer, and the queue-while-connecting behaviour.
 */
const chatSocket = useChatSocket({
  sessionId: () => store.currentSessionId,
  ticket: fetchSocketTicket,
  onAuthFailure: () => {
    store.messages.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: 'Session expired. Please log in again.',
    })
  },
  onEvent: (data) => {
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
  },
})

function connectWebSocket() {
  chatSocket.connect()
}

function sendOverWs(text: string) {
  chatSocket.send({
    type: 'user_message',
    text,
    llm_config: store.llmConfig || undefined,
  })
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
  showSessions.value = false
  chatSocket.close()
  store.currentSessionId = 'new'
  store.resetConversation()
  store.llmConfig = store.defaultLLMConfig()
  store.pendingLLMConfig = store.defaultLLMConfig()
  pendingMessage.value = null
  connectWebSocket()
}

async function handleLoadSession(sessionId: string) {
  showSessions.value = false
  chatSocket.close()
  store.currentSessionId = sessionId
  pendingMessage.value = null
  await store.loadSession(sessionId)
  connectWebSocket()
}

async function confirmDeleteSession(sessionId: string, title: string) {
  const label = title?.trim() || 'this conversation'
  const ok = await dialog.confirm({
    title: 'Delete conversation?',
    message: `“${label}” will be deleted. This cannot be undone.`,
    confirmLabel: 'Delete',
    tone: 'danger',
  })
  if (!ok) return
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
  renameInput?.focus()
  renameInput?.select()
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
  // On a narrow screen the panel is a drawer; a tapped citation opens it.
  showActivity.value = true
  showSessions.value = false
}
</script>

<style scoped>
/* Fills the layout's main area. It was 100vh, which on a phone overflowed by
   the height of the fixed top bar and pushed the composer off-screen. */
.chat-interface {
  flex: 1;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.chat-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
}

/* Wide-screen defaults: drawer chrome is hidden. */
.drawer-scrim,
.drawer-toggle,
.only-narrow { display: none; }

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

.sidebar-title { flex: 1; font-size: inherit; font-weight: inherit; }

.new-session-btn {
  background: var(--app-primary-strong);
  color: white;
  border: none;
  border-radius: var(--app-radius-sm);
  width: 28px;
  height: 28px;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  flex-shrink: 0;
}
.new-session-btn:focus-visible { outline: var(--app-focus); outline-offset: 2px; }

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
.search-input:focus-visible { outline: var(--app-focus); outline-offset: -1px; border-color: var(--app-primary); }

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
  gap: 0.15rem;
  padding: 0.1rem 0.25rem 0.1rem 0;
  border-radius: 5px;
  margin: 0 0.25rem;
}
.session-item:hover { background: var(--app-line); }
.session-item.active { background: var(--app-primary-soft-2); }

.session-open {
  flex: 1;
  min-width: 0;
  display: block;
  text-align: left;
  background: none;
  border: 0;
  padding: 0.35rem 0.25rem 0.35rem 0.75rem;
  font: inherit;
  color: inherit;
  cursor: pointer;
  border-radius: 5px;
}
.session-open:focus-visible { outline: var(--app-focus); outline-offset: -2px; }

.session-actions { display: flex; flex-shrink: 0; }

/* Faded until the row is hovered or focused on a mouse device; always
   visible on touch, where there is no hover to reveal them. */
@media (hover: hover) and (pointer: fine) {
  .session-actions { opacity: 0; transition: opacity 0.12s ease; }
  .session-item:hover .session-actions,
  .session-item:focus-within .session-actions { opacity: 1; }
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

.session-action {
  background: none;
  border: none;
  color: var(--app-ink-3);
  font-size: 0.75rem;
  width: 26px;
  height: 26px;
  border-radius: var(--app-radius-sm);
  cursor: pointer;
  line-height: 1;
}
.session-action:hover { background: var(--app-bg-3); color: var(--app-ink-2); }
.session-action.danger:hover { background: var(--app-danger-soft); color: var(--app-danger); }
.session-action:focus-visible { outline: var(--app-focus); outline-offset: -2px; }

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
.tab.active { color: var(--app-primary-strong); border-bottom-color: var(--app-primary); font-weight: 600; }
.tab:focus-visible { outline: var(--app-focus); outline-offset: -2px; }
.drawer-close { flex: 0 0 auto; width: var(--app-touch); }

.toolbar-btn:focus-visible,
.prompt-lib-btn:focus-visible,
.suggestion-chip:focus-visible { outline: var(--app-focus); outline-offset: 1px; }

/* ── Tablet: the agents/provenance panel becomes a drawer from the right ── */
@media (max-width: 1100px) {
  .activity-toggle,
  .only-narrow { display: inline-flex; }
  .panel-tab-bar.only-narrow { display: flex; }
  .drawer-scrim {
    display: block;
    position: absolute;
    inset: 0;
    background: rgba(17, 24, 39, 0.35);
    z-index: 20;
  }

  .activity-panel {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(340px, 92vw);
    background: var(--app-bg);
    z-index: 30;
    box-shadow: -8px 0 24px rgba(17, 24, 39, 0.12);
    transform: translateX(100%);
    visibility: hidden;
    transition: transform 0.2s ease, visibility 0s linear 0.2s;
  }
  .activity-panel.open {
    transform: none;
    visibility: visible;
    transition: transform 0.2s ease;
  }
}

/* ── Phone: the session list becomes a drawer from the left too ── */
@media (max-width: 720px) {
  .sessions-toggle { display: inline-flex; gap: 0.3rem; align-items: center; }

  .session-sidebar {
    position: absolute;
    top: 0;
    left: 0;
    bottom: 0;
    width: min(300px, 85vw);
    z-index: 30;
    box-shadow: 8px 0 24px rgba(17, 24, 39, 0.12);
    transform: translateX(-100%);
    visibility: hidden;
    transition: transform 0.2s ease, visibility 0s linear 0.2s;
  }
  .session-sidebar.open {
    transform: none;
    visibility: visible;
    transition: transform 0.2s ease;
  }

  .chat-toolbar { flex-wrap: wrap; gap: 0.4rem; padding: 0.4rem 0.5rem; }
  .session-title-display { flex: 1; max-width: none; min-width: 0; }
  .toolbar-actions { flex-wrap: wrap; width: 100%; }
  .system-prompt-panel { padding: 0.5rem; }
  .suggestions { padding: 0.5rem; }
}

/* Thumb-sized targets wherever the pointer is a finger. */
@media (pointer: coarse) {
  .toolbar-btn,
  .prompt-lib-btn { min-height: var(--app-touch); padding: 0 0.75rem; }
  .new-session-btn,
  .session-action { width: var(--app-touch); height: var(--app-touch); }
  .session-open { min-height: var(--app-touch); }
  .suggestion-chip { min-height: 36px; }
}
</style>
