<template>
  <div class="drawer-content">
    <div class="drawer-header">
      <span class="drawer-title">⬡ KG Builder</span>
      <div class="tabs">
        <button v-for="tab in tabs" :key="tab" class="tab-btn" :class="{ active: activeTab === tab }" @click="setTab(tab)">{{ tab }}</button>
      </div>
    </div>

    <!-- Stats tab -->
    <div v-if="activeTab === 'Stats'" class="tab-pane">
      <div v-if="statsLoading" class="status">Loading…</div>
      <div v-else-if="stats" class="stats-grid">
        <div class="stat-card">
          <div class="stat-val">{{ fmt(stats.total_documents) }}</div>
          <div class="stat-lbl">Total documents</div>
        </div>
        <div class="stat-card linked">
          <div class="stat-val">{{ fmt(stats.linked_documents) }}</div>
          <div class="stat-lbl">Linked to taxa</div>
        </div>
        <div class="stat-card unlinked">
          <div class="stat-val">{{ fmt(stats.unlinked_documents) }}</div>
          <div class="stat-lbl">Unlinked</div>
        </div>
        <div class="stat-card">
          <div class="stat-val">{{ fmt(stats.total_relations) }}</div>
          <div class="stat-lbl">Total relations</div>
        </div>
        <div class="stat-card ok">
          <div class="stat-val">{{ fmt(stats.confirmed_relations) }}</div>
          <div class="stat-lbl">Confirmed</div>
        </div>
        <div class="stat-card pending">
          <div class="stat-val">{{ fmt(stats.suggested_relations) }}</div>
          <div class="stat-lbl">Suggested</div>
        </div>
      </div>
      <div class="pct-bar" v-if="stats && stats.total_documents">
        <div class="pct-fill" :style="{ width: linkPct + '%' }"></div>
        <span class="pct-label">{{ linkPct.toFixed(1) }}% linked</span>
      </div>
      <button class="btn-primary mt" @click="loadStats">↻ Refresh</button>
    </div>

    <!-- Link tab -->
    <div v-if="activeTab === 'Link'" class="tab-pane">
      <div class="form-row">
        <label class="form-label">Root taxon ID</label>
        <input v-model.number="rootTaxid" type="number" class="form-input" placeholder="40674 = Mammalia" />
      </div>
      <div class="form-row">
        <label class="form-label">Batch size</label>
        <input v-model.number="batchLimit" type="number" class="form-input" min="1" max="5000" />
      </div>
      <div class="form-row">
        <label class="form-label">Skip</label>
        <input v-model.number="batchSkip" type="number" class="form-input" min="0" />
      </div>
      <div class="action-row">
        <button class="btn-primary" :disabled="linking" @click="runLink">
          {{ linking ? 'Linking…' : '▶ Link Batch (sync)' }}
        </button>
        <button class="btn-secondary" :disabled="linking" @click="runLinkAsync">
          {{ linking ? '…' : '⬡ Enqueue (async)' }}
        </button>
      </div>
      <div v-if="linkError" class="status error">{{ linkError }}</div>
      <div v-if="linkResult" class="result-box">
        <div class="result-row"><span>Documents processed</span><strong>{{ linkResult.documents_processed }}</strong></div>
        <div class="result-row"><span>Documents linked</span><strong>{{ linkResult.documents_linked }}</strong></div>
        <div class="result-row"><span>Relations written</span><strong>{{ linkResult.relations_written }}</strong></div>
        <div v-if="linkResult.index_entries" class="result-row">
          <span>Index entries</span><strong>{{ fmt(linkResult.index_entries) }}</strong>
        </div>
        <div v-if="linkResult.task_id" class="result-row">
          <span>Task ID</span><code>{{ linkResult.task_id }}</code>
        </div>
      </div>
      <div class="hint">
        After linking, use the Rebuild button in the toolbar to regenerate the <code>knowledge_graph</code> schema.
      </div>
    </div>

    <!-- Agent tab -->
    <div v-if="activeTab === 'Agent'" class="tab-pane">
      <div class="form-row">
        <label class="form-label">Ollama model</label>
        <select v-model="agentModel" class="form-input">
          <option v-for="m in availableModels" :key="m" :value="m">{{ m }}</option>
        </select>
      </div>
      <div class="form-row">
        <label class="form-label">Batch size</label>
        <input v-model.number="agentLimit" type="number" class="form-input" min="1" max="500" />
      </div>
      <div class="form-row">
        <label class="form-label">Skip</label>
        <input v-model.number="agentSkip" type="number" class="form-input" min="0" />
      </div>
      <div class="action-row">
        <button class="btn-primary" :disabled="agentRunning" @click="runAgentSync">
          {{ agentRunning ? 'Running…' : '▶ Run Agent (sync)' }}
        </button>
        <button class="btn-secondary" :disabled="agentRunning" @click="runAgentAsync">
          {{ agentRunning ? '…' : '⬡ Enqueue (async)' }}
        </button>
      </div>
      <div v-if="agentError" class="status error">{{ agentError }}</div>
      <div v-if="agentResult" class="result-box">
        <div class="result-row"><span>Docs processed</span><strong>{{ agentResult.documents_processed }}</strong></div>
        <div class="result-row"><span>Docs linked</span><strong>{{ agentResult.documents_linked }}</strong></div>
        <div class="result-row"><span>Relations written</span><strong>{{ agentResult.relations_written }}</strong></div>
        <div v-if="agentResult.task_id" class="result-row">
          <span>Task ID</span><code>{{ agentResult.task_id }}</code>
        </div>
      </div>
      <div class="hint">
        The agent reads each document's title + abstract and calls a <code>lookup_taxon</code> tool to resolve organism references to NCBI taxonomy IDs.
      </div>
    </div>

    <!-- Relations tab -->
    <div v-if="activeTab === 'Relations'" class="tab-pane">
      <div class="filter-row">
        <select v-model="relFilter" class="form-input sm" @change="loadRelations">
          <option value="">All</option>
          <option value="suggested">Suggested</option>
          <option value="confirmed">Confirmed</option>
          <option value="rejected">Rejected</option>
        </select>
        <button class="btn-secondary sm" @click="loadRelations">↻</button>
      </div>
      <div v-if="relLoading" class="status">Loading…</div>
      <table v-else class="data-table">
        <thead>
          <tr><th>Doc ID</th><th>tax_id</th><th>Conf</th><th>Evidence</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="r in relations" :key="r._id">
            <td class="mono">{{ r.document_id.slice(-6) }}</td>
            <td class="mono">{{ r.tax_id }}</td>
            <td>{{ (r.confidence * 100).toFixed(0) }}%</td>
            <td class="truncate">{{ r.evidence }}</td>
            <td><span class="badge" :class="r.status">{{ r.status }}</span></td>
            <td class="actions">
              <button v-if="r.status === 'suggested'" class="action-btn ok" @click="confirm(r)">✓</button>
              <button v-if="r.status !== 'rejected'" class="action-btn bad" @click="reject(r)">✗</button>
            </td>
          </tr>
          <tr v-if="!relations.length"><td colspan="6" class="empty-row">No relations</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { kgAPI, agentsAPI } from '@/utils/kbApi'

