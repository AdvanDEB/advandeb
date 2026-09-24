<template>
  <div class="admin-experts-view">
    <header class="page-header">
      <h1>Experts</h1>
      <p class="subtitle">
        Who may contribute elicitations, which tier their judgments belong to,
        and how far the queue has actually got.
      </p>
    </header>

    <!-- ── Pending enrolment requests ─────────────────────────────── -->
    <section class="card">
      <div class="card-head">
        <h2>Pending requests</h2>
        <span v-if="requests.length" class="count-pill">{{ requests.length }}</span>
      </div>
      <p class="note">
        Tier is the scientific decision. <strong>Panel</strong> judgments carry the
        agreement statistics and the human consensus reported in the paper;
        <strong>contributor</strong> judgments are stored, attributed and creditable
        but are never pooled into panel statistics. Promotion later affects future
        work only — past judgments keep the tier they were made under.
      </p>

      <p v-if="loadingRequests" class="muted">Loading…</p>
      <p v-else-if="!requests.length" class="muted">No requests waiting.</p>

      <div v-for="r in requests" :key="r.id" class="request">
        <div class="request-head">
          <div>
            <strong>{{ r.full_name }}</strong>
            <span class="email">{{ r.email }}</span>
          </div>
          <span class="submitted">{{ formatDate(r.created_at) }}</span>
        </div>

        <ExpertiseProfileCard :profile="r" />

        <div class="decide">
          <button class="btn small" :disabled="busyId === r.id"
                  @click="decide(r, 'approve', 'panel')">
            Approve → panel
          </button>
          <button class="btn small" :disabled="busyId === r.id"
                  @click="decide(r, 'approve', 'contributor')">
            Approve → contributor
          </button>
          <button class="btn small danger" :disabled="busyId === r.id"
                  @click="decide(r, 'decline', null)">
            Decline
          </button>
          <input v-model="notes[r.id]" class="note-input" placeholder="Reason / note (recorded)" />
        </div>
      </div>
    </section>

    <!-- ── Current experts ────────────────────────────────────────── -->
    <section class="card">
      <div class="card-head">
        <h2>Current experts</h2>
        <span v-if="eligible !== null" class="count-pill">{{ eligible }} eligible</span>
      </div>

      <p v-if="loadingExperts" class="muted">Loading…</p>
      <p v-else-if="!experts.length" class="muted">No users found.</p>
      <table v-else class="experts-table">
        <thead>
          <tr>
            <th>Name</th><th>Roles</th><th>Tier</th>
            <th class="num">Elicitations</th><th>Access</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in experts" :key="u.id">
            <td>{{ u.name }}</td>
            <td>
              <span v-for="r in (u.roles || [])" :key="r" class="role-pill">{{ prettyRole(r) }}</span>
            </td>
            <td>
              <span v-if="u.tier" :class="['tier-badge', u.tier]">{{ u.tier }}</span>
              <span v-else class="muted">—</span>
            </td>
            <td class="num">{{ u.n_elicitations ?? '—' }}</td>
            <td>
              <span :class="['status-badge', canElicit(u) ? 'active' : 'off']">
                {{ canElicit(u) ? 'can elicit' : 'no access' }}
              </span>
              <span v-if="canElicit(u) && !u.has_capability" class="via-role" title="Granted by role, not by capability">
                via role
              </span>
            </td>
            <td class="actions">
              <button class="btn small" :disabled="busyId === u.id"
                      @click="setCapability(u, !u.has_capability)">
                {{ u.has_capability ? 'Revoke' : 'Grant' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ── Progress ───────────────────────────────────────────────── -->
    <section class="card">
      <div class="card-head"><h2>Progress</h2></div>
      <p v-if="loadingStats" class="muted">Loading…</p>
      <template v-else-if="stats">
        <!-- Panel coverage first: it is the number that reveals whether the
             human consensus is actually being collected, as opposed to the
             queue merely moving. -->
        <div class="panel-coverage">
          <div class="pc-head">
            <span class="pc-title">Panel coverage</span>
            <span class="pc-value">
              {{ stats.comparison_complete ?? 0 }} / {{ stats.comparison_total ?? 0 }}
              comparison items have their full panel
            </span>
          </div>
          <div class="bar-track">
            <div class="bar-fill" :style="{ width: `${comparisonPct}%` }"></div>
          </div>
          <p class="pc-note">
            A comparison item needs every panel judgment before it contributes a
            human consensus. Queue throughput can look healthy while this stays
            at zero.
          </p>
        </div>

        <div class="stat-row">
          <div class="stat">
            <span class="stat-value">{{ stats.completed ?? 0 }}</span>
            <span class="stat-label">of {{ stats.total_queue ?? 0 }} queue items</span>
          </div>
          <div class="stat">
            <span class="stat-value">{{ stats.repeated_judgments ?? 0 }}</span>
            <span class="stat-label">repeated judgments</span>
          </div>
          <div class="stat">
            <span class="stat-value">
              {{ stats.median_seconds_per_item ? Math.round(stats.median_seconds_per_item) + 's' : '—' }}
            </span>
            <span class="stat-label">median per item</span>
          </div>
          <div class="stat rung">
            <span class="stat-value">{{ stats.rung ?? 'R0' }}</span>
            <span class="stat-label">claims rung</span>
          </div>
        </div>

        <!-- Expert-named references. `recall_misses` is a headline figure for
             the method: each one is a paper the corpus held and retrieval
             failed to surface, named by an expert who knew it mattered
             (advandeb_methods docs/09 §2.5a). -->
        <div v-if="refStats" class="stat-row refs-row">
          <div class="stat miss">
            <span class="stat-value">{{ refStats.recall_misses ?? 0 }}</span>
            <span class="stat-label">
              retrieval misses
              <template v-if="refStats.miss_rate !== null && refStats.miss_rate !== undefined">
                ({{ Math.round(refStats.miss_rate * 100) }}% of
                {{ refStats.checked_for_retrieval }} checked)
              </template>
            </span>
          </div>
          <div class="stat">
            <span class="stat-value">{{ refStats.by_status?.not_in_corpus ?? 0 }}</span>
            <span class="stat-label">papers new to the corpus</span>
          </div>
          <div class="stat">
            <span class="stat-value">{{ refStats.by_status?.in_corpus_retrieved ?? 0 }}</span>
            <span class="stat-label">already read by the panel</span>
          </div>
          <div class="stat">
            <span class="stat-value">{{ refStats.undetermined ?? 0 }}</span>
            <span class="stat-label">retrieval undetermined</span>
          </div>
        </div>

        <p class="rung-note">
          <strong>{{ stats.rung }}</strong> — {{ stats.rung_note }}
          <span v-if="stats.next_rung_at" class="muted">
            · next rung at {{ stats.next_rung_at }}
            ({{ Math.max(0, stats.next_rung_at - (stats.completed ?? 0)) }} to go)
          </span>
        </p>

        <div class="split">
          <div v-if="byTask.length" class="col">
            <span class="col-title">By task</span>
            <ul class="mini">
              <li v-for="t in byTask" :key="t.k"><span>{{ t.k }}</span><b>{{ t.v }}</b></li>
            </ul>
          </div>
          <div v-if="byExpert.length" class="col">
            <span class="col-title">By expert</span>
            <ul class="mini">
              <li v-for="e in byExpert" :key="e.k"><span>{{ e.k }}</span><b>{{ e.v }}</b></li>
            </ul>
          </div>
        </div>

        <div v-if="byStratum.length" class="strata">
          <span class="col-title">Per-stratum coverage</span>
          <p class="hint">
            Prefix proportionality is the property that keeps a half-finished
            queue a valid sample — a stratum far behind the others is worth
            noticing early.
          </p>
          <ul class="mini two-col">
            <li v-for="s in byStratum" :key="s.k"><span>{{ s.k }}</span><b>{{ s.v }}</b></li>
          </ul>
        </div>
      </template>
      <p v-else class="muted">No statistics available.</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import api from '@/utils/api'
import ExpertiseProfileCard from '@/components/enrolment/ExpertiseProfileCard.vue'

interface ExpertRow {
  id: string
  name: string
  roles?: string[]
  tier?: string
  has_capability?: boolean
  can_elicit?: boolean
  can_annotate?: boolean   // tolerated: pre-rename field name
  n_elicitations?: number
}

const experts = ref<ExpertRow[]>([])
const eligible = ref<number | null>(null)
const requests = ref<any[]>([])
const stats = ref<any>(null)
const notes = reactive<Record<string, string>>({})

const loadingExperts = ref(true)
const loadingRequests = ref(true)
const loadingStats = ref(true)
const busyId = ref<string | null>(null)

// The backend is being built in parallel; accept either spelling rather than
// showing "no access" for everyone if one field name lands differently.
function canElicit(u: ExpertRow): boolean {
  return !!(u.can_elicit ?? u.can_annotate ?? u.has_capability)
}

const comparisonPct = computed(() => {
  const t = stats.value?.comparison_total || 0
  const c = stats.value?.comparison_complete || 0
  return t ? Math.round((c / t) * 100) : 0
})

// Expert-asserted references, served alongside the rest of admin stats.
const refStats = computed(() => stats.value?.expert_references || null)

const byTask = computed(() => toPairs(stats.value?.by_task))
const byExpert = computed(() => toPairs(stats.value?.by_expert))
const byStratum = computed(() => toPairs(stats.value?.by_stratum))

function toPairs(obj: Record<string, number> | undefined) {
  return Object.entries(obj || {})
    .map(([k, v]) => ({ k: k.replace(/_/g, ' '), v }))
    .sort((a, b) => b.v - a.v)
}

function prettyRole(r: string) {
  return r.replace(/_/g, ' ').replace('knowledge ', '')
}

function formatDate(d?: string) {
  if (!d) return ''
  try { return new Date(d).toLocaleDateString() } catch { return d }
}

async function loadExperts() {
  loadingExperts.value = true
  try {
    const { data } = await api.get('/elicitation/experts')
    experts.value = data.users || []
    eligible.value = data.eligible ?? null
  } catch { /* toast already surfaced by the interceptor */ }
  finally { loadingExperts.value = false }
}

async function loadRequests() {
  loadingRequests.value = true
  try {
    const { data } = await api.get('/enrolment/requests')
    requests.value = data.requests || data || []
  } catch { requests.value = [] }
  finally { loadingRequests.value = false }
}

async function loadStats() {
  loadingStats.value = true
  try {
    const { data } = await api.get('/elicitation/stats/admin')
    stats.value = data
  } catch { stats.value = null }
  finally { loadingStats.value = false }
}

async function setCapability(u: ExpertRow, granted: boolean) {
  busyId.value = u.id
  try {
    await api.post(`/elicitation/experts/${u.id}`, null, { params: { granted } })
    await loadExperts()
  } finally { busyId.value = null }
}

async function decide(r: any, decision: 'approve' | 'decline', tier: string | null) {
  busyId.value = r.id
  try {
    await api.post(`/enrolment/requests/${r.id}/decide`, {
      decision, tier, note: notes[r.id] || undefined,
    })
    await Promise.all([loadRequests(), loadExperts()])
  } finally { busyId.value = null }
}

onMounted(() => { loadExperts(); loadRequests(); loadStats() })
</script>

<style scoped>
.admin-experts-view {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  max-width: 1100px;
}
.page-header h1 { font-size: 1.5rem; font-weight: 700; color: #111827; }
.subtitle { color: #6b7280; line-height: 1.6; margin-top: 0.4rem; max-width: 60ch; }

.card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 1.25rem 1.5rem;
}
.card-head { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.6rem; }
.card-head h2 { font-size: 1.05rem; font-weight: 600; color: #111827; }
.count-pill {
  background: #111827; color: #fff; border-radius: 999px;
  padding: 0.1rem 0.5rem; font-size: 0.72rem; font-weight: 600;
}

.note {
  font-size: 0.82rem; color: #4b5563; line-height: 1.6;
  background: #f9fafb; border-radius: 6px; padding: 0.6rem 0.8rem;
  margin-bottom: 1rem;
}
.hint { font-size: 0.75rem; color: #9ca3af; line-height: 1.5; margin: 0.25rem 0 0.5rem; }
.muted { color: #9ca3af; font-size: 0.9rem; }

.request {
  border: 1px solid #e5e7eb; border-radius: 8px;
  padding: 1rem 1.1rem; margin-bottom: 0.9rem;
  display: flex; flex-direction: column; gap: 0.9rem;
}
.request-head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }
.request-head .email { color: #6b7280; font-size: 0.85rem; margin-left: 0.5rem; }
.submitted { font-size: 0.75rem; color: #9ca3af; }

.decide { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
.note-input {
  flex: 1; min-width: 180px;
  padding: 0.35rem 0.6rem; border: 1px solid #d1d5db;
  border-radius: 6px; font-size: 0.82rem;
}

.btn {
  padding: 0.5rem 1rem; border: 1px solid #d1d5db; border-radius: 6px;
  background: #fff; color: #374151; cursor: pointer;
  font-size: 0.85rem; font-weight: 600;
}
.btn:hover:not(:disabled) { background: #f3f4f6; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.small { padding: 0.35rem 0.7rem; font-size: 0.8rem; }
.btn.danger { color: #dc2626; border-color: #fecaca; }
.btn.danger:hover:not(:disabled) { background: #fef2f2; }

.experts-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.experts-table th {
  text-align: left; padding: 0.5rem 0.6rem; border-bottom: 2px solid #e5e7eb;
  color: #6b7280; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.03em;
}
.experts-table th.num, .experts-table td.num { text-align: right; }
.experts-table td { padding: 0.6rem; border-bottom: 1px solid #f3f4f6; vertical-align: middle; }

.role-pill {
  display: inline-block; padding: 0.15rem 0.5rem; margin: 0 0.2rem 0.2rem 0;
  border-radius: 999px; font-size: 0.72rem; font-weight: 600;
  border: 1px solid #e5e7eb; color: #6b7280; background: #f9fafb;
}
.tier-badge {
  padding: 0.15rem 0.55rem; border-radius: 999px;
  font-size: 0.75rem; font-weight: 600;
}
.tier-badge.panel { background: #dbeafe; color: #1d4ed8; }
.tier-badge.contributor { background: #f3e8ff; color: #7e22ce; }

.status-badge { padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
.status-badge.active { background: #dcfce7; color: #15803d; }
.status-badge.off { background: #f3f4f6; color: #9ca3af; }
.via-role { font-size: 0.68rem; color: #9ca3af; margin-left: 0.35rem; }

.panel-coverage { margin-bottom: 1.2rem; }
.pc-head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; flex-wrap: wrap; }
.pc-title { font-size: 0.75rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600; }
.pc-value { font-size: 0.85rem; color: #374151; }
.bar-track { height: 8px; background: #f3f4f6; border-radius: 999px; margin-top: 0.4rem; overflow: hidden; }
.bar-fill { height: 100%; background: #3b82f6; border-radius: 999px; transition: width 0.3s; }
.pc-note { font-size: 0.75rem; color: #9ca3af; margin-top: 0.4rem; line-height: 1.5; }

.stat-row { display: flex; gap: 2rem; flex-wrap: wrap; padding: 0.8rem 0; border-top: 1px solid #f3f4f6; }
.stat { display: flex; flex-direction: column; }
.stat-value { font-size: 1.3rem; font-weight: 700; color: #111827; }
.stat-label { font-size: 0.72rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.03em; }
.stat.rung .stat-value { color: #1d4ed8; }

.rung-note { font-size: 0.85rem; color: #374151; line-height: 1.6; padding-bottom: 0.8rem; }

.split { display: flex; gap: 2.5rem; flex-wrap: wrap; border-top: 1px solid #f3f4f6; padding-top: 0.9rem; }
.col { flex: 1; min-width: 200px; }
.col-title { font-size: 0.72rem; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600; }
.mini { list-style: none; margin-top: 0.4rem; display: flex; flex-direction: column; gap: 0.2rem; }
.mini li { display: flex; justify-content: space-between; font-size: 0.82rem; color: #374151; gap: 1rem; }
.mini li b { color: #111827; }
.mini.two-col { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 0.2rem 1.5rem; }

.strata { border-top: 1px solid #f3f4f6; padding-top: 0.9rem; margin-top: 0.9rem; }
.refs-row { margin-top: 0.6rem; }
.stat.miss .stat-value { color: #b45309; }
</style>
