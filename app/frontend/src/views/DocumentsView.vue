<template>
  <div class="documents-view">
    <header class="page-header">
      <h1>Documents</h1>
      <button class="toggle-upload-btn" @click="showUpload = !showUpload">
        {{ showUpload ? 'Hide upload' : '+ Upload' }}
      </button>
    </header>

    <div v-if="showUpload" class="upload-section">
      <DocumentUpload @uploaded="handleUploaded" />
    </div>

    <DocumentLibrary ref="libraryRef" @open="handleOpenDoc" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import DocumentUpload from '@/components/documents/DocumentUpload.vue'
import DocumentLibrary from '@/components/documents/DocumentLibrary.vue'

const showUpload = ref(false)
const libraryRef = ref<InstanceType<typeof DocumentLibrary>>()

function handleUploaded(_docId: string) {
  showUpload.value = false
  libraryRef.value?.fetchDocuments()
}

function handleOpenDoc(doc: any) {
  // TODO Week 11: open document viewer / PDF preview
  console.log('Open doc', doc)
}
</script>

<style scoped>
.documents-view {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  max-width: 1200px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.page-header h1 {
  font-size: 1.5rem;
  font-weight: 700;
  color: #111827;
}

.toggle-upload-btn {
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.4rem 1rem;
  font-size: 0.875rem;
  cursor: pointer;
}

.toggle-upload-btn:hover { background: #2563eb; }

.upload-section {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 1.25rem;
}
</style>