export default {
  name: 'KGBuilderDrawer',
  setup() {
    const tabs = ['Stats', 'Link', 'Agent', 'Relations']
    const activeTab = ref('Stats')

    // Stats
    const stats = ref(null)
    const statsLoading = ref(false)
    const linkPct = computed(() => {
      if (!stats.value || !stats.value.total_documents) return 0
      return (stats.value.linked_documents / stats.value.total_documents) * 100
    })

    // Link
    const rootTaxid = ref(40674)
    const batchLimit = ref(200)
    const batchSkip = ref(0)
    const linking = ref(false)
    const linkResult = ref(null)
    const linkError = ref('')

    // Agent
    const availableModels = ref(['mistral'])
    const agentModel = ref('mistral')
    const agentLimit = ref(20)
    const agentSkip = ref(0)
    const agentRunning = ref(false)
    const agentResult = ref(null)
    const agentError = ref('')

    // Relations
    const relations = ref([])
    const relLoading = ref(false)
    const relFilter = ref('suggested')

    onMounted(loadStats)

    async function loadAgentModels() {
      try {
        const res = await agentsAPI.getModels()
        availableModels.value = res.data?.models || ['mistral']
        if (!availableModels.value.includes(agentModel.value)) {
          agentModel.value = availableModels.value[0] || 'mistral'
        }
      } catch (_) {
        availableModels.value = ['mistral']
      }
    }

    async function setTab(tab) {
      activeTab.value = tab
      if (tab === 'Stats') loadStats()
      else if (tab === 'Agent') loadAgentModels()
      else if (tab === 'Relations') loadRelations()
    }

    async function loadStats() {
      statsLoading.value = true
      try {
        const res = await kgAPI.getStats()
        stats.value = res.data
      } catch (_) {
        stats.value = null
      } finally {
        statsLoading.value = false
      }
    }

    async function runLink() {
      linking.value = true
      linkResult.value = null
      linkError.value = ''
      try {
        const res = await kgAPI.linkSync(rootTaxid.value, batchLimit.value, batchSkip.value)
        linkResult.value = res.data
        batchSkip.value += res.data.documents_processed || batchLimit.value
        await loadStats()
      } catch (e) {
        linkError.value = e.response?.data?.detail || e.message
      } finally {
        linking.value = false
      }
    }

    async function runLinkAsync() {
      linking.value = true
      linkResult.value = null
      linkError.value = ''
      try {
        const res = await kgAPI.linkAsync(rootTaxid.value, batchLimit.value, batchSkip.value)
        linkResult.value = res.data
      } catch (e) {
        linkError.value = e.response?.data?.detail || e.message
      } finally {
        linking.value = false
      }
    }

    async function runAgentSync() {
      agentRunning.value = true
      agentResult.value = null
      agentError.value = ''
      try {
        const res = await kgAPI.linkAgentSync(agentModel.value, agentLimit.value, agentSkip.value)
        agentResult.value = res.data
        agentSkip.value += res.data.documents_processed || agentLimit.value
        await loadStats()
      } catch (e) {
        agentError.value = e.response?.data?.detail || e.message
      } finally {
        agentRunning.value = false
      }
    }

    async function runAgentAsync() {
      agentRunning.value = true
      agentResult.value = null
      agentError.value = ''
      try {
        const res = await kgAPI.linkAgentAsync(agentModel.value, 500, agentSkip.value)
        agentResult.value = res.data
      } catch (e) {
        agentError.value = e.response?.data?.detail || e.message
      } finally {
        agentRunning.value = false
      }
    }

    async function loadRelations() {
      relLoading.value = true
      try {
        const params = { limit: 50 }
        if (relFilter.value) params.status = relFilter.value
        const res = await kgAPI.listRelations(params)
        relations.value = res.data.relations || []
      } catch (_) {
        relations.value = []
      } finally {
        relLoading.value = false
      }
    }

    async function confirm(rel) {
      await kgAPI.updateRelation(rel._id, { status: 'confirmed' })
      rel.status = 'confirmed'
    }

    async function reject(rel) {
      await kgAPI.updateRelation(rel._id, { status: 'rejected' })
      rel.status = 'rejected'
    }

    function fmt(n) {
      return n != null ? n.toLocaleString() : '—'
    }

    return {
      tabs, activeTab, setTab,
      stats, statsLoading, linkPct, loadStats,
      rootTaxid, batchLimit, batchSkip, linking, linkResult, linkError,
      runLink, runLinkAsync,
      availableModels, agentModel, agentLimit, agentSkip,
      agentRunning, agentResult, agentError,
      runAgentSync, runAgentAsync,
      relations, relLoading, relFilter, loadRelations, confirm, reject,
      fmt,
    }
  },
}
</script>

