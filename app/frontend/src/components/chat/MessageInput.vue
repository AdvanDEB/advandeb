<template>
  <div class="message-input-area">
    <form @submit.prevent="submit">
      <textarea
        ref="inputEl"
        v-model="text"
        :disabled="disabled"
        placeholder="Ask about DEB theory, your data, or run a scenario…"
        rows="3"
        @keydown.enter.exact.prevent="submit"
        @keydown.enter.shift.exact="text += '\n'"
      ></textarea>

      <div class="input-controls">
        <span class="hint">Enter to send · Shift+Enter for new line</span>
        <button type="submit" :disabled="disabled || !text.trim()" class="send-btn">
          <span v-if="disabled" class="spinner"></span>
          <span v-else>Send</span>
        </button>
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  disabled: boolean
}>()

const emit = defineEmits<{
  (e: 'send', text: string): void
}>()

const text = ref('')
const inputEl = ref<HTMLTextAreaElement>()

function submit() {
  const trimmed = text.value.trim()
  if (!trimmed || props.disabled) return
  emit('send', trimmed)
  text.value = ''
}
</script>

<style scoped>
.message-input-area {
  border-top: 1px solid #e5e7eb;
  padding: 0.75rem 1rem;
  background: white;
}

form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

textarea {
  width: 100%;
  resize: none;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 0.625rem 0.75rem;
  font-family: inherit;
  font-size: 0.9rem;
  line-height: 1.5;
  outline: none;
  transition: border-color 0.15s;
}

textarea:focus {
  border-color: #3b82f6;
}

textarea:disabled {
  background: #f9fafb;
  color: #9ca3af;
}

.input-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.hint {
  font-size: 0.75rem;
  color: #9ca3af;
}

.send-btn {
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.4rem 1rem;
  font-size: 0.875rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  transition: background 0.15s;
}

.send-btn:hover:not(:disabled) {
  background: #2563eb;
}

.send-btn:disabled {
  background: #93c5fd;
  cursor: not-allowed;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: white;
  border-radius: 50%;
  display: inline-block;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
