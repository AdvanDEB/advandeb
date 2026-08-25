<template>
  <div class="admin-chats-view">
    <header class="page-header">
      <button class="back-link" @click="router.push('/admin/users')">&larr; Back to Users</button>
      <h1>{{ targetUser?.full_name || targetUser?.email || 'User' }}'s conversations</h1>
      <div class="consent-banner">
        You are viewing <strong>{{ targetUser?.email }}</strong>'s conversation history for research
        purposes. This access is logged and visible to the user in their Privacy settings.
      </div>
    </header>

    <div class="chats-layout">
      <!-- Session list -->
      <aside class="session-sidebar">
        <div class="sidebar-header">Conversations</div>
        <p v-if="loadingSessions" class="muted pad">Loading…</p>
        <p v-else-if="sessions.length === 0" class="muted pad">No conversations yet.</p>
        <ul v-else class="session-list">
          <li
            v-for="s in sessions"
            :key="s.id"
            :class="['session-item', { active: s.id === selectedSessionId }]"
            @click="selectSession(s.id)"
          >
            <span class="session-title">{{ s.title || 'Untitled' }}</span>
            <span class="session-date">{{ formatDate(s.updated_at) }}</span>
          </li>
        </ul>

        <div class="access-log-toggle" @click="showAccessLog = !showAccessLog">
          {{ showAccessLog ? 'Hide' : 'Show' }} access log ({{ accessLog.length }})
        </div>
        <div v-if="showAccessLog" class="access-log">
          <p v-if="accessLog.length === 0" class="muted pad">No prior access recorded.</p>
          <div v-for="(entry, i) in accessLog" :key="i" class="access-log-entry">
            <span>{{ entry.admin_email }}</span>
            <span class="muted">{{ formatDate(entry.accessed_at) }}</span>
          </div>
        </div>
      </aside>

      <!-- Read-only message thread -->
      <div class="messages-pane">
        <p v-if="loadingMessages" class="muted pad">Loading…</p>
        <p v-else-if="!selectedSessionId" class="muted pad">Select a conversation to view it.</p>
        <p v-else-if="messages.length === 0" class="muted pad">No messages in this conversation.</p>
        <div v-else class="messages">
          <div v-for="m in messages" :key="m.id" :class="['message', m.role]">
            <div class="message-bubble">
              <div class="message-content" v-html="renderMarkdown(m.content)"></div>
              <div v-if="m.citations && m.citations.length > 0" class="citations">
                <span v-for="c in m.citations" :key="c.citation_id" class="citation-badge">
                  [{{ c.marker }}]
                </span>
              </div>
              <div v-if="m.timestamp" class="msg-timestamp">{{ formatDate(m.timestamp) }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { getUser } from '@/utils/usersApi'
import { getUserAccessLog, getUserSession, listUserSessions } from '@/utils/adminChatApi'
import type { AdminUser } from '@/types/user'
import type { AdminChatSession, ChatAccessLogEntry } from '@/types/adminChat'
import type { ChatMessage } from '@/types/chat'

const route = useRoute()
const router = useRouter()
const userId = route.params.id as string

const targetUser = ref<AdminUser | null>(null)
const sessions = ref<AdminChatSession[]>([])
const loadingSessions = ref(true)
const selectedSessionId = ref<string | null>(null)
const messages = ref<ChatMessage[]>([])
const loadingMessages = ref(false)
const accessLog = ref<ChatAccessLogEntry[]>([])
const showAccessLog = ref(false)

function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked(text) as string)
}

function formatDate(iso?: string): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

async function selectSession(sessionId: string) {
  selectedSessionId.value = sessionId
  loadingMessages.value = true
  try {
    const detail = await getUserSession(userId, sessionId)
    messages.value = detail.messages
  } catch {
    // interceptor toasts; bounce back to the list on 403 (opted out mid-session)
    selectedSessionId.value = null
  } finally {
    loadingMessages.value = false
  }
}

onMounted(async () => {
  try {
    targetUser.value = await getUser(userId)
  } catch {
    // interceptor toasts
  }
  try {
    sessions.value = await listUserSessions(userId)
  } catch {
    // interceptor toasts (e.g. 403 if opted out since the admin list was loaded)
  } finally {
    loadingSessions.value = false
  }
  try {
    accessLog.value = await getUserAccessLog(userId)
  } catch {
    // interceptor toasts
  }
})
</script>

<style scoped>
.admin-chats-view {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  height: 100vh;
  box-sizing: border-box;
}

.back-link {
  background: none;
  border: none;
  color: #3b82f6;
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0;
  margin-bottom: 0.5rem;
}
.back-link:hover { text-decoration: underline; }

.page-header h1 { font-size: 1.3rem; font-weight: 700; color: #111827; }

.consent-banner {
  margin-top: 0.6rem;
  padding: 0.6rem 0.9rem;
  background: #fffbeb;
  border: 1px solid #fcd34d;
  border-radius: 6px;
  color: #92400e;
  font-size: 0.85rem;
}

.chats-layout {
  flex: 1;
  display: flex;
  gap: 1rem;
  overflow: hidden;
}

.session-sidebar {
  width: 260px;
  flex-shrink: 0;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f9fafb;
}

.sidebar-header {
  padding: 0.6rem 0.9rem;
  font-weight: 600;
  font-size: 0.85rem;
  border-bottom: 1px solid #e5e7eb;
}

.pad { padding: 0.75rem 0.9rem; }
.muted { color: #9ca3af; font-size: 0.85rem; }

.session-list { list-style: none; overflow-y: auto; flex: 1; padding: 0.3rem 0; margin: 0; }
.session-item {
  padding: 0.5rem 0.9rem;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
.session-item:hover { background: #e5e7eb; }
.session-item.active { background: #dbeafe; }
.session-title { font-size: 0.85rem; color: #111827; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.session-date { font-size: 0.7rem; color: #9ca3af; }

.access-log-toggle {
  padding: 0.5rem 0.9rem;
  font-size: 0.78rem;
  color: #3b82f6;
  cursor: pointer;
  border-top: 1px solid #e5e7eb;
}
.access-log { padding: 0 0.9rem 0.75rem; max-height: 160px; overflow-y: auto; }
.access-log-entry { display: flex; justify-content: space-between; font-size: 0.78rem; padding: 0.25rem 0; gap: 0.5rem; }

.messages-pane {
  flex: 1;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow-y: auto;
  background: #fff;
}

.messages { padding: 1rem; display: flex; flex-direction: column; gap: 0.75rem; }

.message { display: flex; }
.message.user { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }

.message-bubble {
  max-width: 70%;
  padding: 0.6rem 0.9rem;
  border-radius: 10px;
  font-size: 0.9rem;
}
.message.user .message-bubble { background: #dbeafe; color: #1e3a8a; }
.message.assistant .message-bubble { background: #f3f4f6; color: #111827; }

.message-content :deep(p) { margin: 0 0 0.5rem; }
.message-content :deep(p:last-child) { margin-bottom: 0; }

.citations { margin-top: 0.4rem; display: flex; flex-wrap: wrap; gap: 0.3rem; }
.citation-badge {
  font-size: 0.72rem;
  color: #4b5563;
  background: #e5e7eb;
  padding: 0.05rem 0.4rem;
  border-radius: 4px;
}

.msg-timestamp { margin-top: 0.3rem; font-size: 0.7rem; color: #9ca3af; }
</style>
