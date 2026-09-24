<template>
  <div class="enrol-page">
    <div class="enrol-card">
      <!-- Submitted -------------------------------------------------- -->
      <div v-if="submitted" class="done">
        <span class="tick">✓</span>
        <h1>Request received</h1>
        <p>
          Thanks — your request is with the AdvanDEB administrators. They review
          each one by hand and assign a contribution tier, so it is not instant.
          You will hear back by email at <strong>{{ form.email }}</strong>.
        </p>
        <p class="muted">
          Nothing is active until then; your account cannot see or judge anything yet.
        </p>
      </div>

      <!-- Form ------------------------------------------------------- -->
      <form v-else class="form" @submit.prevent="submit">
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
            <label class="field">
              <span>Full name <em>*</em></span>
              <input v-model.trim="form.full_name" required autocomplete="name" />
            </label>
            <label class="field">
              <span>Email <em>*</em></span>
              <input v-model.trim="form.email" type="email" required autocomplete="email" />
            </label>
            <label class="field">
              <span>Affiliation <em>*</em></span>
              <input v-model.trim="form.affiliation" required
                     placeholder="Institution or organisation" />
            </label>
            <label class="field">
              <span>ORCID <small>optional</small></span>
              <input v-model.trim="form.orcid" placeholder="0000-0002-1825-0097" />
              <small class="hint">
                Used to check whether you authored any of the facts you would be judging.
              </small>
            </label>
          </div>
        </section>

        <section class="block">
          <h2>Your background</h2>
          <div class="grid">
            <label class="field">
              <span>Years working in the field <em>*</em></span>
              <input v-model.number="form.years_in_field" type="number" min="0" max="70" required />
            </label>
            <label class="field">
              <span>DEB-specific experience <em>*</em></span>
              <select v-model="form.deb_experience" required>
                <option value="">Choose…</option>
                <option value="none">None — I work in adjacent areas</option>
                <option value="reader">I read DEB work but do not use it</option>
                <option value="applied">I have applied DEB models</option>
                <option value="developer">I develop DEB theory or models</option>
              </select>
            </label>
          </div>
        </section>

        <section class="block">
          <h2>Familiarity by area</h2>
          <p class="hint block-hint">
            Rate only the areas you have a view on. Leaving one blank is a real
            answer, and a more useful one than a guess — these ratings decide
            which facts reach you.
          </p>
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
          <button type="submit" class="btn primary" :disabled="!valid || busy">
            {{ busy ? 'Sending…' : 'Request access' }}
          </button>
          <span v-if="error" class="error">{{ error }}</span>
          <router-link to="/login" class="back">Already have an account?</router-link>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import api from '@/utils/api'
import CategoryFamiliarity from '@/components/enrolment/CategoryFamiliarity.vue'

const submitted = ref(false)
const busy = ref(false)
const error = ref('')

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

const valid = computed(() =>
  !!form.full_name && !!form.email && !!form.affiliation &&
  form.years_in_field !== null && !!form.deb_experience)

async function submit() {
  if (!valid.value) return
  busy.value = true
  error.value = ''
  try {
    await api.post('/enrolment/request', { ...form })
    submitted.value = true
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not send the request. Please try again.'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.enrol-page {
  min-height: 100vh;
  background: #f9fafb;
  padding: 2.5rem 1rem;
  display: flex;
  justify-content: center;
  overflow-y: auto;
}

.enrol-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 2rem 2.25rem;
  max-width: 720px;
  width: 100%;
  height: fit-content;
}

h1 { font-size: 1.4rem; font-weight: 700; color: #111827; }
h2 { font-size: 0.95rem; font-weight: 600; color: #111827; margin-bottom: 0.7rem; }

.lede { color: #4b5563; line-height: 1.65; margin-top: 0.6rem; font-size: 0.92rem; }
.lede.small { font-size: 0.82rem; color: #9ca3af; }

.form { display: flex; flex-direction: column; gap: 1.6rem; }
.block { border-top: 1px solid #f3f4f6; padding-top: 1.2rem; }
.block-hint { margin-bottom: 0.8rem; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 0.9rem 1.2rem;
}

.field { display: flex; flex-direction: column; gap: 0.3rem; }
.field > span { font-size: 0.8rem; font-weight: 600; color: #4b5563; }
.field em { color: #dc2626; font-style: normal; }
.field small { font-weight: 400; color: #9ca3af; }
.field input, .field select {
  padding: 0.5rem 0.6rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 0.9rem;
  font-family: inherit;
}

.hint { font-size: 0.75rem; color: #9ca3af; line-height: 1.5; }

.consent {
  display: flex; gap: 0.6rem; align-items: flex-start;
  font-size: 0.85rem; color: #374151; line-height: 1.55; cursor: pointer;
}
.consent input { margin-top: 0.2rem; flex-shrink: 0; }

.actions { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }

.btn {
  padding: 0.55rem 1.2rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #fff;
  color: #374151;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: 600;
}
.btn.primary { background: #111827; border-color: #111827; color: #fff; }
.btn:disabled { background: #d1d5db; border-color: #d1d5db; cursor: not-allowed; }

.error { color: #b91c1c; font-size: 0.85rem; }
.back { margin-left: auto; font-size: 0.82rem; color: #6b7280; text-decoration: none; }
.back:hover { color: #374151; }

.done { text-align: center; display: flex; flex-direction: column; gap: 0.8rem; align-items: center; padding: 1.5rem 0; }
.tick { font-size: 2.5rem; color: #16a34a; }
.done p { color: #4b5563; line-height: 1.65; max-width: 46ch; }
.muted { color: #9ca3af; font-size: 0.85rem; }
</style>
