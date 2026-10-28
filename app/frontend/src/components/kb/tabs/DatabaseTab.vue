<template>
  <div class="tab-content database-tab" role="tabpanel" aria-label="Database">
    <div class="tab-inner">
      <div class="section-header">
        <!-- The endpoint inspects ArangoDB, not MongoDB. Naming the wrong
             store matters in a codebase mid-migration where both exist. -->
        <h2>ArangoDB Collections</h2>
        <button type="button" class="btn primary" :disabled="collectionsLoading" @click="loadCollections">
          {{ collectionsLoading ? 'Loading…' : 'Refresh' }}
        </button>
      </div>

      <div v-if="collectionsLoading && !collections.length" class="empty-state">Loading collections…</div>
      <div v-else-if="!collections.length" class="empty-state">
        No collections loaded — click Refresh
      </div>
      <div v-else class="collections-grid">
        <button
          v-for="c in collections"
          :key="c.name"
          type="button"
          :class="['coll-card', { active: selectedCollection === c.name }]"
          :aria-pressed="selectedCollection === c.name"
          @click="loadCollectionDocs(c.name)"
        >
          <span class="coll-name">{{ c.name }}</span>
          <span class="coll-count">{{ formatCount(c.count) }}</span>
        </button>
      </div>

      <div v-if="docsLoading" class="empty-state">Loading documents…</div>
      <div v-else-if="selectedCollection && !collectionDocs.length" class="empty-state">
        {{ selectedCollection }} is empty
      </div>
      <div v-else-if="collectionDocs.length">
        <h3 class="subsection-title">{{ selectedCollection }} <span class="dim">(first 20)</span></h3>
        <div class="doc-list">
          <pre v-for="(doc, i) in collectionDocs" :key="i" class="doc-pre">{{ previewDoc(doc) }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { fetchCollections, fetchCollectionDocs } from '@/utils/kbApi'
import type { CollectionInfo } from '@/utils/kbApi'
import { useKnowledgeBuilderStore } from '@/stores/knowledgeBuilder'
import { formatCount } from '@/utils/format'

const kb = useKnowledgeBuilderStore()
const { activeTab } = storeToRefs(kb)
const { setError } = kb

const collections        = ref<CollectionInfo[]>([])
const selectedCollection = ref<string | null>(null)
const collectionDocs     = ref<unknown[]>([])

const collectionsLoading = ref(false)
const docsLoading        = ref(false)

/** Preview limit per document in the browser — long enough to identify a record. */
const DOC_PREVIEW_CHARS = 500

/**
 * Truncated JSON preview that says it was truncated.
 *
 * Slicing pretty-printed JSON leaves output that looks like malformed data —
 * a dangling key, an unclosed brace — with nothing to signal it was cut.
 */
function previewDoc(doc: unknown): string {
  const full = JSON.stringify(doc, null, 2)
  if (full.length <= DOC_PREVIEW_CHARS) return full
  return `${full.slice(0, DOC_PREVIEW_CHARS)}\n… (${formatCount(full.length - DOC_PREVIEW_CHARS)} more characters)`
}

async function loadCollections() {
  collectionsLoading.value = true
  try { collections.value = await fetchCollections() }
  catch (e) { setError(e) }
  finally { collectionsLoading.value = false }
}

async function loadCollectionDocs(name: string) {
  selectedCollection.value = name
  docsLoading.value = true
  // Clear first so a slow load can't show the previous collection's rows under
  // the new collection's heading.
  collectionDocs.value = []
  try { collectionDocs.value = await fetchCollectionDocs(name) }
  catch (e) { setError(e) }
  finally { docsLoading.value = false }
}

// Collections load the first time the tab is shown.
watch(activeTab, (tab) => {
  if (tab === 'database' && !collections.value.length) loadCollections()
}, { immediate: true })
</script>

<style scoped>
.tab-content { flex: 1; min-height: 0; overflow: hidden; }

.tab-inner {
  padding: 1.5rem;
  /* Was max-width:1200px with no auto margin, so every non-graph tab hugged the
     left edge and left a dead column on the right — while table cells truncated. */
  max-width: 1600px;
  margin-inline: auto;
  width: 100%;
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.section-header h2 { font-size: 1rem; font-weight: 600; color: #e2e8f0; margin: 0; }

.btn {
  padding: 0.35rem 0.75rem;
  border-radius: 5px;
  border: 1px solid #334155;
  background: #1e293b;
  color: #cbd5e1;
  font-size: 0.75rem;
  cursor: pointer;
  white-space: nowrap;
}
.btn:hover { background: #334155; }
.btn.primary { background: #1d4ed8; border-color: var(--app-primary); color: white; }
.btn.primary:hover { background: var(--app-primary-strong); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

.empty-state { padding: 2rem; text-align: center; color: #475569; font-size: 0.85rem; }

.subsection-title { font-size: 0.85rem; font-weight: 600; color: #94a3b8; margin: 0; }

.collections-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.5rem;
}

.coll-card {
  /* Now a <button> so it is reachable and activatable by keyboard — as a
     clickable <div> it was mouse-only. Needs the button defaults reset. */
  font: inherit;
  text-align: left;
  padding: 0.6rem 0.75rem;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.coll-card:hover { border-color: var(--app-primary); }
.coll-card:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }
.coll-card.active { border-color: #60a5fa; background: #1e3a5f; }
.coll-name { font-size: 0.75rem; color: #e2e8f0; font-weight: 500; }
.coll-count { font-size: 0.7rem; color: #64748b; }

.doc-list { display: flex; flex-direction: column; gap: 0.5rem; }
.doc-pre {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 0.75rem;
  font-size: 0.65rem;
  color: #94a3b8;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.dim { color: #475569; }

/* ---- Narrow screens ---------------------------------------------------------- */
@media (max-width: 768px) {
  .tab-inner { padding: 1rem; }
  .section-header { flex-wrap: wrap; gap: 0.5rem 1rem; }
  .collections-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
}

@media (pointer: coarse) {
  .btn { min-height: var(--app-touch); }
}
</style>
