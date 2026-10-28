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
    <section class="el-card">
      <div class="card-head">
        <h2>Pending requests</h2>
        <Transition name="count">
          <span v-if="requests.length" :key="requests.length" class="count-pill">
            {{ requests.length }}
          </span>
        </Transition>
      </div>

      <p class="note">
        Tier is the scientific decision. <strong>Panel</strong> judgments carry the
        agreement statistics and the human consensus reported in the paper;
        <strong>contributor</strong> judgments are stored, attributed and creditable
        but are never pooled into panel statistics. Promotion later affects future
        work only — past judgments keep the tier they were made under.
      </p>

      <!-- A new account's one-time password. The server returns it once and
           stores only its hash: if it is not shown here, it is lost and the
           person cannot sign in. The previous view discarded it. -->
      <div v-for="c in issued" :key="c.email" class="issued" role="status"
           data-test="issued">
        <p>
          <strong>{{ c.name }}</strong> approved as <strong>{{ c.tier }}</strong>.
          A new account was created — pass these on now; the password is not
          shown again.
        </p>
        <dl class="creds">
          <div><dt>Email</dt><dd><code>{{ c.email }}</code></dd></div>
          <div><dt>One-time password</dt><dd><code class="pw">{{ c.password }}</code></dd></div>
        </dl>
        <button class="el-btn el-btn--ghost act" @click="dismissIssued(c.email)">Done</button>
      </div>

      <LoadState
        :loading="loadingRequests"
        :error="errRequests"
        :empty="!requests.length"
        empty-text="No requests waiting."
        @retry="loadRequests"
      />

      <TransitionGroup name="row" tag="div">
        <div v-for="r in requests" :key="r.id" class="request">
          <div class="request-head">
            <div class="who">
              <strong>{{ r.name }}</strong>
              <a class="email" :href="`mailto:${r.email}`">{{ r.email }}</a>
            </div>
            <span class="submitted">{{ formatDate(r.created_at) }}</span>
          </div>

          <ExpertiseProfileCard :profile="r" />

          <input
            v-model="notes[r.id]"
            class="note-input"
            placeholder="Reason / note (recorded with the decision)"
          />

          <div class="decide">
            <button class="el-btn el-btn--primary act" :disabled="busyId === r.id"
                    @click="decide(r, true, 'panel')">
              Approve → panel
            </button>
            <button class="el-btn el-btn--ghost act" :disabled="busyId === r.id"
                    @click="decide(r, true, 'contributor')">
              Approve → contributor
            </button>
            <button class="el-btn el-btn--ghost act danger" :disabled="busyId === r.id"
                    @click="decide(r, false, null)">
              Decline
            </button>
          </div>

          <p v-if="rowError[r.id]" class="row-error" role="alert">
            {{ rowError[r.id] }}
          </p>
        </div>
      </TransitionGroup>
    </section>

    <!-- ── Current experts ────────────────────────────────────────── -->
    <section class="el-card">
      <div class="card-head">
        <h2>Current experts</h2>
        <span v-if="eligible !== null" class="count-pill ghost">{{ eligible }} eligible</span>
      </div>

      <LoadState
        :loading="loadingExperts"
        :error="errExperts"
        :empty="!experts.length"
        empty-text="No users found."
        @retry="loadExperts"
      />

      <!-- Desktop: a table. Phone: the same rows as stacked cards, because a
           six-column table at 360px is a pinch-zoom horizontal scroll. -->
      <table v-if="experts.length" class="experts-table">
        <thead>
          <tr>
            <th>Name</th><th>Roles</th><th>Tier</th>
            <th class="num">Elicitations</th><th>Access</th><th><span class="sr">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in experts" :key="u.id">
            <td data-h="Name">
              {{ u.name }}
              <span v-if="u.author_slugs.length" class="slugs"
                    title="Authored stylized facts under these slugs; excluded from their queue">
                author: {{ u.author_slugs.join(', ') }}
              </span>
            </td>
            <td data-h="Roles">
              <span v-for="r in (u.roles || [])" :key="r" class="role-pill">{{ prettyRole(r) }}</span>
            </td>
            <td data-h="Tier">
              <span v-if="u.tier" class="tier-badge" :class="u.tier">
                <span class="tier-dot" aria-hidden="true"></span>{{ u.tier }}
              </span>
              <span v-else class="muted">unassigned</span>
            </td>
            <td class="num" data-h="Elicitations">{{ u.n_elicitations }}</td>
            <td data-h="Access">
              <span class="status-badge" :class="canElicit(u) ? 'active' : 'off'">
                {{ canElicit(u) ? 'can elicit' : 'no access' }}
              </span>
              <span v-if="canElicit(u) && !u.has_capability" class="via-role">
                via role
              </span>
            </td>
            <td class="actions-cell">
              <button class="el-btn el-btn--ghost act" :disabled="busyId === u.id"
                      @click="setCapability(u, !u.has_capability)">
                {{ busyId === u.id ? '…' : (u.has_capability ? 'Revoke' : 'Grant') }}
              </button>
              <p v-if="rowError[u.id]" class="row-error" role="alert">{{ rowError[u.id] }}</p>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ── Progress ───────────────────────────────────────────────── -->
    <section class="el-card">
      <div class="card-head"><h2>Progress</h2></div>

      <LoadState
        :loading="loadingStats"
        :error="errStats"
        :empty="!stats"
        empty-text="No statistics available."
        @retry="loadStats"
      />

      <template v-if="stats">
        <!-- Panel coverage leads. A comparison item contributes nothing to the
             human consensus until every panel judgment is in, so throughput can
             look healthy while this sits at zero. It is the number that says
             whether the consensus is actually being collected. -->
        <div class="panel-coverage">
          <div class="pc-head">
            <span class="pc-title">Panel coverage</span>
            <span class="pc-value">
              <b>{{ stats.comparison_complete }}</b> of
              {{ stats.comparison_total }} comparison items have their full panel
            </span>
          </div>
          <div class="bar-track" role="img"
               :aria-label="`Panel coverage ${comparisonPct} percent`">
            <div class="bar-fill" :style="{ width: comparisonPct + '%' }"></div>
          </div>
          <p class="pc-note">
            Queue throughput can look healthy while this stays at zero.
          </p>
        </div>

        <div class="stat-row">
          <div class="stat">
            <span class="stat-value">{{ stats.completed }}</span>
            <span class="stat-label">judgments · {{ stats.total_queue }} queue items</span>
          </div>
          <div class="stat">
            <span class="stat-value">{{ stats.repeated_judgments }}</span>
            <span class="stat-label">repeated judgments</span>
          </div>
          <div class="stat">
            <span class="stat-value">
              {{ stats.median_seconds_per_item ? Math.round(stats.median_seconds_per_item) + 's' : '—' }}
            </span>
            <span class="stat-label">median per item</span>
          </div>
          <div class="stat">
            <span class="stat-value">{{ stats.rung }}</span>
            <span class="stat-label">claims rung</span>
          </div>
        </div>

        <!-- Expert-named references. `recall_misses` is a headline figure for the
             method: each is a paper the corpus held and retrieval failed to
             surface, named by an expert who knew it mattered
             (advandeb_methods docs/09 §2.5a). -->
        <div v-if="refStats" class="stat-row">
          <div class="stat">
            <span class="stat-value">{{ refStats.recall_misses ?? 0 }}</span>
            <span class="stat-label">
              retrieval misses<template
                v-if="refStats.miss_rate !== null && refStats.miss_rate !== undefined"
              > · {{ Math.round(refStats.miss_rate * 100) }}% of
                {{ refStats.checked_for_retrieval }} checked</template>
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
            · next rung at {{ stats.next_rung_at }} {{ stats.ladder_basis }}
            ({{ Math.max(0, stats.next_rung_at - stats.ladder_count) }} to go)
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
            Prefix proportionality is what keeps a half-finished queue a valid
            sample — a stratum far behind the others is worth noticing early.
          </p>
          <ul class="mini two-col">
            <li v-for="s in byStratum" :key="s.k">
              <span class="stratum-name">{{ s.k }}</span><b>{{ s.v }}</b>
            </li>
          </ul>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { formatDate } from '@/utils/format'
