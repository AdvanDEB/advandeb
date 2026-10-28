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
          <a
            v-if="profile.orcid"
            class="orcid-link"
            :href="`https://orcid.org/${profile.orcid}`"
            target="_blank"
            rel="noopener"
          >
            {{ profile.orcid }}
            <span class="ext" aria-hidden="true">↗</span>
            <span class="sr">(opens orcid.org in a new tab)</span>
          </a>
          <span v-else>—</span>
        </dd>
      </div>
      <div>
        <dt>Acknowledgement consent</dt>
        <dd>{{ profile.consent ? 'Given' : 'Not given' }}</dd>
      </div>
    </dl>

    <!-- COI: an outsider's conflict is no less a conflict (docs/10 §5.1).
         Amber is a status colour here, and it never carries the meaning alone —
         the banner is labelled in words. -->
    <p v-if="authoredMatches.length" class="coi">
      <strong>Conflict of interest:</strong> matched to
      {{ authoredMatches.length }} authored stylized fact{{ authoredMatches.length === 1 ? '' : 's' }}
      ({{ authoredMatches.slice(0, 6).join(', ') }}<span v-if="authoredMatches.length > 6">…</span>)<template
        v-if="profile.matched_author_slugs?.length"> as
        <code>{{ profile.matched_author_slugs.join(', ') }}</code></template>.
      These will be excluded from their queue.
    </p>

    <div v-if="ratedCategories.length" class="cats">
      <span class="cats-title">Self-rated familiarity</span>
      <!-- Magnitude on a 1–5 ordinal scale: width carries the value, and one
           blue hue steps light→dark alongside it so the 4s and 5s — the ones
           that decide tier — separate at a glance. The ramp stops well short of
           dark: the label sits on top of the fill and has to stay readable. -->
      <ul>
        <li v-for="c in ratedCategories" :key="c.key">
          <span
            class="bar"
            :style="{ width: `${c.value * 20}%`, background: RAMP[c.value] }"
          ></span>
          <span class="cat-name">{{ c.label }}</span>
          <span class="cat-val">{{ c.value }}</span>
        </li>
      </ul>
      <p class="cats-legend">
        1 not my area · 5 specialist. Unrated areas are not shown.
      </p>
    </div>
    <p v-else class="muted">No per-category familiarity submitted.</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { EnrolmentRequestRecord } from '@/types/enrolment.generated'
import { prettyCategory } from './categories'

// A request as the server serves it. The card read `consent_acknowledgement`
// and `authored_sf_numbers`, which a request does not carry, so it showed
// "Not given" and no conflict of interest for everyone.
type Profile = Pick<EnrolmentRequestRecord,
  'affiliation' | 'orcid' | 'years_in_field' | 'deb_experience'
  | 'category_familiarity' | 'consent' | 'matched_authored_sf_numbers'>
  & Partial<Pick<EnrolmentRequestRecord, 'matched_author_slugs'>>

const props = defineProps<{ profile: Profile }>()

// Sequential, one hue, light→dark. Capped at blue-200 so ink text keeps its
// contrast over the fill at every step.
// Steps fall monotonically in OKLab lightness (0.971 → 0.809) at roughly even
// intervals, so 4 and 5 — the two that decide tier — are told apart by the fill
// as well as by the width. The darkest step still carries the label at 5.7:1.
const RAMP: Record<number, string> = {
  1: '#f0f6ff', 2: '#dbeafe', 3: '#bfdbfe', 4: '#a7cdfc', 5: '#93c5fd',
}

const ratedCategories = computed(() =>
  Object.entries(props.profile.category_familiarity || {})
    .map(([key, value]) => ({ key, value: Number(value), label: prettyCategory(key) }))
    .filter(c => c.value > 0)
    .sort((a, b) => b.value - a.value))

const specialistCount = computed(() =>
  ratedCategories.value.filter(c => c.value >= 4).length)

const authoredMatches = computed(() => props.profile.matched_authored_sf_numbers || [])
</script>

<style scoped>
@import '@/styles/elicitation-tokens.css';

.profile { display: flex; flex-direction: column; gap: var(--el-s3); }

.headline { display: flex; gap: var(--el-s5); flex-wrap: wrap; }
.stat { display: flex; flex-direction: column; min-width: 0; }
/* Values wear ink. The label carries the meaning, not a colour. */
.stat-value { font-size: 1.15rem; font-weight: 700; color: var(--el-ink); }
.stat-label {
  font-size: var(--el-fs-xs); color: var(--el-ink-3);
  text-transform: uppercase; letter-spacing: 0.03em;
}

.meta {
  display: flex; gap: var(--el-s5); flex-wrap: wrap;
  font-size: var(--el-fs-sm);
}
.meta div { min-width: 0; }
.meta dt {
  font-size: var(--el-fs-xs); color: var(--el-ink-4);
  text-transform: uppercase; letter-spacing: 0.03em;
}
.meta dd { color: var(--el-ink-2); word-break: break-word; }

/* A tappable link needs a tappable target, and the arrow says it leaves the
   app before the tap rather than after it. */
.orcid-link {
  display: inline-flex; align-items: center; gap: var(--el-s1);
  min-height: var(--el-touch); padding-right: var(--el-s1);
  color: #1d4ed8; text-decoration: none;
}
.orcid-link:hover, .orcid-link:focus-visible { text-decoration: underline; }
.orcid-link:focus-visible { outline: 2px solid var(--el-accent); outline-offset: 2px; }
.ext { font-size: 0.7em; opacity: 0.7; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

.coi {
  font-size: var(--el-fs-sm);
  background: var(--el-warn-bg);
  color: var(--el-warn-ink);
  padding: var(--el-s2) var(--el-s3);
  border-radius: var(--el-radius-sm);
  line-height: var(--el-lh);
}

.cats-title {
  font-size: var(--el-fs-xs); color: var(--el-ink-4);
  text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;
}
.cats ul {
  list-style: none; margin-top: var(--el-s2);
  display: flex; flex-direction: column; gap: 2px;
}
.cats li {
  position: relative;
  display: flex; align-items: center; gap: var(--el-s2);
  font-size: var(--el-fs-sm);
  padding: var(--el-s1) var(--el-s2);
  border-radius: 4px;
  overflow: hidden;
  min-height: 26px;
}
.bar {
  position: absolute; left: 0; top: 0; bottom: 0;
  border-radius: 0 4px 4px 0;
  z-index: 0;
  transition: width var(--el-t-slow) var(--el-ease);
}
/* Wraps rather than truncates. "Universal laws of biological organization" is
   wider than a 360px card, and an ellipsis would have hidden the rest of it
   behind nothing at all — there was not even a tooltip to fall back to. */
.cat-name {
  position: relative; z-index: 1; color: var(--el-ink-2);
  flex: 1; min-width: 0; line-height: 1.35;
}
/* Ink, not the ramp colour — the bar beside it already carries identity. */
.cat-val { position: relative; z-index: 1; font-weight: 700; color: var(--el-ink); }

.cats-legend {
  font-size: var(--el-fs-xs); color: var(--el-ink-4);
  margin-top: var(--el-s2); line-height: 1.5;
}

.muted { color: var(--el-ink-4); font-size: var(--el-fs-sm); }

@media (max-width: 720px) {
  .headline, .meta { gap: var(--el-s4); }
  .headline .stat { flex: 1 1 44%; }
  .meta div { flex: 1 1 100%; }
}
</style>
