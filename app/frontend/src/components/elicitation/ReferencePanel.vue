<template>
  <section class="refs" :class="{ prominent }">
    <button type="button" class="disclose" :aria-expanded="isOpen" @click="open = !isOpen">
      {{ isOpen ? '▾' : '▸' }}
      {{ prominent ? 'Add the reference you are relying on' : 'Add a reference from your own knowledge' }}
      <span v-if="refs.length" class="count">{{ refs.length }}</span>
      <span class="hint">— optional, by DOI</span>
    </button>

    <div v-if="isOpen" class="body">
      <p class="lede">
        A paper you know that supports or opposes this fact. It is recorded as
        your reference and goes to a curator, who decides whether it becomes
        evidence in the knowledge base. It never changes any score.
      </p>

      <div class="form">
        <label class="sr-only" :for="`doi-${uid}`">DOI</label>
        <input
          :id="`doi-${uid}`"
          v-model="doi"
          class="doi"
          placeholder="10.1234/abc or https://doi.org/10.1234/abc"
          :disabled="saving"
          @keydown.enter.prevent="submit"
        />
        <div class="dir" role="group" aria-label="The paper">
          <button
            v-for="d in directions" :key="d.value" type="button"
            :class="['pill', { active: direction === d.value }]"
            :aria-pressed="direction === d.value"
            :disabled="saving"
            @click="direction = d.value"
          >{{ d.label }}</button>
        </div>
      </div>
      <label class="sr-only" :for="`note-${uid}`">Why it bears on this fact</label>
      <input
        :id="`note-${uid}`"
        v-model="note"
        class="note"
        placeholder="Optional — why does it bear on this fact?"
        :disabled="saving"
      />
      <div class="actions">
        <button type="button" class="primary" :disabled="!canSubmit || saving" @click="submit">
          {{ saving ? 'Checking the DOI…' : 'Add reference' }}
        </button>
        <span v-if="err" class="err" role="alert">{{ err }}</span>
      </div>

      <ul v-if="refs.length" class="list">
        <li v-for="r in refs" :key="r._id" class="ref">
          <div class="ref-head">
            <span :class="['dirbadge', r.direction]">{{ r.direction }}</span>
            <a :href="'https://doi.org/' + r.doi" target="_blank" rel="noopener"
               class="doi-link">{{ r.doi }}</a>
            <button type="button" class="rm" :aria-label="`Remove ${r.doi}`" @click="remove(r._id)">×</button>
          </div>
          <div v-if="r.resolution && r.resolution.resolved_title" class="title">
            {{ r.resolution.resolved_title }}
            <span v-if="r.resolution.resolved_year">({{ r.resolution.resolved_year }})</span>
          </div>
          <div class="status">
            {{ statusLabel(r.resolution && r.resolution.status) }}
            · {{ curationLabel(r.curation && r.curation.status) }}
          </div>
          <div v-if="r.note" class="note-shown">“{{ r.note }}”</div>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import api from '@/utils/api'

const props = defineProps<{
  sfNumber: number
  statementSha256: string
  /** Open, and worded for it, when the expert says their judgment goes
   *  beyond the passages — the moment a reference is most worth adding. */
  prominent?: boolean
}>()
const emit = defineEmits<{ (e: 'changed', ids: string[]): void }>()

const uid = Math.random().toString(36).slice(2, 8)
const open = ref<boolean | null>(null)
const isOpen = computed(() => open.value ?? !!props.prominent)
const doi = ref('')
const direction = ref<'supports' | 'opposes'>('supports')
const note = ref('')
const saving = ref(false)
const err = ref('')
const refs = ref<any[]>([])

const directions = [
  { value: 'supports' as const, label: 'Supports' },
  { value: 'opposes' as const, label: 'Opposes' },
]

const canSubmit = computed(() => doi.value.trim().includes('/'))

// Where the paper stands, worded for the expert. Not what the machine made of
// it: that is another judge's answer, and the server no longer sends it.
const LABELS: Record<string, string> = {
  pending: 'Checking…',
  not_in_corpus: 'Not in our corpus yet',
  in_corpus_not_retrieved: 'In our corpus, but the search did not find it for this fact',
  in_corpus_retrieved: 'Already among the passages found for this fact',
  in_corpus_retrieval_unknown: 'In our corpus',
  unresolvable: 'Could not be resolved',
}
const CURATION: Record<string, string> = {
  pending: 'awaiting curator review',
  accepted: 'accepted by a curator',
  rejected: 'not accepted by a curator',
}