import api from '@/utils/api'
import ExpertiseProfileCard from '@/components/enrolment/ExpertiseProfileCard.vue'
import LoadState from '@/components/enrolment/LoadState.vue'

import type {
  AdminStats, ExpertList, ExpertListEntry,
} from '@/types/elicitation.generated'
import type {
  EnrolmentDecision, EnrolmentDecisionResult, EnrolmentRequestList,
  EnrolmentRequestRecord, Tier,
} from '@/types/enrolment.generated'

const experts = ref<ExpertListEntry[]>([])
const eligible = ref<number | null>(null)
const requests = ref<EnrolmentRequestRecord[]>([])
const stats = ref<AdminStats | null>(null)
const issued = ref<{ name: string; email: string; tier: Tier; password: string }[]>([])
const notes = reactive<Record<string, string>>({})
const rowError = reactive<Record<string, string>>({})

const loadingExperts = ref(true)
const loadingRequests = ref(true)
const loadingStats = ref(true)
const errExperts = ref('')
const errRequests = ref('')
const errStats = ref('')
const busyId = ref<string | null>(null)

function canElicit(u: ExpertListEntry): boolean {
  return u.can_elicit
}

const comparisonPct = computed(() => {
  const t = stats.value?.comparison_total || 0
  const c = stats.value?.comparison_complete || 0
  return t ? Math.round((c / t) * 100) : 0
})

