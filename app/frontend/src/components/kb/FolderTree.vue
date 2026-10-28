<template>
  <ul class="ft-list">
    <!-- Subfolders -->
    <li v-for="sub in node.subdirs" :key="sub.path" class="ft-item">
      <div class="ft-row ft-folder-row">
        <input
          type="checkbox"
          class="cb"
          :aria-label="`Select folder ${sub.name}`"
          :checked="isFolderChecked(sub.path)"
          :indeterminate="isFolderIndeterminate(sub.path)"
          @change="toggleFolder(sub)"
        />
        <button
          type="button"
          class="ft-expand-btn"
          :aria-expanded="expanded.has(sub.path)"
          :aria-label="`${expanded.has(sub.path) ? 'Collapse' : 'Expand'} ${sub.name}`"
          @click="toggleExpand(sub.path)"
        >
          {{ expanded.has(sub.path) ? '▾' : '▸' }}
        </button>
        <span class="ft-name">{{ sub.name }}</span>
        <span class="ft-count dim">{{ countPdfs(sub) }}</span>
      </div>
      <FolderTree
        v-if="expanded.has(sub.path)"
        :node="sub"
        :selected-files="selectedFiles"
        :selected-folders="selectedFolders"
        @toggle-file="$emit('toggle-file', $event)"
        @toggle-folder="$emit('toggle-folder', $event)"
      />
    </li>

    <!-- Files at this level -->
    <li v-for="f in node.files" :key="f.path" class="ft-item ft-file-item">
      <div class="ft-row ft-file-row">
        <input
          type="checkbox"
          class="cb"
          :aria-label="`Select ${f.name}`"
          :checked="selectedFiles.has(f.path)"
          @change="$emit('toggle-file', f.path)"
        />
        <span class="ft-name ft-file-name">{{ f.name }}</span>
        <span class="ft-count dim">{{ formatBytes(f.size) }}</span>
      </div>
    </li>
  </ul>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { formatBytes } from '@/utils/format'

export interface FolderNode {
  path: string
  name: string
  files: { path: string; name: string; size: number }[]
  subdirs: FolderNode[]
}

const props = defineProps<{
  node: FolderNode
  selectedFiles: Set<string>
  selectedFolders: Set<string>
}>()

const emit = defineEmits<{
  (e: 'toggle-file', path: string): void
  (e: 'toggle-folder', node: FolderNode): void
}>()

const expanded = ref<Set<string>>(new Set())

function toggleExpand(path: string) {
  const next = new Set(expanded.value)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  expanded.value = next
}

function toggleFolder(sub: FolderNode) {
  emit('toggle-folder', sub)
}

/** Recursively collect all file paths under a node */
function allFilePaths(n: FolderNode): string[] {
  const paths: string[] = n.files.map(f => f.path)
  for (const sub of n.subdirs) paths.push(...allFilePaths(sub))
  return paths
}

function countPdfs(n: FolderNode): string {
  const c = allFilePaths(n).length
  return `${c} PDF${c !== 1 ? 's' : ''}`
}

function isFolderChecked(folderPath: string): boolean {
  if (props.selectedFolders.has(folderPath)) return true
  // Also checked if every file under it is individually selected
  const sub = props.node.subdirs.find(s => s.path === folderPath)
  if (!sub) return false
  const all = allFilePaths(sub)
  return all.length > 0 && all.every(p => props.selectedFiles.has(p))
}

function isFolderIndeterminate(folderPath: string): boolean {
  if (props.selectedFolders.has(folderPath)) return false
  const sub = props.node.subdirs.find(s => s.path === folderPath)
  if (!sub) return false
  const all = allFilePaths(sub)
  const selected = all.filter(p => props.selectedFiles.has(p))
  return selected.length > 0 && selected.length < all.length
}
</script>

<style scoped>
.ft-list { list-style: none; margin: 0; padding: 0 0 0 1.4rem; display: flex; flex-direction: column; gap: 1px; }
.ft-item { }
.ft-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.2rem 0.35rem;
  border-radius: 3px;
}
.ft-folder-row { background: #0f172a; }
.ft-file-row   { background: #172033; }
.ft-expand-btn {
  background: none; border: none; color: #94a3b8;
  cursor: pointer; padding: 0 0.15rem; font-size: 0.72rem; line-height: 1;
}
.ft-name      { font-size: 0.8rem; color: #e2e8f0; flex: 1; }
.ft-file-name { font-size: 0.75rem; color: #cbd5e1; }
.ft-count     { font-size: 0.68rem; white-space: nowrap; }
.dim          { color: #64748b; }
.cb           { accent-color: #6366f1; cursor: pointer; }

@media (pointer: coarse) {
  .ft-expand-btn { min-width: var(--app-touch); min-height: var(--app-touch); }
}
</style>
