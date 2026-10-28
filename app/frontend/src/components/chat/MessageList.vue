<template>
  <div ref="listEl" class="message-list" role="region" aria-label="Conversation">
    <div v-if="messages.length === 0" class="empty-state">
      <p>Start a conversation about DEB theory or your data.</p>
    </div>

    <div
      v-for="message in messages"
      :key="message.id"
      :class="['message', message.role]"
    >
      <div class="message-bubble">
        <span class="sr-only">{{ message.role === 'user' ? 'You said:' : 'Assistant:' }}</span>
        <!-- Reconnect placeholder: generating=true AND no content yet -->
        <div v-if="message.generating && !message.content && !message.streaming" class="generating-indicator" aria-hidden="true">
          <span class="dot"></span><span class="dot"></span><span class="dot"></span>
        </div>

        <!-- Streaming or normal content -->
        <div v-else class="message-content" v-html="renderMarkdown(message.content)"></div>
        <!-- Streaming cursor -->
        <span v-if="message.streaming" class="stream-cursor" aria-hidden="true"></span>

        <div
          v-if="message.evidence_mode && message.evidence_mode !== 'local'"
          class="evidence-mode"
        >
          {{ evidenceModeLabel(message.evidence_mode) }}
        </div>

        <!-- Citations -->
        <div v-if="message.citations && message.citations.length > 0" class="citations">
          <button
            v-for="citation in message.citations"
            :key="citation.citation_id"
            type="button"
            class="citation-badge"
            :title="citationTooltip(citation)"
            :aria-label="`Source ${citation.marker}${citation.title ? ': ' + citation.title : ''} — show provenance`"
            @click="$emit('show-provenance', citation)"
          >
            [{{ citation.marker }}]<span v-if="citation.title" class="citation-title-inline"> {{ citation.title }}</span>
          </button>
        </div>

        <!-- Timestamp: revealed on hover or focus, always shown on touch -->
        <div v-if="message.timestamp" class="msg-timestamp">
          <time :datetime="message.timestamp">{{ formatRelativeTime(message.timestamp) }}</time>
        </div>
      </div>

      <!-- Message actions. These were rendered only while the pointer hovered
           the message, so a keyboard or touch user could never reach Copy,
           Retry or the feedback buttons. They are always in the DOM now:
           faded until hover or focus on a mouse device, plainly visible on a
           touch screen. -->
      <div
        v-if="!message.generating && !message.streaming"
        :class="['message-actions', message.role]"
        role="group"
        :aria-label="message.role === 'user' ? 'Your message actions' : 'Reply actions'"
      >
        <button type="button" class="action-btn" title="Copy" aria-label="Copy message" @click="copyMessage(message.content)">
          <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        </button>
        <template v-if="message.role === 'assistant'">
          <button type="button" class="action-btn" title="Retry" aria-label="Retry this answer" @click="$emit('retry', message.id)">
            <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
          </button>
          <button
            type="button"
            class="action-btn"
            :class="{ active: message.feedback === 1 }"
            title="Helpful"
            aria-label="Helpful"
            :aria-pressed="message.feedback === 1"
            @click="$emit('feedback', message.id, 1)"
          >
            <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
          </button>
          <button
            type="button"
            class="action-btn"
            :class="{ active: message.feedback === -1 }"
            title="Not helpful"
            aria-label="Not helpful"
            :aria-pressed="message.feedback === -1"
            @click="$emit('feedback', message.id, -1)"
          >
            <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"/><path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>
          </button>
        </template>
      </div>
    </div>

    <!-- Streaming tokens are not announced one by one — that would be noise.
         A screen reader hears "Assistant is responding" when a reply starts
         and the finished reply once it is complete. -->
    <div class="sr-only" role="status" aria-live="polite" aria-atomic="true">{{ liveStatus }}</div>
    <div class="sr-only" aria-live="polite" aria-atomic="true">{{ liveReply }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import type { ChatMessage as Message, CitationRef as Citation, EvidenceMode } from '@/types/chat'
import { renderMarkdown } from '@/utils/markdown'
import { formatRelativeTime } from '@/utils/format'

const props = defineProps<{
  messages: Message[]
}>()

defineEmits<{
  (e: 'show-provenance', citation: Citation): void
  (e: 'retry', messageId: string): void
  (e: 'feedback', messageId: string, rating: 1 | -1): void
}>()

const listEl = ref<HTMLElement>()
const liveStatus = ref('')
const liveReply = ref('')

// Delegate copy-code clicks via event delegation on the list container
onMounted(() => {
  listEl.value?.addEventListener('click', (e) => {
    const btn = (e.target as Element).closest<HTMLButtonElement>('.code-copy-btn')
    if (!btn) return
    const code = btn.dataset.code || ''
    navigator.clipboard.writeText(code).catch(() => {})
    btn.textContent = 'Copied!'
    setTimeout(() => { btn.textContent = 'Copy' }, 1500)
  })
})

// Auto-scroll when new tokens arrive or new messages appear
watch(
  [() => props.messages.length, () => props.messages[props.messages.length - 1]?.content],
  async () => {
    await nextTick()
    if (listEl.value) {
      listEl.value.scrollTop = listEl.value.scrollHeight
    }
  },
)

function plainText(markdown: string): string {
  const el = document.createElement('div')
  el.innerHTML = renderMarkdown(markdown)
  return (el.textContent || '').replace(/\s+/g, ' ').trim()
}

// Announce the start and the end of an assistant reply, nothing in between.
watch(
  () => {
    const last = props.messages[props.messages.length - 1]
    return last && last.role === 'assistant'
      ? { id: last.id, busy: !!(last.streaming || last.generating) }
      : null
  },
  (now, before) => {
    if (!now) return
    if (now.busy && !(before?.id === now.id && before.busy)) {
      liveStatus.value = 'Assistant is responding…'
    } else if (!now.busy && before?.id === now.id && before.busy) {
      const last = props.messages[props.messages.length - 1]
      liveStatus.value = 'Assistant replied.'
      liveReply.value = plainText(last.content)
    }
  },
)

function citationTooltip(c: Citation): string {
  const parts: string[] = []
  if (c.title) parts.push(c.title)
  if (c.authors?.length)
    parts.push(c.authors.slice(0, 3).join(', ') + (c.authors.length > 3 ? ' et al.' : ''))
  if (c.year) parts.push(String(c.year))
  if (c.journal) parts.push(c.journal)
  if (c.evidence_text) parts.push('\n' + c.evidence_text.slice(0, 120) + '…')
  return parts.join(' · ')
}

function evidenceModeLabel(mode: EvidenceMode): string {
  if (mode === 'local_plus_external') return 'Local KB + external literature'
  if (mode === 'external_fallback_labeled') return 'External literature fallback'
  return 'Local KB'
}

function copyMessage(content: string) {
  navigator.clipboard.writeText(content).catch(() => {})
}
</script>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.empty-state {
  text-align: center;
  color: #9ca3af;
  margin-top: 4rem;
  font-size: 0.95rem;
}

.message {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  position: relative;
}

.message.user { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }

.message-bubble {
  max-width: 72%;
  padding: 0.75rem 1rem;
  border-radius: 12px;
  font-size: 0.9rem;
  line-height: 1.5;
  position: relative;
}

.message.user .message-bubble {
  background: #3b82f6;
  color: white;
  border-bottom-right-radius: 4px;
}

.message.assistant .message-bubble {
  background: #f3f4f6;
  color: #111827;
  border-bottom-left-radius: 4px;
}

.stream-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  background: currentColor;
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: blink 0.9s step-end infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.message-content :deep(p) { margin: 0.25em 0; }
.message-content :deep(p:first-child) { margin-top: 0; }
.message-content :deep(p:last-child) { margin-bottom: 0; }

.message-content :deep(ul),
.message-content :deep(ol) {
  margin: 0.4em 0;
  padding-left: 1.4em;
}

.message-content :deep(code) {
  font-family: 'Fira Code', 'Courier New', monospace;
  font-size: 0.85em;
  background: rgba(0, 0, 0, 0.06);
  padding: 0.1em 0.3em;
  border-radius: 3px;
}

/* Code block wrapper from marked renderer */
.message-content :deep(.code-block-wrapper) {
  border-radius: 6px;
  overflow: hidden;
  margin: 0.5em 0;
  border: 1px solid rgba(0, 0, 0, 0.1);
}

.message-content :deep(.code-block-header) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.25rem 0.6rem;
  background: rgba(0, 0, 0, 0.12);
  font-size: 0.75rem;
}