const refStats = computed(() => stats.value?.expert_references || null)

const byTask = computed(() => toPairs(stats.value?.by_task))
// A list of per-expert rows, not a mapping: rendered as one before, it showed
// array indices where names belong.
const byExpert = computed(() => (stats.value?.by_expert ?? [])
  .map((e) => ({ k: e.name, v: e.n }))
  .sort((a, b) => b.v - a.v))
const byStratum = computed(() => toPairs(stats.value?.by_stratum))

function toPairs(obj: Record<string, number> | undefined) {
  return Object.entries(obj || {})
    .map(([k, v]) => ({ k: k.replace(/_/g, ' ').replace(/\|/g, ' · '), v }))
    .sort((a, b) => b.v - a.v)
}

function prettyRole(r: string) {
  return r.replace(/_/g, ' ').replace('knowledge ', '')
}

function readError(e: any): string {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg
  if (e?.response?.status === 403) return 'You do not have permission for this.'
  if (e?.message === 'Network Error') return 'Could not reach the server.'
  return 'Something went wrong. Try again.'
}

async function loadExperts() {
  loadingExperts.value = true; errExperts.value = ''
  try {
    const { data } = await api.get<ExpertList>('/elicitation/experts')
    experts.value = data.users
    eligible.value = data.eligible
  } catch (e) { errExperts.value = readError(e) }
  finally { loadingExperts.value = false }
}

async function loadRequests() {
  loadingRequests.value = true; errRequests.value = ''
  try {
    // Pending only: this list is the queue of decisions still to make.
    const { data } = await api.get<EnrolmentRequestList>('/enrolment/requests', {
      params: { status_filter: 'pending' },
    })
    requests.value = data.requests
  } catch (e) { errRequests.value = readError(e); requests.value = [] }
  finally { loadingRequests.value = false }
}

async function loadStats() {
  loadingStats.value = true; errStats.value = ''
  try {
    const { data } = await api.get<AdminStats>('/elicitation/stats/admin')
    stats.value = data
  } catch (e) { errStats.value = readError(e); stats.value = null }
  finally { loadingStats.value = false }
}

async function setCapability(u: ExpertListEntry, granted: boolean) {
  busyId.value = u.id
  delete rowError[u.id]
  try {
    await api.post(`/elicitation/experts/${u.id}`, null, { params: { granted } })
    await loadExperts()
  } catch (e) {
    // Previously swallowed: a failed grant looked identical to a successful one.
    rowError[u.id] = readError(e)
  } finally { busyId.value = null }
}

