<template>
  <div class="kb-view">
    <a href="#main-content" class="skip-link">Skip to content</a>

    <!-- Top bar -->
    <header class="kb-header">
      <div class="header-left">
        <router-link to="/" class="back-link" title="Back to app" aria-label="Back to app">←</router-link>
        <span class="header-title">Knowledge Builder</span>
      </div>
      <nav class="tab-nav" role="tablist" aria-label="Knowledge Builder sections">
        <button
          v-for="tab in TABS"
          :key="tab.id"
          role="tab"
          type="button"
          :aria-selected="activeTab === tab.id"
          :class="['tab-btn', { active: activeTab === tab.id }]"
          @click="activeTab = tab.id"
        >{{ tab.label }}</button>
      </nav>
      <div class="header-right">
        <span v-if="loading" class="loading-chip">Loading…</span>
        <span v-if="error" role="alert" class="error-alert"><button type="button" class="error-chip" title="Click to dismiss" @click="error = ''">{{ error }}</button></span>
        <button
          v-if="authStore.hasRole('administrator')"
          class="header-btn danger"
          :disabled="resetting"
          @click="confirmReset"
        >{{ resetting ? 'Resetting…' : 'Reset DB' }}</button>
      </div>
    </header>

    <!-- Each tab owns its state and loads lazily when first shown. v-show, not
         v-if: a tab keeps its state (filters, selections, scroll) across switches. -->
    <main id="main-content" class="kb-main" tabindex="-1">
      <GraphTab v-show="activeTab === 'graph'" />
      <IngestionTab v-show="activeTab === 'ingestion'" />
      <DatabaseTab v-show="activeTab === 'database'" />
      <KgBuilderTab v-show="activeTab === 'kg'" />
      <SuggestionsTab v-show="activeTab === 'suggestions'" />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { useKnowledgeBuilderStore } from '@/stores/knowledgeBuilder'
import type { KbTab } from '@/stores/knowledgeBuilder'
import GraphTab from '@/components/kb/tabs/GraphTab.vue'
import IngestionTab from '@/components/kb/tabs/IngestionTab.vue'
import DatabaseTab from '@/components/kb/tabs/DatabaseTab.vue'
import KgBuilderTab from '@/components/kb/tabs/KgBuilderTab.vue'
import SuggestionsTab from '@/components/kb/tabs/SuggestionsTab.vue'
import { resetKnowledgeBase, fetchResetPreview } from '@/utils/kbApi'
import type { ResetPreview } from '@/utils/kbApi'
import { formatCount as fmtNum } from '@/utils/format'

const authStore = useAuthStore()
const kb = useKnowledgeBuilderStore()

// ---- Tabs -------------------------------------------------------------------

const TABS: { id: KbTab; label: string }[] = [
  { id: 'graph', label: 'Graph' },
  { id: 'ingestion', label: 'Ingestion' },
  { id: 'database', label: 'Database' },
  { id: 'kg', label: 'KG Builder' },
  { id: 'suggestions', label: 'Suggestions' },
]

// ---- Global state -----------------------------------------------------------
//
// Shared with the tabs through the store (stores/knowledgeBuilder.ts). Reset DB
// stays here, beside its header button; it clears the graph and reloads the
// schema list, which is why those live in the store too.

const { activeTab, loading, error, graphBundle, selectedNode } = storeToRefs(kb)
const { setError, loadSchemas, terminateWorker } = kb
const resetting = ref(false)

async function confirmReset() {
  // Ask the server what it would clear rather than describing it here. The
  // hardcoded text had drifted: it warned about "graph nodes" and "ingestion
  // jobs" (neither is cleared) and called taxa "taxonomy_nodes". Showing real
  // row counts also makes the scale of an irreversible action visible.
  resetting.value = true
  let preview: ResetPreview
  try {
    preview = await fetchResetPreview()
  } catch (e) {
    setError(e)
    resetting.value = false
    return
  }
  resetting.value = false

  // The server refuses a reset without a recent backup; say so up front rather
  // than after the admin has typed the confirmation.
  const backup = preview.latest_backup
  if (!backup || backup.age_hours > preview.max_backup_age_hours) {
    alert(
      backup
        ? `The latest backup of ${preview.database} is ${backup.age_hours} h old ` +
          `(limit ${preview.max_backup_age_hours} h). Run a fresh backup ` +
          `(scripts/backup/advandeb_backup.py) before resetting.`
        : `There is no backup of ${preview.database}. Run scripts/backup/advandeb_backup.py ` +
          `before resetting: the reset cannot be undone without one.`
    )
    return
  }

  const clears = preview.clears.map(c => `  • ${c.name} (${fmtNum(c.count)})`).join('\n')
  const keeps = preview.keeps.map(k => `${k.name} (${fmtNum(k.count)})`).join(', ')
  const typed = prompt(
    `This permanently deletes ${fmtNum(preview.total_rows)} rows from ArangoDB:\n\n${clears}\n\n` +
    `Kept: ${keeps}\nRestore point: ${backup.path} (${backup.age_hours} h old)\n\n` +
    `Type the database name (${preview.database}) to confirm.`
  )
  if (typed === null) return
  if (typed.trim() !== preview.database) {
    alert('The name did not match. Nothing was deleted.')
    return
  }

  resetting.value = true
  try {
    const result = await resetKnowledgeBase(typed.trim())
    const summary = Object.entries(result.cleared ?? {})
      .map(([name, n]) => `${name}: ${fmtNum(n)}`)
      .join('\n')
    alert(`Reset complete.\n\n${summary || 'Nothing to clear.'}`)
    graphBundle.value = null
    selectedNode.value = null
    terminateWorker()
    await loadSchemas()
  } catch (e) { setError(e) }
  finally { resetting.value = false }
}

