<template>
  <Transition name="slide-in">
    <aside v-if="node" class="node-inspector">
      <div class="inspector-header">
        <span class="type-badge" :class="`type-${node.node_type.replace(/_/g, '-')}`">
          {{ node.node_type.replace(/_/g, ' ') }}
        </span>
        <button class="close-btn" @click="$emit('close')" title="Close">✕</button>
      </div>

      <div class="inspector-body">

        <!-- ── Document node: rich layout (metadata fetched from DB) ──── -->
        <template v-if="node.node_type === 'document' || node.node_type === 'external_document'">

          <!-- Loading state -->
          <div v-if="metaLoading" class="meta-loading">
            <span class="loading-dot" />
            <span class="loading-dot" />
            <span class="loading-dot" />
          </div>

          <!-- Error state -->
          <p v-else-if="metaError" class="meta-error">{{ metaError }}</p>

          <template v-else>
            <!-- Title (prominent heading) -->
            <h3 v-if="docMeta?.title" class="doc-title">{{ docMeta.title }}</h3>
            <h3 v-else class="node-label">{{ node.label }}</h3>

            <!-- Source file (muted, below title) -->
            <p v-if="node.label && docMeta?.title && node.label !== docMeta.title"
               class="source-file">{{ node.label }}</p>

            <!-- Not-in-DB notice for external documents -->
            <p v-if="node.node_type === 'external_document' && !docMeta" class="not-in-db">
              External citation — not in knowledge base
            </p>

            <dl v-if="docMeta" class="prop-list">
              <!-- Retraction warning — shown at the top if retracted -->
              <div v-if="docMeta.is_retracted" class="prop-row">
                <dt></dt>
                <dd><span class="retracted-badge">RETRACTED</span></dd>
              </div>
              <div v-if="docMeta.authors && docMeta.authors.length" class="prop-row">
                <dt>Authors</dt>
                <dd>{{ docMeta.authors.join(', ') }}</dd>
              </div>
              <div v-if="docMeta.year" class="prop-row">
                <dt>Year</dt>
                <dd>{{ docMeta.year }}</dd>
              </div>
              <div v-if="docMeta.doi" class="prop-row">
                <dt>DOI</dt>
                <dd>
                  <a :href="`https://doi.org/${docMeta.doi}`" target="_blank" rel="noopener"
                     class="doi-link">{{ docMeta.doi }}</a>
                </dd>
              </div>
              <div v-if="docMeta.isbn" class="prop-row">
                <dt>ISBN</dt>
                <dd>{{ docMeta.isbn }}</dd>
              </div>
              <div v-if="docMeta.journal" class="prop-row">
                <dt>Journal</dt>
                <dd>{{ docMeta.journal }}</dd>
              </div>
              <div v-if="docMeta.volume || docMeta.issue || docMeta.pages" class="prop-row">
                <dt>Vol/Issue/Pages</dt>
                <dd>
                  <span v-if="docMeta.volume">Vol. {{ docMeta.volume }}</span>
                  <span v-if="docMeta.issue"> · Issue {{ docMeta.issue }}</span>
                  <span v-if="docMeta.pages"> · pp. {{ docMeta.pages }}</span>
                </dd>
              </div>
              <div v-if="docMeta.cited_by_count != null" class="prop-row">
                <dt>Citations</dt>
                <dd>{{ docMeta.cited_by_count.toLocaleString() }}</dd>
              </div>
              <div v-if="docMeta.openalex_id" class="prop-row">
                <dt>OpenAlex</dt>
                <dd>
                  <a :href="`https://openalex.org/${docMeta.openalex_id}`" target="_blank" rel="noopener"
                     class="doi-link">{{ docMeta.openalex_id }}</a>
                </dd>
              </div>
              <div v-if="docMeta.pmid" class="prop-row">
                <dt>PubMed</dt>
                <dd>
                  <a :href="`https://pubmed.ncbi.nlm.nih.gov/${docMeta.pmid}`" target="_blank" rel="noopener"
                     class="doi-link">{{ docMeta.pmid }}</a>
                </dd>
              </div>
              <div v-if="docMeta.general_domain" class="prop-row">
                <dt>Domain</dt>
                <dd>{{ docMeta.general_domain }}</dd>
              </div>
              <div v-if="node.degree !== undefined" class="prop-row">
                <dt>Degree</dt>
                <dd>{{ node.degree }}</dd>
              </div>
              <div v-if="docMeta.processing_status" class="prop-row">
                <dt>Status</dt>
                <dd><span class="status-pill" :class="`status-${docMeta.processing_status}`">{{ docMeta.processing_status }}</span></dd>
              </div>
            </dl>

            <!-- DOI-only display for external_document with no DB record -->
            <dl v-else class="prop-list">
              <div v-if="node.properties.doi" class="prop-row">
                <dt>DOI</dt>
                <dd>
                  <a :href="`https://doi.org/${node.properties.doi}`" target="_blank" rel="noopener"
                     class="doi-link">{{ node.properties.doi as string }}</a>
                </dd>
              </div>
              <div v-if="node.degree !== undefined" class="prop-row">
                <dt>Degree</dt>
                <dd>{{ node.degree }}</dd>
              </div>
              <div v-if="node.properties.internal !== undefined" class="prop-row">
                <dt>Citation type</dt>
                <dd>{{ node.properties.internal ? 'Internal' : 'External (not in DB)' }}</dd>
              </div>
            </dl>

            <!-- Keywords as pills -->
            <div v-if="docMeta && docKeywords.length" class="keyword-block">
              <div class="content-label">Keywords</div>
              <div class="keyword-pills">
                <span v-for="kw in docKeywords" :key="kw" class="kw-pill">{{ kw }}</span>
              </div>
            </div>

            <!-- Abstract (collapsible) -->
            <div v-if="docMeta?.abstract" class="abstract-block">
              <button class="abstract-toggle" @click="abstractOpen = !abstractOpen">
                <span class="content-label" style="margin:0">Abstract</span>
                <span class="toggle-icon">{{ abstractOpen ? '▾' : '▸' }}</span>
              </button>
              <p v-if="abstractOpen" class="abstract-text">{{ docMeta.abstract }}</p>
            </div>
          </template>

        </template>

        <!-- ── All other node types: generic layout ───────────────────── -->
        <template v-else>
          <h3 class="node-label">{{ node.label }}</h3>

          <dl class="prop-list">
            <div v-if="node.degree !== undefined" class="prop-row">
              <dt>Degree</dt>
              <dd>{{ node.degree }}</dd>
            </div>
            <div v-if="node.properties.doi" class="prop-row">
              <dt>DOI</dt>
              <dd class="mono">{{ node.properties.doi }}</dd>
            </div>
            <div v-if="node.properties.year" class="prop-row">
              <dt>Year</dt>
              <dd>{{ node.properties.year }}</dd>
            </div>
            <div v-if="node.properties.journal" class="prop-row">
              <dt>Journal</dt>
              <dd>{{ node.properties.journal }}</dd>
            </div>
            <div v-if="node.properties.authors && (node.properties.authors as string[]).length" class="prop-row">
              <dt>Authors</dt>
              <dd>{{ (node.properties.authors as string[]).join(', ') }}</dd>
            </div>
            <div v-if="node.properties.rank" class="prop-row">
              <dt>Rank</dt>
              <dd>{{ node.properties.rank }}</dd>
            </div>
            <div v-if="node.properties.tax_id" class="prop-row">
              <dt>NCBI Tax ID</dt>
              <dd class="mono">{{ node.properties.tax_id }}</dd>
            </div>
            <div v-if="node.properties.common_names && (node.properties.common_names as string[]).length" class="prop-row">
              <dt>Common names</dt>
              <dd>{{ (node.properties.common_names as string[]).join(', ') }}</dd>
            </div>
            <div v-if="node.properties.confidence !== undefined" class="prop-row">
              <dt>Confidence</dt>
              <dd>{{ (node.properties.confidence as number).toFixed(2) }}</dd>
            </div>
            <div v-if="node.properties.status" class="prop-row">
              <dt>Status</dt>
              <dd><span class="status-pill" :class="`status-${node.properties.status}`">{{ node.properties.status }}</span></dd>
            </div>
            <div v-if="node.properties.category" class="prop-row">
              <dt>Category</dt>
              <dd>{{ node.properties.category }}</dd>
            </div>
            <div v-if="node.properties.internal !== undefined" class="prop-row">
              <dt>Citation type</dt>
              <dd>{{ node.properties.internal ? 'Internal' : 'External (not in DB)' }}</dd>
            </div>
          </dl>

          <!-- Full text content for facts -->
          <div v-if="node.node_type === 'fact' || node.node_type === 'stylized_fact'" class="content-block">
            <div class="content-label">Statement</div>
            <p class="content-text">{{ node.label }}</p>
          </div>
        </template>

        <div class="inspector-actions">
          <button class="action-btn" :disabled="loading" @click="$emit('expand', node)">
            {{ loading ? 'Loading…' : 'Expand neighbors' }}
          </button>
        </div>
      </div>
    </aside>
  </Transition>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { GraphNode } from '@/utils/kbApi'