.message-content :deep(.code-lang) {
  font-family: monospace;
  opacity: 0.7;
}

.message-content :deep(.code-copy-btn) {
  background: none;
  border: 1px solid rgba(255,255,255,0.3);
  color: inherit;
  font-size: 0.72rem;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  cursor: pointer;
  opacity: 0.7;
}
.message-content :deep(.code-copy-btn:hover) { opacity: 1; }

.message-content :deep(pre) {
  background: rgba(0, 0, 0, 0.08);
  padding: 0.6rem;
  margin: 0;
  overflow-x: auto;
  font-size: 0.85em;
}

.message-content :deep(pre code) {
  background: none;
  padding: 0;
  border-radius: 0;
}

.citations {
  margin-top: 0.5rem;
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.evidence-mode {
  margin-top: 0.4rem;
  color: #7c3aed;
  font-size: 0.72rem;
  font-weight: 600;
}

.citation-badge {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #2563eb;
  font-size: 0.78rem;
  cursor: pointer;
  border-radius: 4px;
  padding: 0.1rem 0.4rem;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  max-width: 240px;
  overflow: hidden;
}
.citation-badge:hover { background: #dbeafe; color: #1d4ed8; }

.citation-title-inline {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-style: italic;
}

.msg-timestamp {
  font-size: 0.7rem;
  color: var(--app-ink-4);
  margin-top: 0.25rem;
  text-align: right;
}
.message.user .msg-timestamp { color: rgba(255, 255, 255, 0.8); }
.message.assistant .msg-timestamp { text-align: left; }

/* Action toolbar */
.message-actions {
  display: flex;
  gap: 0.2rem;
  align-items: center;
  flex-shrink: 0;
  margin-bottom: 0.25rem;
}
.message-actions.user { order: -1; }

/* On a mouse device the actions and timestamp stay out of the way until the
   message is hovered or anything in it has keyboard focus. Faded rather than
   removed, so Tab still reaches them. */
@media (hover: hover) and (pointer: fine) {
  .message-actions,
  .msg-timestamp {
    opacity: 0;
    transition: opacity 0.12s ease;
  }
  .message:hover .message-actions,
  .message:focus-within .message-actions,
  .message:hover .msg-timestamp,
  .message:focus-within .msg-timestamp { opacity: 1; }
}

.action-btn {
  background: white;
  border: 1px solid #e5e7eb;
  color: #6b7280;
  border-radius: 5px;
  padding: 0.25rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, border-color 0.15s;
}
.action-btn:hover { color: var(--app-ink-2); border-color: var(--app-ink-4); }
.action-btn:focus-visible { outline: var(--app-focus); outline-offset: 1px; }
.action-btn.active { color: var(--app-primary-strong); border-color: var(--app-primary); }

@media (pointer: coarse) {
  .action-btn { min-width: 36px; min-height: 36px; }
}

@media (max-width: 720px) {
  .message-list { padding: 1rem 0.5rem; }
  .message-bubble { max-width: 88%; }
  /* Beside a 88% bubble there is no room for a column of buttons. */
  .message { flex-wrap: wrap; }
  .message.user .message-actions { order: 1; width: 100%; justify-content: flex-end; }
  .message.assistant .message-actions { width: 100%; }
}

/* Generating / reconnect spinner */
.generating-indicator {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 4px 0;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #9ca3af;
  animation: bounce 1.2s infinite ease-in-out;
}
.dot:nth-child(1) { animation-delay: 0s; }
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.7); opacity: 0.5; }
  40%            { transform: scale(1);   opacity: 1; }
}
</style>