// ---- Init -------------------------------------------------------------------

onMounted(loadSchemas)

// Leaving /kb stops the graph worker and drops the (large) graph bundle, so the
// next visit starts fresh, as it did when this state lived in the view.
onUnmounted(() => { terminateWorker(); kb.reset() })
</script>

<style scoped>
.kb-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh; /* mobile browsers: excludes the collapsing URL bar */
  background: #0a0b0f;
  color: #e2e8f0;
  font-family: system-ui, sans-serif;
  overflow: hidden;
}

/* ---- Header ---------------------------------------------------------------- */
.kb-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0 1rem;
  height: 44px;
  background: #0f1117;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  flex-shrink: 0;
}

.back-link {
  color: #64748b;
  text-decoration: none;
  font-size: 1.1rem;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
}
.back-link:hover { background: #334155; color: #e2e8f0; }

.header-title {
  font-size: 0.85rem;
  font-weight: 700;
  color: #e2e8f0;
  letter-spacing: 0.02em;
}

.tab-nav {
  display: flex;
  gap: 0.1rem;
  margin-left: 1rem;
}

.tab-btn {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 0.3rem 0.75rem;
  color: #64748b;
  font-size: 0.78rem;
  cursor: pointer;
  white-space: nowrap;
  height: 44px;
}
.tab-btn:hover { color: #cbd5e1; }
.tab-btn.active { color: #60a5fa; border-bottom-color: var(--app-primary); }

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.loading-chip { font-size: 0.7rem; color: #64748b; }
/* role="alert" wrapper, so a new error is announced; the chip inside is the
   dismiss button. */
.error-alert { display: flex; min-width: 0; }
.error-chip {
  font: inherit;
  font-size: 0.7rem;
  text-align: left;
  border: none;
  background: #7f1d1d;
  color: #fca5a5;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  min-width: 0;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.error-chip:focus-visible { outline: 2px solid #fca5a5; outline-offset: 2px; }

.header-btn {
  padding: 0.3rem 0.65rem;
  border-radius: 5px;
  border: 1px solid #334155;
  background: #0f172a;
  color: #cbd5e1;
  font-size: 0.72rem;
  cursor: pointer;
}
.header-btn:hover { background: #334155; }
.header-btn.danger { border-color: #7f1d1d; color: #fca5a5; }
.header-btn.danger:hover { background: #7f1d1d; }
.header-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ---- Tab content ----------------------------------------------------------- */
.kb-main {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
/* Focused only by the skip link; the tab content itself is the indicator. */
.kb-main:focus { outline: none; }

/* ---- Narrow screens -----------------------------------------------------------
   The header wraps: title and actions on the first row, the tab strip on its
   own row below, scrolling sideways rather than overflowing the page. */
@media (max-width: 768px) {
  .kb-header {
    height: auto;
    flex-wrap: wrap;
    column-gap: 0.75rem;
    row-gap: 0;
    padding: 0 0.75rem;
  }
  .header-left,
  .header-right { min-height: 44px; display: flex; align-items: center; }
  .tab-nav {
    order: 3;
    flex-basis: 100%;
    margin-left: 0;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .tab-btn { flex-shrink: 0; }
  .error-chip { max-width: 45vw; }
}

/* ---- Touch ------------------------------------------------------------------ */
@media (pointer: coarse) {
  .back-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: var(--app-touch);
    min-height: var(--app-touch);
  }
  .header-btn,
  .error-chip { min-height: var(--app-touch); }
}
</style>
