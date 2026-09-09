<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <header class="modal-head">
        <h2>New model</h2>
        <button class="btn-close" aria-label="Close" @click="emit('close')">×</button>
      </header>

      <div class="modal-body">
        <div class="group">
          <div class="group-title">Start from scratch</div>
          <div class="card-grid">
            <button class="card card-empty" @click="emit('create', null)">
              <h3>Empty model</h3>
              <p>Add compartments and transport channels by hand.</p>
            </button>
          </div>
        </div>

        <div v-if="published.length" class="group">
          <div class="group-title">
            Shared templates <span class="group-source">published by curators</span>
          </div>
          <div class="card-grid">
            <button
              v-for="p in published"
              :key="p.id"
              class="card"
              @click="emit('copy', p)"
            >
              <h3>{{ p.name }}</h3>
              <p>{{ p.description || `${p.n_nodes} compartments · ${p.n_edges} channels` }}</p>
              <span class="card-by">by {{ p.owner_email || 'a curator' }}</span>
            </button>
          </div>
        </div>

        <div class="group">
          <div class="group-title">Built-in templates</div>
          <div class="card-grid">
            <button
              v-for="t in abstractTemplates"
              :key="t.id"
              class="card"
              @click="emit('create', t.id)"
            >
              <h3>{{ t.name }}</h3>
              <p>{{ t.description }}</p>
            </button>
          </div>
        </div>

        <div class="group">
          <div class="group-title">
            Organism examples <span class="group-source">AmP database</span>
          </div>
          <div class="card-grid">
            <button
              v-for="t in organismTemplates"
              :key="t.id"
              class="card"
              @click="emit('create', t.id)"
            >
              <h3><em>{{ t.name }}</em></h3>
              <p>{{ t.description }}</p>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import type { TDebModelSummary, TDebTemplate } from '@/utils/tdebApi'

const props = defineProps<{
  templates: TDebTemplate[]
  published: TDebModelSummary[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  /** null means "empty model". */
  (e: 'create', templateId: string | null): void
  (e: 'copy', model: TDebModelSummary): void
}>()

const abstractTemplates = computed(() =>
  props.templates.filter(t => t.category === 'template'))
const organismTemplates = computed(() =>
  props.templates.filter(t => t.category === 'organism'))

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
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
  width: min(880px, 100%);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.28);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid #e5e7eb;
}
.modal-head h2 { font-size: 1.05rem; font-weight: 600; color: #111827; margin: 0; }
.btn-close {
  background: none; border: none; font-size: 1.5rem; line-height: 1;
  color: #9ca3af; cursor: pointer;
}
.btn-close:hover { color: #374151; }

.modal-body { padding: 1.1rem 1.25rem 1.5rem; overflow-y: auto; }
.group { margin-bottom: 1.4rem; }
.group-title {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
  margin-bottom: 0.6rem;
}
.group-source {
  font-weight: 400; text-transform: none; letter-spacing: 0; color: #9ca3af;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 0.7rem;
}
.card {
  text-align: left;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 0.8rem;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.card:hover { border-color: #93c5fd; box-shadow: 0 2px 8px rgba(59, 130, 246, 0.12); }
.card h3 { font-size: 0.85rem; font-weight: 600; color: #111827; margin: 0 0 0.3rem; }
.card p { font-size: 0.74rem; color: #6b7280; line-height: 1.5; margin: 0; }
.card-by { display: block; font-size: 0.68rem; color: #9ca3af; margin-top: 0.35rem; }
.card-empty { border-style: dashed; }
</style>
