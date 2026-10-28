<template>
  <div class="documents-view">
    <header class="page-header">
      <div class="header-left">
        <h1>Corpus</h1>
        <span class="subtitle">Knowledge base document library</span>
      </div>
      <button
        v-if="isCurator"
        type="button"
        class="upload-btn"
        :aria-expanded="showUpload"
        aria-controls="upload-section"
        @click="showUpload = !showUpload"
      >
        <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        {{ showUpload ? 'Hide upload' : 'Upload document' }}
      </button>
    </header>

    <div v-if="isCurator && showUpload" id="upload-section" class="upload-section">
      <DocumentUpload @uploaded="handleUploaded" />
    </div>

    <DocumentLibrary ref="libraryRef" :is-curator="isCurator" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { isCurator as userIsCurator } from '@/utils/access'
import DocumentUpload from '@/components/documents/DocumentUpload.vue'
import DocumentLibrary from '@/components/documents/DocumentLibrary.vue'

const auth = useAuthStore()
const isCurator = computed(
  () => userIsCurator(auth.user),
)

const showUpload = ref(false)
const libraryRef = ref<InstanceType<typeof DocumentLibrary>>()

// The panel stays open: with several files in flight, closing it on the first
// success hid the progress of the rest.
function handleUploaded() {
  libraryRef.value?.fetchDocuments()
}
</script>

<style scoped>
.documents-view {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  height: 100%;
  min-height: 0;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.page-header h1 {
  font-size: 1.4rem;
  font-weight: 700;
  color: #111827;
  line-height: 1.2;
}

.subtitle {
  font-size: 0.8rem;
  color: #9ca3af;
}

.upload-btn {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.45rem 1rem;
  font-size: 0.875rem;
  cursor: pointer;
  white-space: nowrap;
}
.upload-btn:hover { background: #2563eb; }

.upload-section {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 1.25rem;
  flex-shrink: 0;
}

@media (max-width: 720px) {
  .documents-view { padding: 1rem; gap: 1rem; }
  .page-header { flex-wrap: wrap; gap: 0.75rem; }
  .upload-section { padding: 1rem; }
}

@media (pointer: coarse) {
  .upload-btn { min-height: var(--app-touch); }
}
</style>