async function decide(r: EnrolmentRequestRecord, approve: boolean, tier: Tier | null) {
  busyId.value = r.id
  delete rowError[r.id]
  const body: EnrolmentDecision = { approve, tier, note: notes[r.id] || null }
  try {
    const { data } = await api.post<EnrolmentDecisionResult>(
      `/enrolment/requests/${r.id}/decide`, body)
    if (data.temp_password && data.tier) {
      issued.value = [...issued.value,
        { name: r.name, email: r.email, tier: data.tier, password: data.temp_password }]
    }
    await Promise.all([loadRequests(), loadExperts(), loadStats()])
  } catch (e) {
    rowError[r.id] = readError(e)
  } finally { busyId.value = null }
}

function dismissIssued(email: string) {
  issued.value = issued.value.filter((c) => c.email !== email)
}

onMounted(() => { loadExperts(); loadRequests(); loadStats() })
</script>

<style scoped>
@import '@/styles/elicitation-tokens.css';

.admin-experts-view {
  padding: var(--el-s5) var(--el-s6);
  display: flex; flex-direction: column; gap: var(--el-s5);
  max-width: 1100px;
}
.page-header h1 { font-size: var(--el-fs-xl); font-weight: 700; color: var(--el-ink); }
.subtitle {
  color: var(--el-ink-3); line-height: var(--el-lh);
  margin-top: var(--el-s1); max-width: 60ch; font-size: var(--el-fs-base);
}

.card-head {
  display: flex; align-items: center; gap: var(--el-s2);
  margin-bottom: var(--el-s2);
}
.card-head h2 { font-size: var(--el-fs-lg); font-weight: 600; color: var(--el-ink); }

.count-pill {
  background: var(--el-accent); color: #fff; border-radius: 999px;
  padding: 0.1rem 0.5rem; font-size: var(--el-fs-xs); font-weight: 600;
}
.count-pill.ghost { background: var(--el-bg-3); color: var(--el-ink-2); }

.note {
  font-size: var(--el-fs-sm); color: var(--el-ink-2); line-height: var(--el-lh);
  background: var(--el-bg-2); border-radius: var(--el-radius-sm);
  padding: var(--el-s3); margin-bottom: var(--el-s4);
}
.hint { font-size: var(--el-fs-xs); color: var(--el-ink-4); line-height: 1.5; margin: var(--el-s1) 0 var(--el-s2); }
.muted { color: var(--el-ink-4); font-size: var(--el-fs-sm); }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

.issued {
  border: 1px solid var(--el-line); border-left: 3px solid var(--el-accent);
  border-radius: var(--el-radius-sm); padding: var(--el-s3);
  margin-bottom: var(--el-s3); font-size: var(--el-fs-sm); line-height: var(--el-lh);
}
.creds { display: flex; flex-wrap: wrap; gap: var(--el-s2) var(--el-s5); margin: var(--el-s2) 0; }
.creds dt { font-size: var(--el-fs-xs); color: var(--el-ink-3); }
.creds code { font-family: ui-monospace, monospace; word-break: break-all; }
.creds .pw { font-weight: 700; }
.slugs { display: block; font-size: var(--el-fs-xs); color: var(--el-ink-3); }

.request {
  border: 1px solid var(--el-line); border-radius: var(--el-radius-sm);
  padding: var(--el-s4); margin-bottom: var(--el-s3);
  display: flex; flex-direction: column; gap: var(--el-s3);
}
.request-head {
  display: flex; justify-content: space-between;
  align-items: baseline; gap: var(--el-s4); flex-wrap: wrap;
}
.who { display: flex; align-items: baseline; gap: var(--el-s2); flex-wrap: wrap; }
.who .email {
  color: var(--el-ink-3); font-size: var(--el-fs-sm); text-decoration: none;
  overflow-wrap: anywhere;   /* a long institutional address must not widen the card */
}
.who .email:hover { text-decoration: underline; }
.submitted { font-size: var(--el-fs-xs); color: var(--el-ink-4); }