import { fetchKbDocument, type KbDocumentMeta } from '@/utils/kbApi'

const props = defineProps<{ node: GraphNode | null; loading?: boolean }>()
defineEmits<{
  (e: 'close'): void
  (e: 'expand', node: GraphNode): void
}>()

const abstractOpen = ref(false)
const metaLoading = ref(false)
const metaError = ref<string | null>(null)
const docMeta = ref<KbDocumentMeta | null>(null)

// Fetch document metadata from the DB whenever a document node is selected.
// entity_id is the MongoDB ObjectId string of the document record.
watch(
  () => props.node,
  async (node) => {
    abstractOpen.value = false
    docMeta.value = null
    metaError.value = null

    if (!node) return
    if (node.node_type !== 'document' && node.node_type !== 'external_document') return

    // entity_id is the document's MongoDB _id
    const entityId = node.entity_id
    if (!entityId) return

    metaLoading.value = true
    try {
      docMeta.value = await fetchKbDocument(entityId)
    } catch (err: any) {
      console.error('[NodeInspector] failed to load document metadata', entityId, err)
      metaError.value = `Failed to load metadata (${err?.response?.status ?? err?.message ?? 'unknown error'})`
    } finally {
      metaLoading.value = false
    }
  },
  { immediate: true },
)

const docKeywords = computed<string[]>(() => {
  const kw = docMeta.value?.keywords
  if (!kw) return []
  if (Array.isArray(kw)) return (kw as string[]).filter(Boolean)
  if (typeof kw === 'string') return (kw as string).split(/[,;]/).map(s => s.trim()).filter(Boolean)
  return []
})
</script>

