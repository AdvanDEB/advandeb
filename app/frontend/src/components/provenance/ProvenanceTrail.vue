<template>
  <div class="provenance-trail">
    <div class="trail-header">
      <h3>Citation Trail</h3>
      <button class="close-btn" @click="$emit('close')">✕</button>
    </div>

    <div v-if="loading" class="loading">Loading provenance…</div>

    <div v-else-if="error" class="error-state">{{ error }}</div>

    <div v-else-if="data" class="trail-body">

      <!-- Answer excerpt -->
      <div class="trail-level">
        <div class="level-label">Answer Excerpt</div>
        <div class="trail-item answer-item">
          "{{ data.answer?.excerpt }}"
        </div>
      </div>

      <div class="trail-connector">↓</div>

      <!-- Facts used -->
      <div class="trail-level">
        <div class="level-label">Facts Used</div>
        <div v-if="data.facts && data.facts.length > 0">
          <div
            v-for="fact in data.facts"
            :key="fact.id || fact.text"
            class="trail-item fact-item"
          >
            <span class="fact-text">{{ fact.text }}</span>
            <span v-if="fact.confidence" class="confidence-badge">
              {{ Math.round(fact.confidence * 100) }}%
            </span>
          </div>
        </div>
        <div v-else class="trail-item empty-item">No explicit facts recorded</div>
      </div>

      <div class="trail-connector">↓</div>

      <!-- Source chunks -->
      <div class="trail-level">
        <div class="level-label">Source Chunks</div>
        <div
          v-for="chunk in data.chunks"
          :key="chunk.id"
          class="trail-item chunk-item"
          :class="{ expanded: expandedChunk === chunk.id }"
          @click="toggleChunk(chunk.id)"
        >
          <div class="chunk-preview">{{ truncate(chunk.text, 120) }}</div>
          <div class="chunk-meta">
            <span class="relevance">Relevance: {{ chunk.score?.toFixed(3) }}</span>
            <span v-if="chunk.page" class="page">p. {{ chunk.page }}</span>
            <span class="expand-hint">{{ expandedChunk === chunk.id ? '▲ less' : '▼ more' }}</span>
          </div>
          <div v-if="expandedChunk === chunk.id" class="chunk-full">
            <p>{{ chunk.text }}</p>
            <button
              class="context-btn"
              @click.stop="loadContext(chunk.id)"
            >
              Show surrounding context
            </button>
          </div>

          <!-- Context window -->
          <div v-if="chunkContext[chunk.id]" class="chunk-context">
            <div
              v-for="ctx in chunkContext[chunk.id]"
              :key="ctx.id"
              :class="['ctx-chunk', { target: ctx.is_target }]"
            >
              {{ ctx.text }}
            </div>
          </div>
        </div>
      </div>

      <div class="trail-connector">↓</div>

      <!-- Documents -->
      <div class="trail-level">
        <div class="level-label">Documents</div>
        <div
          v-for="doc in data.documents"
          :key="doc.id"
          class="trail-item doc-item"
        >
          <div class="doc-title">{{ doc.title }}</div>
          <div v-if="doc.authors" class="doc-authors">{{ doc.authors }}</div>
          <div class="doc-meta">
            <span v-if="doc.year" class="doc-year">{{ doc.year }}</span>
            <a
              v-if="doc.url"
              :href="doc.url"
              target="_blank"
              rel="noopener noreferrer"
              class="doc-link"
            >
              View source →
            </a>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import api from '@/utils/api'

interface Fact {
  id?: string
  text: string
  confidence?: number
}

interface Chunk {
  id: string
  text: string
  score?: number
  page?: number
}

interface Document {
  id: string
  title: string
  authors?: string
  year?: number
  url?: string
}

interface ProvenanceData {
  citation_id: string
  answer?: { excerpt: string }
  facts: Fact[]
  chunks: Chunk[]
  documents: Document[]
}

interface ContextChunk {
  id: string
  text: string
  chunk_index?: number
  is_target: boolean
}

const props = defineProps<{
  citationId: string | null
}>()

defineEmits<{ (e: 'close'): void }>()

const data = ref<ProvenanceData | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const expandedChunk = ref<string | null>(null)
const chunkContext = ref<Record<string, ContextChunk[]>>({})

watch(
  () => props.citationId,
  async (id) => {
    if (!id) { data.value = null; return }
    loading.value = true
    error.value = null
    expandedChunk.value = null
    chunkContext.value = {}
    try {
      const { data: result } = await api.get(`/graph/provenance/${id}`)
      data.value = result
    } catch {
      error.value = 'Could not load provenance data.'
    } finally {
      loading.value = false
    }
  },
  { immediate: true }
)

function toggleChunk(chunkId: string) {
  expandedChunk.value = expandedChunk.value === chunkId ? null : chunkId
}

async function loadContext(chunkId: string) {
  if (chunkContext.value[chunkId]) return
  try {
    const { data: result } = await api.get(`/graph/chunk/${chunkId}/context?window=2`)
    chunkContext.value[chunkId] = result.context || []
  } catch {
    // ignore silently
  }
}

function truncate(text: string, max: number): string {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '…' : text
}
</script>

<style scoped>
.provenance-trail {
  height: 100%;
  display: flex;
  flex-direction: column;
  font-size: 0.85rem;
}

.trail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e5e7eb;
  font-weight: 600;
}

.close-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1rem;
  color: #6b7280;
  line-height: 1;
}

.loading,
.error-state {
  padding: 2rem;
  text-align: center;
  color: #6b7280;
}

.error-state { color: #ef4444; }

.trail-body {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.trail-level {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.level-label {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
  margin-bottom: 0.2rem;
}

.trail-connector {
  text-align: center;
  color: #d1d5db;
  font-size: 1.2rem;
  padding: 0.3rem 0;
}

.trail-item {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
}

.answer-item {
  font-style: italic;
  color: #374151;
}

.fact-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.5rem;
}

.fact-text { flex: 1; }

.confidence-badge {
  background: #dbeafe;
  color: #1e40af;
  border-radius: 9999px;
  padding: 0.1rem 0.4rem;
  font-size: 0.7rem;
  white-space: nowrap;
}

.empty-item { color: #9ca3af; font-style: italic; }

.chunk-item {
  cursor: pointer;
  transition: border-color 0.15s;
}

.chunk-item:hover { border-color: #93c5fd; }
.chunk-item.expanded { border-color: #3b82f6; }

.chunk-preview { color: #374151; }

.chunk-meta {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.3rem;
  color: #9ca3af;
  font-size: 0.75rem;
}

.expand-hint { margin-left: auto; }

.chunk-full {
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px dashed #e5e7eb;
  color: #374151;
  white-space: pre-wrap;
}

.context-btn {
  margin-top: 0.5rem;
  background: none;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
  cursor: pointer;
  color: #374151;
}

.chunk-context {
  margin-top: 0.5rem;
  border-top: 1px solid #e5e7eb;
  padding-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.ctx-chunk {
  padding: 0.3rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  color: #6b7280;
  background: #f3f4f6;
}

.ctx-chunk.target {
  background: #dbeafe;
  color: #1e3a8a;
  font-weight: 500;
}

.doc-item { display: flex; flex-direction: column; gap: 0.2rem; }

.doc-title { font-weight: 600; color: #111827; }
.doc-authors { color: #6b7280; font-size: 0.8rem; }

.doc-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.75rem;
}

.doc-year { color: #9ca3af; }

.doc-link {
  color: #2563eb;
  text-decoration: none;
}
.doc-link:hover { text-decoration: underline; }
</style>
