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
        <!-- Render markdown safely -->
        <div class="message-content" v-html="renderMarkdown(message.content)"></div>

        <!-- Citations -->
        <div v-if="message.citations && message.citations.length > 0" class="citations">
          <button
            v-for="citation in message.citations"
            :key="citation.id"
            class="citation-badge"
            @click="$emit('show-provenance', citation)"
          >
            [{{ citation.index }}]
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { marked } from 'marked'

interface Citation {
  id: string
  index: number
  text: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}

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

.citation-badge {
  background: none;
  border: none;
  color: #2563eb;
  font-size: 0.8rem;
  cursor: pointer;
  text-decoration: underline;
  padding: 0;
}

.citation-badge:hover {
  color: #1d4ed8;
}
</style>
