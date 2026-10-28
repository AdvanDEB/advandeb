<template>
  <div class="document-upload">
    <!-- Drop zone. The browse control is a real button; clicking anywhere in
         the zone is a mouse convenience on top of it. -->
    <div
      :class="['drop-zone', { dragging: isDragging }]"
      @drop.prevent="handleDrop"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @click="openPicker"
    >
      <input
        ref="fileInput"
        type="file"
        multiple
        :accept="ACCEPT"
        class="hidden-input"
        tabindex="-1"
        aria-hidden="true"
        data-testid="file-input"
        @click.stop
        @change="handleFileSelect"
      />
      <div class="drop-content">
        <span class="drop-icon" aria-hidden="true">📄</span>
        <p class="drop-text">
          Drag &amp; drop PDFs here, or
          <button type="button" class="browse-btn" @click.stop="openPicker">choose files</button>
        </p>
        <p class="drop-hint">
          PDF only. Each file is queued for ingestion — text, facts, embeddings —
          and appears in the library when processing finishes.
        </p>
      </div>
    </div>

    <!-- Upload queue -->
    <ul v-if="uploads.length > 0" class="upload-list" aria-label="Uploads">
      <li
        v-for="upload in uploads"
        :key="upload.id"
        :class="['upload-item', upload.status]"
      >
        <div class="upload-info">
          <span class="upload-name">{{ upload.filename }}</span>
          <span class="upload-size">{{ formatBytes(upload.size) }}</span>
        </div>

        <div class="upload-progress-row">
          <div
            class="progress-bar"
            role="progressbar"
            :aria-label="`Upload of ${upload.filename}`"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-valuenow="upload.progress"
          >
            <div class="progress-fill" :style="{ width: `${upload.progress}%` }"></div>
          </div>
          <span class="upload-status-text">{{ statusLabel(upload) }}</span>
        </div>

        <div v-if="upload.error" class="upload-error">{{ upload.error }}</div>
      </li>
    </ul>

    <!-- One polite announcement per state change, rather than making the
         whole list live and reading every progress tick aloud. -->
    <p class="sr-only" aria-live="polite">{{ announcement }}</p>

    <p v-if="anyQueued" class="follow-up">
      Track processing under
      <router-link to="/kb">Knowledge Builder → Ingestion</router-link>.
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useNotificationsStore } from '@/stores/notifications'
import { uploadPdf } from '@/utils/kbApi'
import { apiErrorMessage } from '@/utils/api'
import { formatBytes } from '@/utils/format'

const emit = defineEmits<{
  (e: 'uploaded', result: { filename: string; batchId: string; jobId: string }): void
}>()

type UploadStatus = 'uploading' | 'queued' | 'error'

interface Upload {
  id: string
  filename: string
  size: number
  progress: number
  status: UploadStatus
  error?: string
}

// The endpoint behind this (POST /api/kb/ingestion/upload, the same one the
// Knowledge Builder's Ingestion tab uses) runs the PDF pipeline only. This
// component used to offer TXT and DOCX and post to /api/documents/upload, which
// stored a review suggestion and nothing else, then call a /embed route that
// never existed — so every upload ended in "embedding trigger failed".
const ACCEPT = '.pdf,application/pdf'

const fileInput = ref<HTMLInputElement>()
const uploads = ref<Upload[]>([])
const isDragging = ref(false)
const announcement = ref('')
const notifs = useNotificationsStore()

const anyQueued = computed(() => uploads.value.some(u => u.status === 'queued'))

function openPicker() {
  fileInput.value?.click()
}

function handleDrop(event: DragEvent) {
  isDragging.value = false
  uploadFiles(Array.from(event.dataTransfer?.files || []))
}

function handleFileSelect(event: Event) {
  uploadFiles(Array.from((event.target as HTMLInputElement).files || []))
  // Reset so the same file can be chosen again
  if (fileInput.value) fileInput.value.value = ''
}

function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
}