<style scoped>
.node-inspector {
  width: 300px;
  flex-shrink: 0;
  background: #1e293b;
  border-left: 1px solid #334155;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 100%;
}

.inspector-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #334155;
}

.type-badge {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  background: #334155;
  color: #94a3b8;
}
.type-badge.type-document          { background: #1d4ed8; color: #bfdbfe; }
.type-badge.type-external-document { background: #334155; color: #94a3b8; }
.type-badge.type-fact              { background: #065f46; color: #6ee7b7; }
.type-badge.type-stylized-fact     { background: #78350f; color: #fde68a; }
.type-badge.type-taxon,
.type-badge.type-species,
.type-badge.type-genus,
.type-badge.type-family,
.type-badge.type-order,
.type-badge.type-class             { background: #4c1d95; color: #ddd6fe; }
.type-badge.type-phylum            { background: #7c2d12; color: #fed7aa; }
.type-badge.type-kingdom           { background: #7f1d1d; color: #fca5a5; }

.close-btn {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0.2rem 0.3rem;
  border-radius: 4px;
  line-height: 1;
}
.close-btn:hover { background: #334155; color: #e2e8f0; }

.inspector-body {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

/* Loading dots */
.meta-loading {
  display: flex;
  gap: 0.35rem;
  padding: 0.5rem 0;
  align-items: center;
}
.loading-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #475569;
  animation: pulse 1.2s ease-in-out infinite;
}
.loading-dot:nth-child(2) { animation-delay: 0.2s; }
.loading-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* Not-in-DB notice */
.not-in-db {
  font-size: 0.72rem;
  color: #64748b;
  font-style: italic;
  margin: 0;
}

/* Metadata fetch error */
.meta-error {
  font-size: 0.72rem;
  color: #fca5a5;
  margin: 0;
}

/* Document title (prominent) */
.doc-title {
  font-size: 0.88rem;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0;
  line-height: 1.45;
  word-break: break-word;
}

/* Source filename (muted, below title) */
.source-file {
  font-size: 0.68rem;
  color: #475569;
  margin: 0;
  word-break: break-all;
  line-height: 1.4;
}

.node-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0;
  line-height: 1.4;
  word-break: break-word;
}

.prop-list { margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.prop-row { display: flex; gap: 0.5rem; align-items: baseline; }
.prop-row dt { font-size: 0.7rem; color: #64748b; min-width: 80px; flex-shrink: 0; font-weight: 500; }
.prop-row dd { font-size: 0.75rem; color: #cbd5e1; margin: 0; word-break: break-word; }
.mono { font-family: monospace; font-size: 0.7rem !important; }

.doi-link {
  color: #60a5fa;
  font-size: 0.72rem;
  text-decoration: none;
  word-break: break-all;
}
.doi-link:hover { text-decoration: underline; }

/* Keywords */
.keyword-block { display: flex; flex-direction: column; gap: 0.4rem; }
.keyword-pills { display: flex; flex-wrap: wrap; gap: 0.3rem; }
.kw-pill {
  font-size: 0.62rem;
  padding: 0.15rem 0.45rem;
  border-radius: 99px;
  background: #1e3a5f;
  color: #93c5fd;
  border: 1px solid #2563eb44;
  white-space: nowrap;
}

/* Abstract */
.abstract-block { display: flex; flex-direction: column; gap: 0.35rem; }
.abstract-toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  width: 100%;
  text-align: left;
}
.toggle-icon { font-size: 0.65rem; color: #64748b; flex-shrink: 0; }
.abstract-text {
  font-size: 0.74rem;
  color: #94a3b8;
  line-height: 1.55;
  margin: 0;
  word-break: break-word;
}

.status-pill {
  font-size: 0.65rem;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-weight: 600;
}
.status-completed, .status-confirmed, .status-published { background: #065f46; color: #6ee7b7; }
.status-pending, .status-suggested { background: #78350f; color: #fde68a; }
.status-failed, .status-rejected { background: #7f1d1d; color: #fca5a5; }

.retracted-badge {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 0.15rem 0.5rem;
  border-radius: 3px;
  background: #7f1d1d;
  color: #fca5a5;
  border: 1px solid #ef4444;
  text-transform: uppercase;
}

.content-block { display: flex; flex-direction: column; gap: 0.3rem; }
.content-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; font-weight: 600; }
.content-text { font-size: 0.78rem; color: #cbd5e1; line-height: 1.5; margin: 0; }

.inspector-actions { margin-top: auto; padding-top: 0.5rem; border-top: 1px solid #334155; }
.action-btn {
  width: 100%;
  padding: 0.5rem;
  background: #334155;
  border: none;
  border-radius: 6px;
  color: #e2e8f0;
  font-size: 0.75rem;
  cursor: pointer;
  text-align: center;
}
.action-btn:hover { background: #3b82f6; }
.action-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.action-btn:disabled:hover { background: #334155; }

/* Transition */
.slide-in-enter-active, .slide-in-leave-active { transition: width 0.2s ease, opacity 0.2s ease; overflow: hidden; }
.slide-in-enter-from, .slide-in-leave-to { width: 0; opacity: 0; }
.slide-in-enter-to, .slide-in-leave-from { width: 300px; opacity: 1; }
</style>
