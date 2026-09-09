<template>
  <div class="library">
    <header class="page-header">
      <div class="header-left">
        <h1>Models</h1>
        <span class="subtitle">tDEB — transport-network energy budgets</span>
      </div>
      <div class="header-actions">
        <input
          v-model="search"
          class="search"
          type="search"
          placeholder="Search your models…"
          aria-label="Search your models"
        />
        <button class="btn-ghost" @click="importJson">↑ Import</button>
        <button class="btn-primary" @click="showNew = true">＋ New model</button>
      </div>
    </header>

    <p v-if="error" class="banner error">{{ error }}</p>

    <!-- ── Your models ── -->
    <section class="section">
      <h2 class="section-title">
        Your models
        <span class="section-count">{{ models.length }}</span>
        <span class="section-note">private to you</span>
      </h2>

      <p v-if="loading" class="placeholder">Loading…</p>

      <p v-else-if="models.length === 0" class="placeholder">
        You haven't created any models yet.
        <button class="link-btn" @click="showNew = true">Start from a template</button>
        or import a model file.
      </p>

      <p v-else-if="visibleModels.length === 0" class="placeholder">
        No models match “{{ search }}”.
      </p>

      <div v-else class="card-grid">
        <article
          v-for="m in visibleModels"
          :key="m.id"
          class="card"
          tabindex="0"
          role="button"
          @click="open(m.id)"
          @keydown.enter="open(m.id)"
        >
          <div class="card-head">
            <h3>{{ m.name }}</h3>
            <span v-if="m.is_published" class="badge" title="Published as an org template">
              Published
            </span>
          </div>
          <p v-if="m.description" class="card-desc">{{ m.description }}</p>
          <p class="card-meta">
            {{ m.n_nodes }} compartments · {{ m.n_edges }} channels
          </p>
          <p class="card-meta dim">Edited {{ relativeTime(m.updated_at) }}</p>

          <div class="card-actions" @click.stop>
            <button class="card-action" @click="open(m.id)">Open</button>
            <button class="card-action" @click="duplicate(m)">Duplicate</button>
            <button
              v-if="canPublish"
              class="card-action"
              @click="togglePublish(m)"
            >{{ m.is_published ? 'Unpublish' : 'Publish' }}</button>
            <button class="card-action danger" @click="remove(m)">Delete</button>
          </div>
        </article>
      </div>
    </section>

    <!-- ── Org-published templates ── -->
    <section v-if="published.length" class="section">
      <h2 class="section-title">
        Shared templates
        <span class="section-count">{{ published.length }}</span>
        <span class="section-note">published by curators — opening makes your own copy</span>
      </h2>
      <div class="card-grid">
        <article v-for="p in published" :key="p.id" class="card card-shared">
          <div class="card-head"><h3>{{ p.name }}</h3></div>
          <p v-if="p.description" class="card-desc">{{ p.description }}</p>
          <p class="card-meta">{{ p.n_nodes }} compartments · {{ p.n_edges }} channels</p>
          <p class="card-meta dim">by {{ p.owner_email || 'a curator' }}</p>
          <div class="card-actions">
            <button class="card-action" @click="duplicate(p)">Copy to my models</button>
          </div>
        </article>
      </div>
    </section>

    <NewModelDialog
      v-if="showNew"
      :templates="templates"
      :published="published"
      @close="showNew = false"
      @create="createFromTemplate"
      @copy="duplicate"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import NewModelDialog from '@/components/tdeb/NewModelDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import * as tdeb from '@/utils/tdebApi'
import type { TDebModelSummary, TDebTemplate } from '@/utils/tdebApi'

const router = useRouter()
const auth = useAuthStore()
const notifications = useNotificationsStore()

const models = ref<TDebModelSummary[]>([])
const published = ref<TDebModelSummary[]>([])
const templates = ref<TDebTemplate[]>([])
const loading = ref(true)
const error = ref('')
const search = ref('')
const showNew = ref(false)

// Publishing is a curator/administrator act — mirrors require_curator on the API.
const canPublish = computed(() =>
  auth.hasRole('administrator') || auth.hasRole('knowledge_curator'))

const visibleModels = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return models.value
  return models.value.filter(m =>
    m.name.toLowerCase().includes(q) || m.description.toLowerCase().includes(q))
})

function message(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (typeof detail === 'string') return detail
  return err instanceof Error ? err.message : fallback
}