.decide { display: flex; gap: var(--el-s2); flex-wrap: wrap; }
.act { font-weight: 600; font-size: var(--el-fs-sm); }
.act.danger { color: var(--el-danger); border-color: #fecaca; }
.act.danger:hover:not(:disabled) { background: #fef2f2; }

.note-input {
  width: 100%;
  min-height: var(--el-touch);
  padding: var(--el-s2) var(--el-s3);
  border: 1px solid var(--el-line-2); border-radius: var(--el-radius-sm);
  font-size: 16px; font-family: inherit; color: var(--el-ink);
}
.note-input:focus {
  outline: none; border-color: var(--el-accent);
  box-shadow: 0 0 0 3px rgba(17, 24, 39, 0.08);
}

.row-error {
  font-size: var(--el-fs-xs); color: var(--el-danger);
  margin-top: var(--el-s1);
}

.experts-table { width: 100%; border-collapse: collapse; font-size: var(--el-fs-base); }
.experts-table th {
  text-align: left; padding: var(--el-s2); border-bottom: 2px solid var(--el-line);
  color: var(--el-ink-3); font-size: var(--el-fs-xs);
  text-transform: uppercase; letter-spacing: 0.03em;
}
.experts-table th.num, .experts-table td.num { text-align: right; }
.experts-table td {
  padding: var(--el-s3) var(--el-s2);
  border-bottom: 1px solid var(--el-bg-3); vertical-align: middle;
  overflow-wrap: anywhere;
}
.actions-cell { text-align: right; }

.role-pill {
  display: inline-block; padding: 0.15rem 0.5rem; margin: 0 0.2rem 0.2rem 0;
  border-radius: 999px; font-size: var(--el-fs-xs); font-weight: 600;
  border: 1px solid var(--el-line); color: var(--el-ink-3); background: var(--el-bg-2);
}

/* Tier is the most consequential fact on this screen, so the two values must be
   distinguishable to every reader. The previous blue/purple pair failed CVD
   validation at ΔE 2.0 (deutan) — indistinguishable. Blue/amber validates at
   ΔE 30.0 protan, 35.3 normal, and each badge also carries its own word, so
   identity never rests on colour alone. */
.tier-badge {
  display: inline-flex; align-items: center; gap: var(--el-s1);
  padding: 0.15rem 0.55rem; border-radius: 999px;
  font-size: var(--el-fs-xs); font-weight: 600;
  border: 1px solid transparent;
}
.tier-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.tier-badge.panel { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }
.tier-badge.contributor { background: #fffbeb; color: #b45309; border-color: #fde68a; }

.status-badge {
  padding: 0.15rem 0.55rem; border-radius: 999px;
  font-size: var(--el-fs-xs); font-weight: 600;
}
.status-badge.active { background: var(--el-ok-bg); color: var(--el-ok-ink); }
.status-badge.off { background: var(--el-bg-3); color: var(--el-ink-4); }
.via-role { font-size: var(--el-fs-xs); color: var(--el-ink-4); margin-left: var(--el-s1); }

.panel-coverage { margin-bottom: var(--el-s4); }
.pc-head {
  display: flex; justify-content: space-between;
  align-items: baseline; gap: var(--el-s4); flex-wrap: wrap;
}
.pc-title {
  font-size: var(--el-fs-xs); color: var(--el-ink-3);
  text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;
}
.pc-value { font-size: var(--el-fs-sm); color: var(--el-ink-2); }
.pc-value b { color: var(--el-ink); font-size: var(--el-fs-base); }

/* Meter: thin mark, rounded data-end, anchored to the track baseline. Eases to
   its value rather than snapping, so a change between refreshes is visible. */
.bar-track {
  height: 8px; background: var(--el-bg-3);
  border-radius: 999px; margin-top: var(--el-s2); overflow: hidden;
}
.bar-fill {
  height: 100%; background: #1d4ed8;
  border-radius: 999px;
  transition: width var(--el-t-slow) var(--el-ease);
}
.pc-note { font-size: var(--el-fs-xs); color: var(--el-ink-4); margin-top: var(--el-s2); line-height: 1.5; }

.stat-row {
  display: flex; gap: var(--el-s6); flex-wrap: wrap;
  padding: var(--el-s3) 0; border-top: 1px solid var(--el-bg-3);
}
.stat { display: flex; flex-direction: column; min-width: 0; }
/* Values wear ink, not a series colour — the label carries the meaning. */
.stat-value { font-size: 1.3rem; font-weight: 700; color: var(--el-ink); }
.stat-label {
  font-size: var(--el-fs-xs); color: var(--el-ink-3);
  text-transform: uppercase; letter-spacing: 0.03em;
}

.rung-note {
  font-size: var(--el-fs-sm); color: var(--el-ink-2);
  line-height: var(--el-lh); padding-bottom: var(--el-s3);
}

.split {
  display: flex; gap: var(--el-s6); flex-wrap: wrap;
  border-top: 1px solid var(--el-bg-3); padding-top: var(--el-s3);
}
.col { flex: 1; min-width: 200px; }
.col-title {
  font-size: var(--el-fs-xs); color: var(--el-ink-4);
  text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;
}
.mini { list-style: none; margin-top: var(--el-s2); display: flex; flex-direction: column; gap: var(--el-s1); }
.mini li {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: var(--el-fs-sm); color: var(--el-ink-2); gap: var(--el-s4);
}
.mini li b { color: var(--el-ink); flex-shrink: 0; }
.mini.two-col {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--el-s1) var(--el-s5);
}
/* Stratum keys are long (category · task), so they wrap. The first cut of this
   truncated them and put the full name in a `title` — which is unreadable on
   the touch devices this has to work on, and invisible to a keyboard. */
.stratum-name { min-width: 0; line-height: 1.4; word-break: break-word; }

.strata { border-top: 1px solid var(--el-bg-3); padding-top: var(--el-s3); margin-top: var(--el-s3); }

/* A decided request leaving the list is the feedback that the decision landed. */
.row-enter-active, .row-leave-active {
  transition: opacity var(--el-t-slow) var(--el-ease),
              transform var(--el-t-slow) var(--el-ease);
}
.row-enter-from { opacity: 0; transform: translateY(-6px); }
.row-leave-to { opacity: 0; transform: translateX(12px); }
.row-leave-active { position: absolute; width: calc(100% - var(--el-s6) * 2); }

.count-enter-active, .count-leave-active { transition: opacity var(--el-t) var(--el-ease); }
.count-enter-from, .count-leave-to { opacity: 0; }

/* ── phone ─────────────────────────────────────────────────────────── */
@media (max-width: 720px) {
  .admin-experts-view { padding: var(--el-s4) var(--el-s3); gap: var(--el-s4); }

  /* The table becomes stacked cards. Each cell carries its own header via
     data-h, so nothing scrolls sideways and nothing needs pinch-zoom. */
  .experts-table, .experts-table tbody, .experts-table tr, .experts-table td {
    display: block; width: 100%;
  }
  .experts-table thead { display: none; }
  .experts-table tr {
    border: 1px solid var(--el-line); border-radius: var(--el-radius-sm);
    padding: var(--el-s3); margin-bottom: var(--el-s3);
  }
  .experts-table td {
    border: 0; padding: var(--el-s1) 0;
    display: flex; justify-content: space-between; align-items: baseline;
    gap: var(--el-s3); text-align: left;
    min-width: 0;
  }
  .experts-table td::before {
    content: attr(data-h);
    font-size: var(--el-fs-xs); color: var(--el-ink-4);
    text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;
    flex-shrink: 0;
  }
  .experts-table td.num { text-align: right; }
  /* Cells without a data-h get no label pseudo-element — an empty one still
     takes part in the flex row and squeezes the control beside it. */
  .experts-table td:not([data-h])::before { display: none; }
  .actions-cell {
    flex-direction: column; align-items: stretch;
    padding-top: var(--el-s2) !important;
  }
  .actions-cell .el-btn { width: 100%; }

  .decide { flex-direction: column; }
  .decide .el-btn { width: 100%; }

  .stat-row { gap: var(--el-s4); }
  .stat { flex: 1 1 42%; }
  .split { gap: var(--el-s4); }
  .mini.two-col { grid-template-columns: 1fr; }
  .row-leave-active { width: calc(100% - var(--el-s3) * 2); }
}
</style>