function uploadFiles(files: File[]) {
  for (const file of files) {
    // Push first, then work on the reactive proxy from the array: mutating the
    // raw object would update nothing on screen.
    uploads.value.push({
      id: crypto.randomUUID(),
      filename: file.name,
      size: file.size,
      progress: 0,
      status: 'uploading',
    })
    const upload = uploads.value[uploads.value.length - 1]

    if (!isPdf(file)) {
      fail(upload, 'Only PDF files can be ingested.')
      continue
    }
    void doUpload(upload, file)
  }
}

function fail(upload: Upload, message: string) {
  upload.status = 'error'
  upload.error = message
  announcement.value = `${upload.filename}: upload failed. ${message}`
}

async function doUpload(upload: Upload, file: File) {
  try {
    // The shared client attaches the token and refreshes it on a 401, which
    // the old raw XHR did not — an expired session failed the upload outright.
    const result = await uploadPdf(file, undefined, {
      onProgress: (pct) => { upload.progress = pct },
      // Reported below, per file; the global toast would repeat it.
      skipErrorToast: true,
    })
    upload.progress = 100
    upload.status = 'queued'
    announcement.value = `${upload.filename} uploaded and queued for ingestion.`
    notifs.success(`${upload.filename} uploaded and queued for ingestion`)
    emit('uploaded', { filename: result.filename, batchId: result.batch_id, jobId: result.job_id })
  } catch (err) {
    const message = apiErrorMessage(err, 'Upload failed.')
    fail(upload, message)
    notifs.error(`Failed to upload ${upload.filename}: ${message}`)
  }
}

function statusLabel(upload: Upload): string {
  switch (upload.status) {
    case 'uploading': return `${upload.progress}%`
    case 'queued':    return 'Queued for ingestion'
    case 'error':     return 'Failed'
  }
}
</script>

<style scoped>
.document-upload {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.drop-zone {
  border: 2px dashed var(--app-line-2);
  border-radius: var(--app-radius-lg);
  padding: 2rem;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.drop-zone:hover,
.drop-zone.dragging {
  border-color: var(--app-primary);
  background: var(--app-primary-soft);
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
  color: var(--app-ink-2);
}

.browse-btn {
  background: none;
  border: 0;
  padding: 0.25rem 0.1rem;
  font: inherit;
  color: var(--app-primary-strong);
  text-decoration: underline;
  cursor: pointer;
  border-radius: var(--app-radius-sm);
}
.browse-btn:focus-visible { outline: var(--app-focus); outline-offset: 2px; }

.drop-hint {
  font-size: 0.78rem;
  color: var(--app-ink-3);
  max-width: 32rem;
}

.upload-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.upload-item {
  background: var(--app-bg-2);
  border: 1px solid var(--app-line);
  border-radius: var(--app-radius);
  padding: 0.6rem 0.75rem;
}

.upload-item.queued { border-color: var(--app-success-line); }
.upload-item.error  { border-color: var(--app-danger-line); }

.upload-info {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.82rem;
  margin-bottom: 0.35rem;
}

.upload-name {
  font-weight: 500;
  color: var(--app-ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.upload-size { color: var(--app-ink-4); flex-shrink: 0; }

.upload-progress-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.progress-bar {
  flex: 1;
  height: 6px;
  background: var(--app-line);
  border-radius: 9999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--app-primary);
  border-radius: 9999px;
  transition: width 0.2s;
}

.upload-item.queued .progress-fill { background: var(--app-success); }
.upload-item.error  .progress-fill { background: var(--app-danger); }

.upload-status-text {
  font-size: 0.75rem;
  color: var(--app-ink-3);
  white-space: nowrap;
}

.upload-error {
  font-size: 0.75rem;
  color: var(--app-danger);
  margin-top: 0.25rem;
}

.follow-up {
  font-size: 0.8rem;
  color: var(--app-ink-3);
}
.follow-up a { color: var(--app-primary-strong); }

@media (max-width: 480px) {
  .drop-zone { padding: 1.25rem 1rem; }
}
</style>
