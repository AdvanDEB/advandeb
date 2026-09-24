<template>
  <div class="enrol-page">
    <div class="enrol-card el-card">
      <!-- Submitted ------------------------------------------------- -->
      <div v-if="submitted" class="done el-anim">
        <span class="tick" aria-hidden="true">✓</span>
        <h1>Request received</h1>
        <p>
          Thanks — your request is with the AdvanDEB administrators. They review
          each one by hand and assign a contribution tier, so it is not instant.
          You will hear back by email at <strong>{{ sentTo }}</strong>.
        </p>
        <p class="muted">
          Nothing is active until then; your account cannot see or judge anything yet.
        </p>
        <router-link to="/login" class="el-btn el-btn--ghost done-link">
          Go to sign in
        </router-link>
      </div>

      <!-- Form ------------------------------------------------------ -->
      <form v-else class="form" novalidate @submit.prevent="submit">
        <header>
          <h1>Join the stylized-fact elicitation</h1>
          <p class="lede">
            AdvanDEB is assembling expert judgments on the empirical regularities
            that underpin Dynamic Energy Budget theory — where each one came from,
            what it ranges over, and what the literature actually says about it.
          </p>
          <p class="lede">
            Your judgments are <strong>attributed to you and creditable</strong>.
            Contributions are recorded against your name, and you choose below
            whether you want to be acknowledged in resulting publications.
          </p>
          <p class="lede small">
            Takes about two minutes. An administrator reviews every request.
          </p>
        </header>

        <section class="block">
          <h2>Who you are</h2>
          <div class="grid">
            <label class="field" :class="{ bad: showErr('full_name') }">
              <span>Full name <em aria-hidden="true">*</em></span>
              <input
                v-model.trim="form.full_name"
                autocomplete="name"
                autocapitalize="words"
                :aria-invalid="showErr('full_name')"
                @blur="touch('full_name')"
              />
              <small v-if="showErr('full_name')" class="err">{{ errors.full_name }}</small>
            </label>

            <label class="field" :class="{ bad: showErr('email') }">
              <span>Email <em aria-hidden="true">*</em></span>
              <input
                v-model.trim="form.email"
                type="email"
                inputmode="email"
                autocomplete="email"
                autocapitalize="none"
                spellcheck="false"
                :aria-invalid="showErr('email')"
                @blur="touch('email')"
              />
              <small v-if="showErr('email')" class="err">{{ errors.email }}</small>
            </label>

            <label class="field" :class="{ bad: showErr('affiliation') }">
              <span>Affiliation <em aria-hidden="true">*</em></span>
              <input
                v-model.trim="form.affiliation"
                autocomplete="organization"
                placeholder="Institution or organisation"
                :aria-invalid="showErr('affiliation')"
                @blur="touch('affiliation')"
              />
              <small v-if="showErr('affiliation')" class="err">{{ errors.affiliation }}</small>
            </label>

            <label class="field" :class="{ bad: showErr('orcid') }">
              <span>ORCID <small class="opt">optional</small></span>
              <input
                v-model.trim="form.orcid"
                inputmode="numeric"
                autocapitalize="characters"
                spellcheck="false"
                placeholder="0000-0002-1825-0097"
                :aria-invalid="showErr('orcid')"
                @blur="touch('orcid')"
              />
              <small v-if="showErr('orcid')" class="err">{{ errors.orcid }}</small>
              <small v-else class="hint">
                Used to check whether you authored any of the facts you would be judging.
              </small>
            </label>
          </div>
        </section>

        <section class="block">
          <h2>Your background</h2>
          <div class="grid">
            <label class="field" :class="{ bad: showErr('years_in_field') }">
              <span>Years working in the field <em aria-hidden="true">*</em></span>
              <input
                v-model.number="form.years_in_field"
                type="number"
                inputmode="numeric"
                min="0"
                max="70"
                :aria-invalid="showErr('years_in_field')"
                @blur="touch('years_in_field')"
              />
              <small v-if="showErr('years_in_field')" class="err">{{ errors.years_in_field }}</small>
            </label>

            <label class="field" :class="{ bad: showErr('deb_experience') }">
              <span>DEB-specific experience <em aria-hidden="true">*</em></span>
              <select
                v-model="form.deb_experience"
                :aria-invalid="showErr('deb_experience')"
                @blur="touch('deb_experience')"
              >
                <option value="">Choose…</option>
                <option value="none">None — I work in adjacent areas</option>
                <option value="reader">I read DEB work but do not use it</option>
                <option value="applied">I have applied DEB models</option>
                <option value="developer">I develop DEB theory or models</option>
              </select>
              <small v-if="showErr('deb_experience')" class="err">{{ errors.deb_experience }}</small>
            </label>
          </div>
        </section>

        <section class="block">
          <h2>Familiarity by area</h2>
          <CategoryFamiliarity v-model="form.category_familiarity" />
        </section>

        <section class="block">
          <label class="consent">
            <input type="checkbox" v-model="form.consent_acknowledgement" />
            <span>
              I consent to being acknowledged as a contributor in publications
              arising from this work, and to being considered for authorship where
              my contribution meets the criteria. You can withdraw this later.
            </span>
          </label>
        </section>

        <div class="actions">
          <button type="submit" class="el-btn el-btn--primary" :disabled="busy">
            {{ busy ? 'Sending…' : 'Request access' }}
          </button>

          <!-- A disabled button that will not say why is a dead end. The button
               stays live and the reason is stated instead. -->
          <span v-if="!valid && anyTouched" class="why">
            {{ missingSummary }}
          </span>

          <router-link to="/login" class="back">Already have an account?</router-link>
        </div>

        <p v-if="error" class="submit-error el-anim" role="alert">
          {{ error }}
          <button type="button" class="retry" @click="submit">Try again</button>
        </p>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import api from '@/utils/api'
