<template>
  <div class="profile">
    <!-- Tier assignment rests on these three, so they lead. -->
    <div class="headline">
      <div class="stat">
        <span class="stat-value">{{ profile.years_in_field ?? '—' }}</span>
        <span class="stat-label">years in field</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ profile.deb_experience ?? '—' }}</span>
        <span class="stat-label">DEB-specific experience</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ specialistCount }}</span>
        <span class="stat-label">categories rated 4–5</span>
      </div>
    </div>

    <dl class="meta">
      <div><dt>Affiliation</dt><dd>{{ profile.affiliation || '—' }}</dd></div>
      <div>
        <dt>ORCID</dt>
        <dd>
          <a v-if="profile.orcid" :href="`https://orcid.org/${profile.orcid}`" target="_blank" rel="noopener">
            {{ profile.orcid }}
          </a>
          <span v-else>—</span>
        </dd>
      </div>
      <div>
        <dt>Acknowledgement consent</dt>
        <dd>{{ profile.consent_acknowledgement ? 'Given' : 'Not given' }}</dd>
      </div>
    </dl>

    <!-- COI: an outsider's conflict is no less a conflict (docs/10 §5.1). -->
    <p v-if="authoredMatches.length" class="coi">
      <strong>Conflict of interest:</strong> matched to
      {{ authoredMatches.length }} authored stylized fact{{ authoredMatches.length === 1 ? '' : 's' }}
      ({{ authoredMatches.slice(0, 6).join(', ') }}<span v-if="authoredMatches.length > 6">…</span>).
      These will be excluded from their queue.
    </p>

    <div v-if="ratedCategories.length" class="cats">
      <span class="cats-title">Self-rated familiarity</span>
      <ul>
        <li v-for="c in ratedCategories" :key="c.key">
          <span class="bar" :style="{ width: `${c.value * 20}%` }"></span>
          <span class="cat-name">{{ c.label }}</span>
          <span class="cat-val">{{ c.value }}</span>
        </li>
      </ul>
    </div>
    <p v-else class="muted">No per-category familiarity submitted.</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { prettyCategory } from './categories'

interface Profile {
  affiliation?: string
  orcid?: string
  years_in_field?: number
  deb_experience?: string
  category_familiarity?: Record<string, number>
  consent_acknowledgement?: boolean
  authored_sf_numbers?: number[]
}

const props = defineProps<{ profile: Profile }>()

const ratedCategories = computed(() =>
  Object.entries(props.profile.category_familiarity || {})
    .map(([key, value]) => ({ key, value: Number(value), label: prettyCategory(key) }))
    .filter(c => c.value > 0)
    .sort((a, b) => b.value - a.value))

const specialistCount = computed(() =>
  ratedCategories.value.filter(c => c.value >= 4).length)

const authoredMatches = computed(() => props.profile.authored_sf_numbers || [])
</script>

<style scoped>
.profile { display: flex; flex-direction: column; gap: 0.9rem; }

.headline { display: flex; gap: 1.5rem; flex-wrap: wrap; }
.stat { display: flex; flex-direction: column; }
.stat-value { font-size: 1.15rem; font-weight: 700; color: #111827; }
.stat-label { font-size: 0.72rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.03em; }

.meta { display: flex; gap: 1.5rem; flex-wrap: wrap; font-size: 0.85rem; }
.meta dt { font-size: 0.7rem; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.03em; }
.meta dd { color: #374151; }
.meta a { color: #2563eb; }

.coi {
  font-size: 0.82rem;
  background: #fef3c7;
  color: #92400e;
  padding: 0.5rem 0.7rem;
  border-radius: 6px;
  line-height: 1.5;
}

.cats-title {
  font-size: 0.7rem; color: #9ca3af;
  text-transform: uppercase; letter-spacing: 0.03em;
}
.cats ul { list-style: none; margin-top: 0.4rem; display: flex; flex-direction: column; gap: 0.15rem; }
.cats li {
  position: relative;
  display: flex; align-items: center; gap: 0.5rem;
  font-size: 0.8rem; padding: 0.15rem 0.4rem; border-radius: 4px;
  overflow: hidden;
}
.bar {
  position: absolute; left: 0; top: 0; bottom: 0;
  background: #eff6ff; z-index: 0;
}
.cat-name { position: relative; z-index: 1; color: #374151; flex: 1; }
.cat-val { position: relative; z-index: 1; font-weight: 700; color: #1d4ed8; }

.muted { color: #9ca3af; font-size: 0.85rem; }
</style>