/** "3 minutes ago" style, falling back to a date once it stops being useful. */
function relativeTime(iso: string): string {
  if (!iso) return 'recently'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'recently'
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`
  return new Date(then).toLocaleDateString()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [mine, shared, tpl] = await Promise.all([
      tdeb.listModels(), tdeb.listPublished(), tdeb.listTemplates(),
    ])
    models.value = mine
    templates.value = tpl
    // A curator's own published models already appear under "Your models";
    // listing them again as shared templates would just be a duplicate card.
    published.value = shared.filter(p => !mine.some(m => m.id === p.id))
  } catch (err) {
    error.value = message(err, 'Could not load your models.')
  } finally {
    loading.value = false
  }
}

function open(id: string) {
  router.push({ name: 'model-editor', params: { id } })
}

async function createFromTemplate(templateId: string | null) {
  showNew.value = false
  try {
    const net = templateId
      ? await tdeb.createModel({ template: templateId })
      : await tdeb.createModel({ name: 'New model' })
    open(net.id)
  } catch (err) {
    notifications.error(message(err, 'Could not create the model.'))
  }
}

async function duplicate(model: TDebModelSummary) {
  showNew.value = false
  try {
    const copy = await tdeb.duplicateModel(model.id)
    open(copy.id)
  } catch (err) {
    notifications.error(message(err, 'Could not copy the model.'))
  }
}

async function togglePublish(model: TDebModelSummary) {
  const publishing = !model.is_published
  if (publishing && !window.confirm(
    `Publish "${model.name}" as a shared template? Everyone will be able to copy it `
    + `into their own models.`)) return

  try {
    const updated = publishing
      ? await tdeb.publishModel(model.id)
      : await tdeb.unpublishModel(model.id)
    model.is_published = updated.is_published
    notifications.success(
      publishing ? 'Published as a shared template.' : 'Withdrawn from shared templates.')
  } catch (err) {
    notifications.error(message(err, 'Could not change the published state.'))
  }
}

async function remove(model: TDebModelSummary) {
  if (!window.confirm(`Delete "${model.name}" permanently?`)) return
  try {
    await tdeb.deleteModel(model.id)
    models.value = models.value.filter(m => m.id !== model.id)
  } catch (err) {
    notifications.error(message(err, 'Could not delete the model.'))
  }
}

function importJson() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json,application/json'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return
    try {
      const net = await tdeb.createModel({ network: JSON.parse(await file.text()) })
      open(net.id)
    } catch (err) {
      notifications.error(message(err, 'Could not import that file.'))
    }
  }
  input.click()
}

onMounted(load)
</script>

<style scoped>
.library {
  padding: 1.25rem 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  overflow-y: auto;
  height: 100%;
}

.page-header { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
.header-left { display: flex; align-items: baseline; gap: 0.6rem; }
.page-header h1 { font-size: 1.4rem; font-weight: 700; color: #111827; margin: 0; }
.subtitle { font-size: 0.78rem; color: #6b7280; }
.header-actions { display: flex; gap: 0.4rem; margin-left: auto; flex-wrap: wrap; }

.search {
  border: 1px solid #d1d5db;
  border-radius: 5px;
  padding: 0.35rem 0.6rem;
  font-size: 0.8rem;
  min-width: 200px;
}
.search:focus { outline: 2px solid #bfdbfe; outline-offset: -1px; }

.btn-primary, .btn-ghost {
  border-radius: 5px;
  padding: 0.35rem 0.8rem;
  font-size: 0.8rem;
  cursor: pointer;
  border: 1px solid transparent;
}
.btn-primary { background: #3b82f6; color: #fff; }
.btn-primary:hover { background: #2563eb; }
.btn-ghost { background: #fff; color: #4b5563; border-color: #d1d5db; }
.btn-ghost:hover { background: #f3f4f6; }

.banner { border-radius: 6px; padding: 0.5rem 0.75rem; font-size: 0.8rem; margin: 0; }
.banner.error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }

.section { display: flex; flex-direction: column; gap: 0.7rem; }
.section-title {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 0.35rem;
  margin: 0;
}
.section-count {
  background: #e5e7eb;
  color: #374151;
  border-radius: 999px;
  padding: 0 0.4rem;
  font-size: 0.68rem;
}
.section-note {
  margin-left: auto;
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
  color: #9ca3af;
  font-size: 0.7rem;
}

.placeholder { font-size: 0.85rem; color: #6b7280; padding: 1.5rem 0; margin: 0; }
.link-btn {
  background: none;
  border: none;
  color: #2563eb;
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0;
  text-decoration: underline;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 0.75rem;
}
.card {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 0.85rem;
  background: #fff;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.card:hover, .card:focus-visible {
  border-color: #93c5fd;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.12);
  outline: none;
}
.card-shared { background: #f8fafc; cursor: default; }
.card-shared:hover { border-color: #e5e7eb; box-shadow: none; }

.card-head { display: flex; align-items: center; gap: 0.4rem; }
.card-head h3 {
  font-size: 0.88rem;
  font-weight: 600;
  color: #111827;
  margin: 0;
  flex: 1;
  overflow-wrap: anywhere;
}
.badge {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
  border-radius: 999px;
  padding: 0 0.4rem;
  font-size: 0.62rem;
  font-weight: 600;
  white-space: nowrap;
}
.card-desc {
  font-size: 0.75rem;
  color: #4b5563;
  margin: 0;
  line-height: 1.45;
}
.card-meta { font-size: 0.72rem; color: #6b7280; margin: 0; }
.card-meta.dim { color: #9ca3af; }

.card-actions {
  display: flex;
  gap: 0.3rem;
  flex-wrap: wrap;
  margin-top: 0.45rem;
  padding-top: 0.45rem;
  border-top: 1px solid #f3f4f6;
}
.card-action {
  background: none;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  padding: 0.18rem 0.5rem;
  font-size: 0.7rem;
  color: #4b5563;
  cursor: pointer;
}
.card-action:hover { background: #f3f4f6; color: #111827; }
.card-action.danger { color: #b91c1c; border-color: #fecaca; }
.card-action.danger:hover { background: #fef2f2; }
</style>