import CategoryFamiliarity from '@/components/enrolment/CategoryFamiliarity.vue'
import { SF_CATEGORIES } from '@/components/enrolment/categories'

const submitted = ref(false)
const busy = ref(false)
const error = ref('')
const sentTo = ref('')

const form = reactive({
  full_name: '',
  email: '',
  affiliation: '',
  orcid: '',
  years_in_field: null as number | null,
  deb_experience: '',
  category_familiarity: {} as Record<string, number>,
  consent_acknowledgement: false,
})

type FieldKey = 'full_name' | 'email' | 'affiliation' | 'orcid'
  | 'years_in_field' | 'deb_experience'

const touched = reactive<Record<string, boolean>>({})
const attempted = ref(false)

function touch(k: FieldKey) { touched[k] = true }

const LABELS: Record<FieldKey, string> = {
  full_name: 'your name',
  email: 'your email',
  affiliation: 'your affiliation',
  orcid: 'ORCID',
  years_in_field: 'years in the field',
  deb_experience: 'DEB experience',
}

// Validation lives in one place and returns a message per field, so the form
// can put the reason beside the input rather than in a banner the user has to
// map back onto a field themselves.
const errors = computed<Partial<Record<FieldKey, string>>>(() => {
  const e: Partial<Record<FieldKey, string>> = {}
  if (!form.full_name) e.full_name = 'Please give your name.'
  if (!form.email) e.email = 'Please give an email address.'
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email))
    e.email = 'That does not look like an email address.'
  if (!form.affiliation) e.affiliation = 'Please give an institution or organisation.'
  if (form.years_in_field === null || form.years_in_field === undefined)
    e.years_in_field = 'Please give a number of years.'
  else if (form.years_in_field < 0 || form.years_in_field > 70)
    e.years_in_field = 'Please give a number between 0 and 70.'
  if (!form.deb_experience) e.deb_experience = 'Please choose one.'
  // ORCID is optional, but a malformed one is worse than none: it would be
  // matched against fact authorship and silently miss.
  if (form.orcid && !/^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/i.test(form.orcid))
    e.orcid = 'ORCID looks like 0000-0002-1825-0097.'
  return e
})

