<template>
  <div class="drawer-content">
    <div class="drawer-header">
      <span class="drawer-title">⬡ Database Inspector</span>
    </div>
    <div class="db-layout">
      <!-- Collection list -->
      <div class="collection-list">
        <div v-if="collectionsLoading" class="status">Loading…</div>
        <div
          v-for="col in collections"
          :key="col.name"
          class="collection-item"
          :class="{ active: selectedCollection === col.name }"
          @click="selectCollection(col.name)"
        >
          <span class="col-name">{{ col.name }}</span>
          <span class="col-count">{{ col.count.toLocaleString() }}</span>
        </div>
      </div>

      <!-- Document viewer -->
      <div class="doc-viewer">
        <div v-if="!selectedCollection" class="status muted">Select a collection</div>
        <div v-else-if="docsLoading" class="status">Loading…</div>
        <div v-else>
          <div class="doc-header">
            <span>{{ selectedCollection }} — {{ docs.length }} sample docs</span>
            <button class="load-more-btn" @click="loadDocs(true)">↻ Refresh</button>
          </div>
          <div v-for="(doc, i) in docs" :key="i" class="doc-item">
            <div class="doc-toggle" @click="toggleDoc(i)">
              <span>{{ expanded[i] ? '▼' : '▶' }}</span>
              <span class="doc-id">{{ doc._id || `doc ${i + 1}` }}</span>
            </div>
            <pre v-if="expanded[i]" class="doc-json">{{ fmtDoc(doc) }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, reactive, onMounted } from 'vue'
import { dbAPI } from '@/utils/kbApi'

export default {
  name: 'DatabaseDrawer',
  setup() {
    const collections = ref([])
    const collectionsLoading = ref(false)
    const selectedCollection = ref('')
    const docs = ref([])
    const docsLoading = ref(false)
    const expanded = reactive({})

    onMounted(async () => {
      collectionsLoading.value = true
      try {
        const res = await dbAPI.listCollections()
        collections.value = res.data
      } catch (_) {
        collections.value = []
      } finally {
        collectionsLoading.value = false
      }
    })

    async function selectCollection(name) {
      selectedCollection.value = name
      Object.keys(expanded).forEach(k => delete expanded[k])
      await loadDocs()
    }

    async function loadDocs(refresh = false) {
      if (!selectedCollection.value) return
      docsLoading.value = true
      try {
        const res = await dbAPI.getCollectionDocs(selectedCollection.value, 20, 0)
        docs.value = res.data
        if (refresh) Object.keys(expanded).forEach(k => delete expanded[k])
      } catch (_) {
        docs.value = []
      } finally {
        docsLoading.value = false
      }
    }

    function toggleDoc(i) {
      expanded[i] = !expanded[i]
    }

    function fmtDoc(doc) {
      return JSON.stringify(doc, null, 2)
    }

    return {
      collections, collectionsLoading,
      selectedCollection, docs, docsLoading, expanded,
      selectCollection, loadDocs, toggleDoc, fmtDoc,
    }
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
  padding: 10px 16px;
  border-bottom: 1px solid #e0e0e0;
  background: #f8f9fa;
  flex-shrink: 0;
  font-weight: 600;
  font-size: 14px;
}

.db-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.collection-list {
  width: 200px;
  border-right: 1px solid #e0e0e0;
  overflow-y: auto;
  flex-shrink: 0;
}

.collection-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 7px 12px;
  cursor: pointer;
  font-size: 12px;
  border-bottom: 1px solid #f5f5f5;
}

.collection-item:hover { background: #f0f4ff; }
.collection-item.active { background: #e8f0fe; font-weight: 600; }

.col-name { color: #333; word-break: break-all; }
.col-count {
  background: #e8e8e8;
  color: #555;
  border-radius: 10px;
  padding: 1px 6px;
  font-size: 11px;
  flex-shrink: 0;
  margin-left: 4px;
}

.doc-viewer {
  flex: 1;
  overflow-y: auto;
  padding: 10px 14px;
}

.status { color: #888; padding: 8px 0; font-size: 13px; }
.status.muted { color: #bbb; }

.doc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 12px;
  color: #555;
  font-weight: 600;
}

.load-more-btn {
  background: none;
  border: 1px solid #ddd;
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-size: 11px;
  color: #555;
}

.load-more-btn:hover { background: #f0f0f0; }

.doc-item {
  border: 1px solid #e8e8e8;
  border-radius: 4px;
  margin-bottom: 6px;
  overflow: hidden;
}

.doc-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  background: #fafafa;
  font-size: 12px;
  user-select: none;
}

.doc-toggle:hover { background: #f0f4ff; }

.doc-id {
  color: #333;
  font-family: monospace;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-json {
  margin: 0;
  padding: 8px 12px;
  background: #f8f8f8;
  font-size: 11px;
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-all;
  border-top: 1px solid #e8e8e8;
  max-height: 300px;
  overflow-y: auto;
}
</style>
