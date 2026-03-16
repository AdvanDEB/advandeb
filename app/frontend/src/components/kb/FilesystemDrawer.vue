<template>
  <div class="drawer-content">
    <div class="drawer-header">
      <span class="drawer-title">📁 Filesystem</span>
      <div class="path-bar">
        <input
          v-model="pathInput"
          class="path-input"
          placeholder="~/dev/advandeb_auxiliary"
          @keydown.enter="browse(pathInput)"
        />
        <button class="browse-btn" @click="browse(pathInput)">Browse</button>
      </div>
    </div>
    <div class="fs-body">
      <div v-if="loading" class="status">Loading…</div>
      <div v-else-if="error" class="status error">{{ error }}</div>
      <div v-else>
        <div v-if="parent" class="entry dir" @click="browse(parent)">
          <span class="icon">📁</span>
          <span class="name">..</span>
        </div>
        <div
          v-for="entry in entries"
          :key="entry.path"
          class="entry"
          :class="entry.type"
          @click="entry.type === 'dir' ? browse(entry.path) : null"
        >
          <span class="icon">{{ entry.type === 'dir' ? '📁' : '📄' }}</span>
          <span class="name">{{ entry.name }}</span>
          <span v-if="entry.type === 'file' && entry.size != null" class="size">{{ fmtSize(entry.size) }}</span>
        </div>
        <div v-if="!entries.length" class="status muted">Empty directory</div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { fsAPI } from '@/utils/kbApi'

const DEFAULT_PATH = '~/dev/advandeb_auxiliary'

export default {
  name: 'FilesystemDrawer',
  setup() {
    const pathInput = ref(DEFAULT_PATH)
    const currentPath = ref('')
    const parent = ref(null)
    const entries = ref([])
    const loading = ref(false)
    const error = ref('')

    onMounted(() => browse(DEFAULT_PATH))

    async function browse(path) {
      loading.value = true
      error.value = ''
      try {
        const res = await fsAPI.browse(path)
        const data = res.data
        currentPath.value = data.path
        parent.value = data.parent
        entries.value = data.entries
        pathInput.value = data.path
      } catch (e) {
        error.value = e.response?.data?.detail || e.message
      } finally {
        loading.value = false
      }
    }

    function fmtSize(bytes) {
      if (bytes === null || bytes === undefined) return ''
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
    }

    return { pathInput, currentPath, parent, entries, loading, error, browse, fmtSize }
  },
}
</script>

<style scoped>
.drawer-content {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.drawer-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid #e0e0e0;
  background: #f8f9fa;
  flex-shrink: 0;
}

.drawer-title { font-weight: 600; font-size: 14px; flex-shrink: 0; }

.path-bar { display: flex; gap: 6px; flex: 1; }

.path-input {
  flex: 1;
  padding: 5px 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 12px;
  font-family: monospace;
}

.browse-btn {
  padding: 5px 12px;
  background: #4a90e2;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.browse-btn:hover { background: #357abd; }

.fs-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.status { padding: 10px 16px; color: #888; font-size: 13px; }
.status.error { color: #e74c3c; }
.status.muted { color: #bbb; }

.entry {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 16px;
  font-size: 13px;
  border-bottom: 1px solid #f5f5f5;
}

.entry.dir {
  cursor: pointer;
}

.entry.dir:hover { background: #f0f4ff; }

.icon { font-size: 14px; flex-shrink: 0; }

.name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #333;
}

.entry.dir .name { color: #1a56db; font-weight: 500; }

.size {
  color: #999;
  font-size: 11px;
  flex-shrink: 0;
}
</style>