const valid = computed(() => Object.keys(errors.value).length === 0)
const anyTouched = computed(() => attempted.value || Object.keys(touched).length > 0)

function showErr(k: FieldKey) {
  return !!errors.value[k] && (touched[k] || attempted.value)
}

const missingSummary = computed(() => {
  const ks = Object.keys(errors.value) as FieldKey[]
  if (!ks.length) return ''
  const names = ks.map(k => LABELS[k])
  return names.length === 1
    ? `Still needed: ${names[0]}.`
    : `Still needed: ${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}.`
})

async function submit() {
  attempted.value = true
  if (!valid.value || busy.value) {
    // Put the first offending field in view rather than leaving the person
    // hunting for what the summary is referring to.
    const first = (Object.keys(errors.value) as FieldKey[])[0]
    if (first) {
      document.querySelector<HTMLElement>(`[aria-invalid="true"]`)?.focus()
    }
    return
  }
  busy.value = true
  error.value = ''
  try {
    // Only send categories that were actually rated; a picked-but-unrated area
    // is not a claim of expertise.
    const rated: Record<string, number> = {}
    for (const c of SF_CATEGORIES) {
      const v = form.category_familiarity[c.key]
      if (typeof v === 'number' && v > 0) rated[c.key] = v
    }
    await api.post('/enrolment/request', { ...form, category_familiarity: rated })
    sentTo.value = form.email
    submitted.value = true
  } catch (e: any) {
    error.value = readError(e)
  } finally {
    busy.value = false
  }
}

// FastAPI validation errors arrive as an array of objects; rendering that
// straight into the DOM produces "[object Object]".
function readError(e: any): string {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    const first = d[0]
    if (first?.msg) {
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : ''
      return field ? `${field}: ${first.msg}` : first.msg
    }
  }
  if (e?.response?.status === 429)
    return 'Too many requests from this address. Please wait a minute and try again.'
  if (e?.message === 'Network Error')
    return 'Could not reach the server. Check your connection and try again.'
  return 'Could not send the request. Please try again.'
}
</script>

<style scoped>
@import '@/styles/elicitation-tokens.css';

.enrol-page {
  /* dvh so a phone's collapsing URL bar does not clip the card */
  min-height: 100vh;
  min-height: 100dvh;
  background: var(--el-bg-2);
  padding: var(--el-s6) var(--el-s4);
  display: flex;
  justify-content: center;
}

.enrol-card {
  padding: var(--el-s6);
  max-width: 720px;
  width: 100%;
  height: fit-content;
}

h1 { font-size: var(--el-fs-xl); font-weight: 700; color: var(--el-ink); }
h2 {
  font-size: var(--el-fs-base); font-weight: 600;
  color: var(--el-ink); margin-bottom: var(--el-s3);
}

.lede {
  color: var(--el-ink-2); line-height: var(--el-lh);
  margin-top: var(--el-s2); font-size: var(--el-fs-base);
}
.lede.small { font-size: var(--el-fs-sm); color: var(--el-ink-4); }

.form { display: flex; flex-direction: column; gap: var(--el-s5); }
.block { border-top: 1px solid var(--el-line); padding-top: var(--el-s4); }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--el-s4);
}

.field { display: flex; flex-direction: column; gap: var(--el-s1); }
.field > span {
  font-size: var(--el-fs-sm); font-weight: 600; color: var(--el-ink-2);
}
.field em { color: var(--el-danger); font-style: normal; }
.opt { font-weight: 400; color: var(--el-ink-4); }

/* 16px minimum on every control: below that, iOS zooms the viewport on focus
   and the person has to pinch back out between fields. */
