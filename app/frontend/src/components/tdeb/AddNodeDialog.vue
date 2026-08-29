<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <header class="modal-head">
        <h2>Add compartment</h2>
        <button class="btn-close" aria-label="Close" @click="emit('close')">×</button>
      </header>

      <div class="modal-body">
        <label class="field">
          <span>Type</span>
          <select v-model="nodeType">
            <option v-for="t in NODE_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </label>

        <label class="field">
          <span>Name</span>
          <input v-model="name" type="text" :placeholder="defaultName" @keydown.enter="submit" />
        </label>

        <label class="field">
          <span>Initial value</span>
          <input v-model.number="initialValue" type="number" step="any" @keydown.enter="submit" />
        </label>

        <button class="btn-primary" @click="submit">Add</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { NodeTypeId } from '@/utils/tdebApi'
import { NODE_TYPES } from '@/utils/tdebConstants'

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'add', payload: { name: string; node_type: NodeTypeId; initial_value: number }): void
}>()

const nodeType = ref<NodeTypeId>('reserve')
const name = ref('')
const initialValue = ref(0)

const defaultName = computed(() =>
  NODE_TYPES.find(t => t.value === nodeType.value)?.label ?? nodeType.value)

function submit() {
  emit('add', {
    name: name.value.trim() || defaultName.value,
    node_type: nodeType.value,
    initial_value: Number.isFinite(initialValue.value) ? initialValue.value : 0,
  })
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
  padding: 1.5rem;
}
.modal {
  background: #fff;
  border-radius: 10px;
  width: min(380px, 100%);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.28);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.9rem 1.1rem;
  border-bottom: 1px solid #e5e7eb;
}
.modal-head h2 { font-size: 0.95rem; font-weight: 600; color: #111827; margin: 0; }
.btn-close {
  background: none;
  border: none;
  font-size: 1.4rem;
  line-height: 1;
  color: #9ca3af;
  cursor: pointer;
}
.btn-close:hover { color: #374151; }

.modal-body { padding: 1rem 1.1rem 1.2rem; display: flex; flex-direction: column; gap: 0.75rem; }
.field { display: flex; flex-direction: column; gap: 0.25rem; }
.field > span { font-size: 0.72rem; font-weight: 600; color: #4b5563; }
.field input,
.field select {
  border: 1px solid #d1d5db;
  border-radius: 5px;
  padding: 0.35rem 0.5rem;
  font-size: 0.82rem;
  color: #111827;
  background: #fff;
}
.btn-primary {
  margin-top: 0.2rem;
  background: #3b82f6;
  color: #fff;
  border: none;
  border-radius: 5px;
  padding: 0.4rem 0.9rem;
  font-size: 0.82rem;
  cursor: pointer;
}
.btn-primary:hover { background: #2563eb; }
</style>
