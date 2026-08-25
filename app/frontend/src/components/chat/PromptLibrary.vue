<template>
  <div class="prompt-library">
    <div class="library-header">
      <span class="library-title">Starter prompts</span>
      <button class="close-btn" @click="$emit('close')">✕</button>
    </div>
    <ul class="prompt-list">
      <li
        v-for="(prompt, i) in prompts"
        :key="i"
        class="prompt-item"
        @click="$emit('select', prompt)"
      >
        {{ prompt }}
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
defineEmits<{
  (e: 'select', text: string): void
  (e: 'close'): void
}>()

const prompts = [
  'What is the kappa rule in DEB theory and how does it affect growth and reproduction?',
  'Explain the role of reserve dynamics in DEB models — what is mobilised and when?',
  'How does temperature affect metabolic rates in DEB theory?',
  'What is the difference between V1-morphs and isomorphs in DEB, and when does it matter?',
  'How are DEB parameters typically estimated from experimental data?',
  'What is the role of maturation threshold (Ep) in DEB theory?',
  'Explain structural volume vs. reserve mass in DEB — what can each be used for?',
  'What is DEBtool and what are its main components?',
  'How does hypoxia affect DEB model predictions for marine organisms?',
  'What is the role of assimilation efficiency in DEB-based bioenergetics?',
]
</script>

<style scoped>
.prompt-library {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  right: 0;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.12);
  z-index: 100;
  overflow: hidden;
}

.library-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid #f3f4f6;
  background: #f9fafb;
}

.library-title {
  font-size: 0.78rem;
  font-weight: 600;
  color: #374151;
}

.close-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: #9ca3af;
  font-size: 0.9rem;
  line-height: 1;
  padding: 0;
}
.close-btn:hover { color: #374151; }

.prompt-list {
  list-style: none;
  margin: 0;
  padding: 0.35rem 0;
  max-height: 300px;
  overflow-y: auto;
}

.prompt-item {
  padding: 0.5rem 0.75rem;
  font-size: 0.85rem;
  color: #374151;
  cursor: pointer;
  line-height: 1.4;
  border-bottom: 1px solid #f9fafb;
}
.prompt-item:last-child { border-bottom: none; }
.prompt-item:hover { background: #eff6ff; color: #2563eb; }
</style>
