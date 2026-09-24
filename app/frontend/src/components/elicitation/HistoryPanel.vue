<template>
  <section class="card history">
    <header class="h-head">
      <h3>Your decisions</h3>
      <input
        v-model="q"
        class="search"
        type="search"
        placeholder="Search statements and rationales…"
        @input="debouncedFetch"
      />
    </header>

    <p class="note">
      Your own past judgments. Worth a look before a hard item — consistency
      with yourself is the floor under consistency with anyone else.
    </p>

    <div v-if="loading" class="state">Loading…</div>
    <div v-else-if="unavailable" class="state">
      History is unavailable right now.
    </div>
    <div v-else-if="!rows.length" class="state">
      {{ q ? 'Nothing matches that search.' : 'No decisions recorded yet.' }}
    </div>

    <ul v-else class="rows">
      <li v-for="r in rows" :key="r.id || `${r.sf_number}-${r.task}`" class="row">
        <div class="r-head">
          <span class="badge">#{{ r.sf_number }}</span>
          <span class="badge task">{{ r.task }}</span>
          <span class="chosen">{{ labelFor(r) }}</span>
          <span class="conf" :title="`confidence ${r.confidence}/5`">
            {{ '●'.repeat(r.confidence || 0) }}<span class="dim">{{ '○'.repeat(5 - (r.confidence || 0)) }}</span>
          </span>
          <span v-if="r.time_spent_s" class="time">{{ Math.round(r.time_spent_s) }}s</span>
        </div>
        <p class="stmt">{{ r.statement }}</p>
        <p v-if="r.rationale" class="rat">{{ r.rationale }}</p>
      </li>
    </ul>

    <button v-if="hasMore && !loading" class="ghost more" @click="fetchMore">
      Load more
    </button>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api from '@/utils/api'
import { optionFor, type TaskType } from './taskOptions'

interface HistoryRow {
  id?: string
  sf_number: number
  statement: string
  task: TaskType
  provenance_type?: string | null
  scope_verdict?: string | null
  assessability?: string | null
  confidence?: number
  rationale?: string
  time_spent_s?: number
  created_at?: string
}

const rows = ref<HistoryRow[]>([])
const q = ref('')
const loading = ref(true)
const unavailable = ref(false)
const hasMore = ref(false)
const offset = ref(0)
const LIMIT = 25

let timer: number | undefined
function debouncedFetch() {
  if (timer) window.clearTimeout(timer)
  timer = window.setTimeout(() => { offset.value = 0; fetch(true) }, 250)
}

function labelFor(r: HistoryRow): string {
  const value = r.provenance_type ?? r.scope_verdict ?? r.assessability ?? null
  return optionFor(r.task, value)?.label ?? value ?? '—'
}

async function fetch(reset = false) {
  loading.value = true
  try {
    const { data } = await api.get('/elicitation/history', {
      params: { q: q.value || undefined, limit: LIMIT, offset: offset.value },
    })
    const items: HistoryRow[] = data?.items ?? []
    rows.value = reset ? items : [...rows.value, ...items]
    hasMore.value = typeof data?.total === 'number'
      ? rows.value.length < data.total
      : items.length === LIMIT
    unavailable.value = false
  } catch {
    // History is a convenience; its absence must not break elicitation.
    unavailable.value = true
    hasMore.value = false
  } finally {
    loading.value = false
  }
}

function fetchMore() {
  offset.value += LIMIT
  fetch(false)
}

onMounted(() => fetch(true))
defineExpose({ refresh: () => { offset.value = 0; fetch(true) } })
</script>

<style scoped>
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 1.1rem 1.25rem; }
.h-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.h-head h3 { font-size: 1rem; font-weight: 600; color: #111827; }
.search { padding: 0.4rem 0.6rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.85rem; min-width: 16rem; }
.note { font-size: 0.8rem; color: #6b7280; margin: 0.4rem 0 0.9rem; line-height: 1.5; }

.rows { list-style: none; display: flex; flex-direction: column; gap: 0.9rem; max-height: 50vh; overflow-y: auto; }
.row { border-left: 3px solid #e5e7eb; padding-left: 0.8rem; }
.r-head { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.25rem; }
.badge { background: #eef2ff; color: #3730a3; border-radius: 5px; padding: 0.1rem 0.4rem; font-size: 0.72rem; font-weight: 600; }
.badge.task { background: #f3f4f6; color: #4b5563; font-weight: 500; }
.chosen { font-size: 0.82rem; font-weight: 600; color: #111827; }
.conf { font-size: 0.7rem; color: #111827; letter-spacing: 1px; }
.conf .dim { color: #d1d5db; }
.time { font-size: 0.72rem; color: #9ca3af; margin-left: auto; }
.stmt { font-size: 0.85rem; color: #374151; line-height: 1.5; }
.rat { font-size: 0.8rem; color: #6b7280; margin-top: 0.25rem; font-style: italic; line-height: 1.5; }

.state { padding: 1.5rem 0; text-align: center; color: #9ca3af; font-size: 0.85rem; }
.ghost { background: #fff; border: 1px solid #d1d5db; border-radius: 6px; padding: 0.45rem 0.9rem; cursor: pointer; font-size: 0.85rem; }
.more { margin-top: 0.9rem; }
</style>