.field input, .field select {
  min-height: var(--el-touch);
  padding: var(--el-s2) var(--el-s3);
  border: 1px solid var(--el-line-2);
  border-radius: var(--el-radius-sm);
  font-size: 16px;
  font-family: inherit;
  color: var(--el-ink);
  background: var(--el-bg);
  transition: border-color var(--el-t) var(--el-ease),
              box-shadow var(--el-t) var(--el-ease);
}
.field input:focus, .field select:focus {
  outline: none;
  border-color: var(--el-accent);
  box-shadow: 0 0 0 3px rgba(17, 24, 39, 0.08);
}
.field.bad input, .field.bad select { border-color: var(--el-danger); }

.hint { font-size: var(--el-fs-xs); color: var(--el-ink-4); line-height: 1.5; }
.err { font-size: var(--el-fs-xs); color: var(--el-danger); line-height: 1.5; }

.consent {
  display: flex; gap: var(--el-s3); align-items: flex-start;
  font-size: var(--el-fs-sm); color: var(--el-ink-2);
  line-height: 1.55; cursor: pointer;
  padding: var(--el-s2);
  margin: calc(var(--el-s2) * -1);
  border-radius: var(--el-radius-sm);
}
/* A default checkbox is ~13px. The label is the real target, but the box
   itself should still be hittable. */
.consent input {
  width: 22px; height: 22px;
  margin-top: 0.1rem; flex-shrink: 0;
  accent-color: var(--el-accent);
}

.actions {
  display: flex; align-items: center; gap: var(--el-s4);
  flex-wrap: wrap;
}
.why { font-size: var(--el-fs-sm); color: var(--el-danger); }

.back {
  margin-left: auto;
  font-size: var(--el-fs-sm); color: var(--el-ink-3);
  text-decoration: none;
  min-height: var(--el-touch);
  display: inline-flex; align-items: center;
  padding: 0 var(--el-s2);
}
.back:hover, .back:focus-visible { color: var(--el-ink-2); text-decoration: underline; }

.submit-error {
  display: flex; align-items: center; gap: var(--el-s3); flex-wrap: wrap;
  font-size: var(--el-fs-sm); color: var(--el-danger);
  background: #fef2f2; border: 1px solid #fecaca;
  border-radius: var(--el-radius-sm); padding: var(--el-s3);
}
.retry {
  min-height: var(--el-touch); padding: 0 var(--el-s3);
  border: 1px solid #fecaca; border-radius: var(--el-radius-sm);
  background: var(--el-bg); color: var(--el-danger);
  font-size: var(--el-fs-sm); font-weight: 600; cursor: pointer;
}

.done {
  text-align: center; display: flex; flex-direction: column;
  gap: var(--el-s3); align-items: center; padding: var(--el-s5) 0;
}
.tick {
  font-size: 2.5rem; color: var(--el-ok-ink);
  width: 4rem; height: 4rem; line-height: 4rem;
  border-radius: 50%; background: var(--el-ok-bg);
  animation: tick-in var(--el-t-slow) var(--el-ease) both;
}
@keyframes tick-in {
  from { opacity: 0; transform: scale(0.8); }
  to   { opacity: 1; transform: none; }
}
.done p { color: var(--el-ink-2); line-height: var(--el-lh); max-width: 46ch; }
.done-link { display: inline-flex; align-items: center; margin-top: var(--el-s2); }
.muted { color: var(--el-ink-4); font-size: var(--el-fs-sm); }

@media (max-width: 720px) {
  .enrol-page { padding: var(--el-s4) var(--el-s3); }
  .enrol-card { padding: var(--el-s4); }
  .grid { grid-template-columns: 1fr; gap: var(--el-s3); }
  .actions { gap: var(--el-s3); }
  .actions .el-btn { width: 100%; }
  .back { margin-left: 0; }
}
</style>
