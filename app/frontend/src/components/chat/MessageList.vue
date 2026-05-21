<template>
  <div ref="listEl" class="message-list">
    <div v-if="messages.length === 0" class="empty-state">
      <p>Start a conversation about DEB theory or your data.</p>
    </div>

    <div
      v-for="message in messages"
      :key="message.id"
      :class="['message', message.role]"
    >
      <div class="message-bubble">
        <!-- Generating spinner (reconnect catch-up) -->
        <div v-if="message.generating" class="generating-indicator">
          <span class="dot"></span><span class="dot"></span><span class="dot"></span>
        </div>

        <!-- Render markdown safely -->
        <div v-else class="message-content" v-html="renderMarkdown(message.content)"></div>

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
            class="citation-badge"
            :title="citationTooltip(citation)"
            @click="$emit('show-provenance', citation)"
          >
            [{{ citation.marker }}]<span v-if="citation.title" class="citation-title-inline"> {{ citation.title }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { marked } from 'marked'
import type { ChatMessage as Message, CitationRef as Citation, EvidenceMode } from '@/types/chat'

const props = defineProps<{
  messages: Message[]
}>()

defineEmits<{
  (e: 'show-provenance', citation: Citation): void
}>()

const listEl = ref<HTMLElement>()

// Auto-scroll to newest message
watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    if (listEl.value) {
      listEl.value.scrollTop = listEl.value.scrollHeight
    }
  }
)

function renderMarkdown(text: string): string {
  return marked(text) as string
}

function citationTooltip(c: Citation): string {
  const parts: string[] = []
  if (c.title) parts.push(c.title)
  if (c.authors?.length) parts.push(c.authors.slice(0, 3).join(', ') + (c.authors.length > 3 ? ' et al.' : ''))
  if (c.year) parts.push(String(c.year))
  if (c.journal) parts.push(c.journal)
  if (c.evidence_text) parts.push('\n' + c.evidence_text.slice(0, 120) + '…')
  return parts.join(' · ')
}

function evidenceModeLabel(mode: EvidenceMode): string {
  if (mode === 'local_plus_external') return 'Local KB answer with external literature support'
  if (mode === 'external_fallback_labeled') return 'External literature fallback'
  return 'Local KB support'
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
}

.message.user {
  justify-content: flex-end;
}

.message.assistant {
  justify-content: flex-start;
}

.message-bubble {
  max-width: 72%;
  padding: 0.75rem 1rem;
  border-radius: 12px;
  font-size: 0.9rem;
  line-height: 1.5;
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

.message-content :deep(p) {
  margin: 0.25em 0;
}

.message-content :deep(pre) {
  background: rgba(0, 0, 0, 0.08);
  padding: 0.5rem;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 0.85em;
}

.message-content :deep(code) {
  font-family: 'Fira Code', 'Courier New', monospace;
  font-size: 0.85em;
  background: rgba(0, 0, 0, 0.06);
  padding: 0.1em 0.3em;
  border-radius: 3px;
}

.citations {
  margin-top: 0.5rem;
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.evidence-mode {
  margin-top: 0.5rem;
  color: #7c3aed;
  font-size: 0.75rem;
  font-weight: 600;
}

.citation-badge {
  background: none;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
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

.citation-badge:hover {
  background: #dbeafe;
  color: #1d4ed8;
}

.citation-title-inline {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-style: italic;
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
