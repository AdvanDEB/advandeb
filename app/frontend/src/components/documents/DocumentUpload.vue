<template>
  <div class="document-upload">
    <!-- Drop zone -->
    <div
      :class="['drop-zone', { dragging: isDragging }]"
      @drop.prevent="handleDrop"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @click="fileInput?.click()"
    >
      <input
        ref="fileInput"
        type="file"
        multiple
        accept=".pdf,.txt,.docx"
        class="hidden-input"
        @change="handleFileSelect"
      />
      <div class="drop-content">
        <span class="drop-icon">📄</span>
        <p class="drop-text">Drag & drop PDFs here, or <span class="browse-link">browse</span></p>
        <p class="drop-hint">Supports PDF, TXT, DOCX</p>
      </div>
    </div>

    <!-- Upload queue -->
    <div v-if="uploads.length > 0" class="upload-list">
      <div
        v-for="upload in uploads"
        :key="upload.id"
        :class="['upload-item', upload.status]"
      >
        <div class="upload-info">
          <span class="upload-name">{{ upload.filename }}</span>
          <span class="upload-size">{{ formatSize(upload.size) }}</span>
        </div>

        <div class="upload-progress-row">
          <div class="progress-bar">
            <div
              class="progress-fill"
              :style="{ width: `${upload.progress}%` }"
            ></div>
          </div>
          <span class="upload-status-text">{{ statusLabel(upload) }}</span>
        </div>

        <div v-if="upload.error" class="upload-error">{{ upload.error }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useNotificationsStore } from '@/stores/notifications'

const emit = defineEmits<{
  (e: 'uploaded', documentId: string): void
}>()

interface Upload {
  id: string
  filename: string
  size: number
  progress: number
  status: 'queued' | 'uploading' | 'embedding' | 'done' | 'error'
  error?: string
  documentId?: string
}

const fileInput = ref<HTMLInputElement>()
const uploads = ref<Upload[]>([])
const isDragging = ref(false)
const notifs = useNotificationsStore()

function handleDrop(event: DragEvent) {
  isDragging.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  uploadFiles(files)
}

function handleFileSelect(event: Event) {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  uploadFiles(files)
  // Reset so same file can be re-uploaded
  if (fileInput.value) fileInput.value.value = ''
}

function uploadFiles(files: File[]) {
  for (const file of files) {
    const upload: Upload = {
      id: crypto.randomUUID(),
      filename: file.name,
      size: file.size,
      progress: 0,
      status: 'uploading',
    }
    uploads.value.push(upload)
    doUpload(upload, file)
  }
}

function doUpload(upload: Upload, file: File) {
  const token = localStorage.getItem('access_token')
  const formData = new FormData()
  formData.append('file', file)

  const xhr = new XMLHttpRequest()

  xhr.upload.addEventListener('progress', (e) => {
    if (e.lengthComputable) {
      upload.progress = Math.round((e.loaded / e.total) * 90) // leave 10% for embed
    }
  })

  xhr.addEventListener('load', async () => {
    if (xhr.status >= 200 && xhr.status < 300) {
      try {
        const data = JSON.parse(xhr.responseText)
        upload.documentId = data._id || data.id
        upload.status = 'embedding'
        upload.progress = 90
        await triggerEmbed(upload)
      } catch {
        upload.status = 'error'
        upload.error = 'Upload succeeded but response was unreadable.'
      }
    } else {
      upload.status = 'error'
      upload.error = `Upload failed (HTTP ${xhr.status})`
      notifs.error(`Failed to upload ${upload.filename}`)
    }
  })

  xhr.addEventListener('error', () => {
    upload.status = 'error'
    upload.error = 'Network error during upload.'
    notifs.error(`Network error uploading ${upload.filename}`)
  })

  xhr.open('POST', '/api/documents/upload')
  if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
  xhr.send(formData)
}

async function triggerEmbed(upload: Upload) {
  if (!upload.documentId) return
  const token = localStorage.getItem('access_token')

  try {
    const response = await fetch(`/api/documents/${upload.documentId}/embed`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })

    if (response.ok) {
      upload.status = 'done'
      upload.progress = 100
      notifs.success(`${upload.filename} uploaded and queued for embedding`)
      emit('uploaded', upload.documentId!)
    } else {
      upload.status = 'error'
      upload.error = 'Upload succeeded but embedding trigger failed.'
    }
  } catch {
    upload.status = 'error'
    upload.error = 'Upload succeeded but embedding trigger failed.'
  }
}

function statusLabel(upload: Upload): string {
  switch (upload.status) {
    case 'uploading':  return `${upload.progress}%`
    case 'embedding':  return 'Queuing embedding…'
    case 'done':       return 'Done'
    case 'error':      return 'Error'
    default:           return 'Queued'
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<style scoped>
.document-upload {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.drop-zone {
  border: 2px dashed #d1d5db;
  border-radius: 8px;
  padding: 2rem;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.drop-zone:hover,
.drop-zone.dragging {
  border-color: #3b82f6;
  background: #eff6ff;
}

.hidden-input { display: none; }

.drop-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
}

.drop-icon { font-size: 2.5rem; }

.drop-text {
  font-size: 0.9rem;
  color: #374151;
}

.browse-link {
  color: #3b82f6;
  text-decoration: underline;
}

.drop-hint {
  font-size: 0.78rem;
  color: #9ca3af;
}

.upload-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.upload-item {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 0.6rem 0.75rem;
}

.upload-item.done   { border-color: #86efac; }
.upload-item.error  { border-color: #fca5a5; }

.upload-info {
  display: flex;
  justify-content: space-between;
  font-size: 0.82rem;
  margin-bottom: 0.35rem;
}

.upload-name {
  font-weight: 500;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 70%;
}

.upload-size { color: #9ca3af; }

.upload-progress-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.progress-bar {
  flex: 1;
  height: 6px;
  background: #e5e7eb;
  border-radius: 9999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #3b82f6;
  border-radius: 9999px;
  transition: width 0.2s;
}

.upload-item.done   .progress-fill { background: #22c55e; }
.upload-item.error  .progress-fill { background: #ef4444; }

.upload-status-text {
  font-size: 0.75rem;
  color: #6b7280;
  white-space: nowrap;
}

.upload-error {
  font-size: 0.75rem;
  color: #dc2626;
  margin-top: 0.25rem;
}
</style>
