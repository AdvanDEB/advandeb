<template>
  <div class="search-overlay">
    <input
      v-model="query"
      type="text"
      placeholder="🔍 Search nodes..."
      class="search-input"
      @input="$emit('search', query)"
      @keydown.escape="clear"
    />
    <button v-if="query" class="clear-btn" @click="clear">✕</button>
  </div>
</template>

<script>
import { ref } from 'vue'

export default {
  name: 'SearchOverlay',
  emits: ['search'],
  setup(_, { emit }) {
    const query = ref('')

    function clear() {
      query.value = ''
      emit('search', '')
    }

    return { query, clear }
  },
}
</script>

<style scoped>
.search-overlay {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 4px;
}

.search-input {
  width: 220px;
  padding: 7px 12px;
  border: 1px solid #ddd;
  border-radius: 20px;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.search-input:focus {
  border-color: #4a90e2;
  box-shadow: 0 2px 8px rgba(74, 144, 226, 0.2);
}

.clear-btn {
  background: rgba(255,255,255,0.9);
  border: 1px solid #ddd;
  border-radius: 50%;
  width: 24px;
  height: 24px;
  cursor: pointer;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #666;
}

.clear-btn:hover { color: #333; background: #fff; }
</style>