<style scoped>
.drawer-content { display: flex; flex-direction: column; height: 100%; }

.drawer-header {
  display: flex; align-items: center; gap: 16px;
  padding: 10px 16px; border-bottom: 1px solid #e0e0e0;
  background: #f8f9fa; flex-shrink: 0;
}
.drawer-title { font-weight: 600; font-size: 14px; }
.tabs { display: flex; gap: 4px; }
.tab-btn {
  padding: 4px 12px; border: 1px solid #ddd; border-radius: 4px;
  background: #fff; cursor: pointer; font-size: 12px;
}
.tab-btn.active { background: #4a90e2; color: #fff; border-color: #4a90e2; }

.tab-pane { flex: 1; overflow-y: auto; padding: 14px 16px; }
.status { color: #888; padding: 8px 0; font-size: 13px; }
.status.error { color: #e74c3c; }

.stats-grid {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 10px; margin-bottom: 12px;
}
.stat-card {
  border: 1px solid #e8e8e8; border-radius: 6px;
  padding: 10px 12px; text-align: center;
}
.stat-card.linked { border-color: #27ae60; }
.stat-card.unlinked { border-color: #e67e22; }
.stat-card.ok { border-color: #4a90e2; }
.stat-card.pending { border-color: #f39c12; }
.stat-val { font-size: 20px; font-weight: 700; color: #222; }
.stat-lbl { font-size: 11px; color: #888; margin-top: 2px; }

.pct-bar {
  height: 18px; background: #eee; border-radius: 9px;
  position: relative; overflow: hidden; margin-bottom: 10px;
}
.pct-fill {
  height: 100%; background: #27ae60; border-radius: 9px;
  transition: width 0.4s;
}
.pct-label {
  position: absolute; inset: 0; display: flex;
  align-items: center; justify-content: center;
  font-size: 11px; font-weight: 600; color: #333;
}

.form-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.form-label { font-size: 12px; color: #555; min-width: 100px; }
.form-input {
  flex: 1; padding: 5px 8px; border: 1px solid #ddd;
  border-radius: 4px; font-size: 12px;
}
.form-input.sm { width: 120px; flex: none; }

.action-row { display: flex; gap: 8px; margin-bottom: 10px; }

.btn-primary {
  padding: 6px 14px; background: #4a90e2; color: #fff;
  border: none; border-radius: 4px; cursor: pointer; font-size: 12px;
}
.btn-primary:disabled { background: #aac4e8; cursor: default; }
.btn-primary:not(:disabled):hover { background: #357abd; }
.btn-primary.mt { margin-top: 8px; }

.btn-secondary {
  padding: 6px 12px; background: #f0f0f0; color: #444;
  border: 1px solid #ddd; border-radius: 4px; cursor: pointer; font-size: 12px;
}
.btn-secondary:hover { background: #e0e0e0; }
.btn-secondary.sm { padding: 4px 8px; }

.result-box {
  background: #f8f9fa; border: 1px solid #e0e0e0;
  border-radius: 6px; padding: 10px 12px; margin: 10px 0;
}
.result-row {
  display: flex; justify-content: space-between;
  padding: 3px 0; font-size: 12px; color: #555;
}
.result-row strong { color: #222; }

.hint { font-size: 11px; color: #999; margin-top: 10px; line-height: 1.5; }
.hint code { background: #f0f0f0; padding: 1px 4px; border-radius: 3px; }

.filter-row { display: flex; gap: 8px; margin-bottom: 10px; align-items: center; }

.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th {
  text-align: left; padding: 6px 8px;
  background: #f0f0f0; border-bottom: 2px solid #ddd;
  font-weight: 600; color: #555;
}
.data-table td { padding: 5px 8px; border-bottom: 1px solid #f0f0f0; }
.data-table tr:hover td { background: #fafafa; }
.mono { font-family: monospace; font-size: 11px; }
.truncate { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.actions { display: flex; gap: 4px; }
.action-btn {
  padding: 2px 6px; border: none; border-radius: 3px;
  cursor: pointer; font-size: 12px; font-weight: 600;
}
.action-btn.ok { background: #d4edda; color: #155724; }
.action-btn.ok:hover { background: #27ae60; color: #fff; }
.action-btn.bad { background: #f8d7da; color: #721c24; }
.action-btn.bad:hover { background: #e74c3c; color: #fff; }
.badge { padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 500; }
.badge.suggested { background: #fff3cd; color: #856404; }
.badge.confirmed { background: #d4edda; color: #155724; }
.badge.rejected { background: #f8d7da; color: #721c24; }
.empty-row { text-align: center; color: #aaa; padding: 16px !important; }
</style>
