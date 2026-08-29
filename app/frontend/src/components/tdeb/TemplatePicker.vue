<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <header class="modal-head">
        <h2>Choose a model</h2>
        <button class="btn-close" aria-label="Close" @click="emit('close')">×</button>
      </header>

      <div class="modal-body">
        <p v-if="loading" class="modal-note">Loading templates…</p>
        <p v-else-if="error" class="modal-note error">{{ error }}</p>

        <template v-else>
          <div v-if="savedModels.length" class="group">
            <div class="group-title">Your models</div>
            <div class="card-grid">
              <button
                v-for="m in savedModels"
                :key="m.id"
                class="card card-saved"
                @click="emit('open', m.id)"
              >
                <h3>{{ m.name }}</h3>
                <p>{{ m.n_nodes }} compartments · {{ m.n_edges }} channels</p>
                <span class="card-meta">Updated {{ formatDate(m.updated_at) }}</span>
                <span
                  class="card-delete"
                  role="button"
                  tabindex="0"
                  title="Delete model"
                  @click.stop="emit('delete', m.id)"
                  @keydown.enter.stop="emit('delete', m.id)"
                >×</span>
              </button>
            </div>
          </div>

          <div class="group">
            <div class="group-title">Templates</div>
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
              <button class="card card-empty" @click="emit('create', null)">
                <h3>Empty model</h3>
                <p>Start from scratch — add compartments and channels by hand.</p>
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
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TDebModelSummary, TDebTemplate } from '@/utils/tdebApi'

const props = defineProps<{
  templates: TDebTemplate[]
  savedModels: TDebModelSummary[]
  loading: boolean
  error: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  /** null means "empty model". */
  (e: 'create', templateId: string | null): void
  (e: 'open', modelId: string): void
  (e: 'delete', modelId: string): void
}>()

const abstractTemplates = computed(() =>
  props.templates.filter(t => t.category === 'template'))
const organismTemplates = computed(() =>
  props.templates.filter(t => t.category === 'organism'))

function formatDate(iso: string): string {
  if (!iso) return 'recently'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'recently' : d.toLocaleDateString()
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
  background: none;
  border: none;
  font-size: 1.5rem;
  line-height: 1;
  color: #9ca3af;
  cursor: pointer;
}
.btn-close:hover { color: #374151; }

.modal-body { padding: 1.1rem 1.25rem 1.5rem; overflow-y: auto; }
.modal-note { font-size: 0.85rem; color: #6b7280; text-align: center; padding: 2rem 0; }
.modal-note.error { color: #b91c1c; }

.group { margin-bottom: 1.5rem; }
.group-title {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
  margin-bottom: 0.6rem;
}
.group-source { font-weight: 400; text-transform: none; letter-spacing: 0; color: #9ca3af; }

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 0.7rem;
}
.card {
  position: relative;
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
.card-empty { border-style: dashed; }
.card-saved { background: #f8fafc; }
.card-meta { display: block; font-size: 0.68rem; color: #9ca3af; margin-top: 0.4rem; }
.card-delete {
  position: absolute;
  top: 0.35rem;
  right: 0.5rem;
  font-size: 1.05rem;
  line-height: 1;
  color: #cbd5e1;
  cursor: pointer;
}
.card-delete:hover { color: #ef4444; }
</style>