function statusLabel(s?: string | null) {
  return LABELS[s || 'pending'] || 'Checking…'
}
function curationLabel(s?: string | null) {
  return CURATION[s || 'pending'] || CURATION.pending
}

async function load() {
  if (!props.sfNumber) return
  try {
    const { data } = await api.get('/elicitation/references', {
      params: { sf_number: props.sfNumber, mine_only: true },
    })
    refs.value = data.references || []
  } catch {
    // Secondary to the judgment: a failure here must never block the form.
    refs.value = []
  }
  emit('changed', refs.value.map((r) => r._id))
}

async function submit() {
  if (!canSubmit.value) return
  saving.value = true
  err.value = ''
  try {
    await api.post('/elicitation/references', {
      sf_number: props.sfNumber,
      statement_sha256: props.statementSha256,
      doi: doi.value.trim(),
      direction: direction.value,
      note: note.value.trim() || null,
    })
    doi.value = ''
    note.value = ''
    await load()
  } catch (e: any) {
    err.value = (e && e.response && e.response.data && e.response.data.detail)
      || 'Could not add that reference'
  } finally {
    saving.value = false
  }
}

async function remove(id: string) {
  try {
    await api.delete('/elicitation/references/' + id)
    await load()
  } catch (e: any) {
    err.value = (e && e.response && e.response.data && e.response.data.detail)
      || 'Could not remove'
  }
}

watch(() => props.sfNumber,
      () => { refs.value = []; open.value = null; load() },
      { immediate: true })
</script>

<style scoped>
.refs { margin-top: 0.9rem; border-top: 1px solid #f3f4f6; padding-top: 0.6rem; }
.refs.prominent .disclose { color: #1f2937; font-weight: 600; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.disclose { background: none; border: none; cursor: pointer; font-size: 0.85rem; color: #4b5563; padding: 0.2rem 0; text-align: left; width: 100%; }
.disclose .hint { color: #9ca3af; }
.disclose .count { background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 0 0.4rem; font-size: 0.72rem; margin-left: 0.3rem; }
.body { margin-top: 0.7rem; }
.lede { font-size: 0.8rem; color: #6b7280; line-height: 1.5; margin-bottom: 0.6rem; }
.form { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
.doi { flex: 1 1 18rem; padding: 0.45rem 0.6rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.85rem; font-family: ui-monospace, monospace; }
.note { width: 100%; margin-top: 0.4rem; padding: 0.45rem 0.6rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.85rem; }
.dir { display: flex; gap: 0.25rem; }
.pill { border: 1px solid #d1d5db; background: #fff; border-radius: 6px; padding: 0.4rem 0.7rem; font-size: 0.82rem; cursor: pointer; }
.pill.active { background: #111827; color: #fff; border-color: #111827; }
.actions { display: flex; align-items: center; gap: 0.8rem; margin-top: 0.5rem; }
.primary { background: #374151; color: #fff; border: none; border-radius: 6px; padding: 0.42rem 0.9rem; font-size: 0.83rem; cursor: pointer; }
.primary:disabled { background: #d1d5db; cursor: not-allowed; }
.err { color: #b91c1c; font-size: 0.8rem; }
.list { list-style: none; margin-top: 0.8rem; display: flex; flex-direction: column; gap: 0.6rem; }
.ref { border: 1px solid #e5e7eb; border-radius: 8px; padding: 0.5rem 0.65rem; }
.ref-head { display: flex; align-items: center; gap: 0.5rem; }
.dirbadge { font-size: 0.7rem; font-weight: 600; border-radius: 4px; padding: 0.1rem 0.35rem; }
.dirbadge.supports { background: #dcfce7; color: #166534; }
.dirbadge.opposes { background: #fee2e2; color: #991b1b; }
.doi-link { font-size: 0.78rem; font-family: ui-monospace, monospace; color: #1d4ed8; text-decoration: none; }
.rm { margin-left: auto; background: none; border: none; cursor: pointer; color: #9ca3af; font-size: 1rem; }
.title { font-size: 0.85rem; color: #374151; margin-top: 0.25rem; }
.status { font-size: 0.75rem; margin-top: 0.3rem; color: #4b5563; }
.note-shown { font-size: 0.78rem; color: #6b7280; margin-top: 0.3rem; font-style: italic; }
</style>
