<template>
  <section :class="['ev-detail', { 'ev-detail--dark': dark }]" aria-label="Expert verdict">
    <div class="ev-title">Expert verdict</div>

    <p v-if="loading" class="ev-muted">Loading…</p>
    <p v-else-if="summary?.withheld" class="ev-muted ev-withheld">{{ WITHHELD_TEXT }}</p>
    <template v-else-if="sections.length">
      <p class="ev-about">{{ ABOUT_TEXT }}</p>
      <div v-for="section in sections" :key="section.corpusId" class="ev-corpus">
        <div class="ev-corpus-name">{{ section.name }}</div>
        <div
          v-for="group in section.groups"
          :key="group.tier"
          :class="['ev-group', `ev-group--${group.tier}`]"
        >
          <div class="ev-line">
            <span v-if="group.tier === 'contributor'" class="ev-tier">{{ CONTRIBUTORS_LABEL }}:</span>
            <span :class="['ev-verdict', `ev-verdict--${verdictKey(group)}`]">{{ groupLine(group) }}</span>
          </div>
          <div class="ev-dist">
            <span class="ev-dist-name">Consensus</span>
            <span class="ev-bar" aria-hidden="true">
              <span
                v-for="p in consensusParts(group)"
                v-show="p.n > 0"
                :key="p.key"
                :class="['ev-seg', `ev-seg--${p.key}`]"
                :style="{ flexGrow: p.n }"
              />
            </span>
            <span class="ev-dist-text">{{ distributionText(consensusParts(group)) }}</span>
          </div>
          <div class="ev-dist">
            <span class="ev-dist-name">Strength</span>
            <span class="ev-bar" aria-hidden="true">
              <span
                v-for="p in strengthParts(group)"
                v-show="p.n > 0"
                :key="p.key"
                :class="['ev-seg', `ev-seg--${p.key}`]"
                :style="{ flexGrow: p.n }"
              />
            </span>
            <span class="ev-dist-text">
              {{ distributionText(strengthParts(group)) }}<template v-if="strengthMedianLabel(group)"> · median {{ strengthMedianLabel(group) }}</template>
            </span>
          </div>
        </div>
      </div>
    </template>
    <p v-else class="ev-muted"><span aria-hidden="true">—</span><span class="sr-only">No expert verdict</span></p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ExpertVerdictSummary } from '@/types/expertVerdict.generated'
import {
  ABOUT_TEXT, CONTRIBUTORS_LABEL, DEFAULT_MIN_N, WITHHELD_TEXT,
  consensusParts, corpusSections, distributionText, groupLine,
  strengthMedianLabel, strengthParts, verdictKey,
} from './expertVerdict'

const props = withDefaults(
  defineProps<{
    summary?: ExpertVerdictSummary | null
    minN?: number
    loading?: boolean
    /** For dark panels (the graph node inspector). */
    dark?: boolean
  }>(),
  { summary: null, minN: DEFAULT_MIN_N, loading: false, dark: false },
)

const sections = computed(() => corpusSections(props.summary, props.minN))
</script>

<style scoped>
.ev-detail {
  --ev-text: #111827;
  --ev-muted: #6b7280;
  --ev-label: #9ca3af;
  --ev-track: #f3f4f6;
  --ev-against: #dc2626;
  --ev-inconclusive: #9ca3af;
  --ev-supported: #16a34a;
  --ev-weak: #c7d2fe;
  --ev-moderate: #818cf8;
  --ev-strong: #4338ca;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.8rem;
  color: var(--ev-text);
}
.ev-detail--dark {
  --ev-text: #cbd5e1;
  --ev-muted: #94a3b8;
  --ev-label: #64748b;
  --ev-track: #334155;
  --ev-against: #f87171;
  --ev-inconclusive: #64748b;
  --ev-supported: #4ade80;
  --ev-weak: #475569;
  --ev-moderate: #818cf8;
  --ev-strong: #c7d2fe;
}

.ev-title {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ev-label);
}
.ev-about { margin: 0; font-size: 0.75rem; color: var(--ev-muted); line-height: 1.45; }
.ev-muted { margin: 0; color: var(--ev-muted); font-size: 0.78rem; }

.ev-corpus { display: flex; flex-direction: column; gap: 0.3rem; }
.ev-corpus + .ev-corpus { margin-top: 0.25rem; }
.ev-corpus-name { font-size: 0.75rem; font-weight: 600; }

.ev-group { display: flex; flex-direction: column; gap: 0.15rem; padding-left: 0.6rem; border-left: 2px solid var(--ev-track); }
.ev-group--contributor { opacity: 0.85; }
.ev-line { display: flex; flex-wrap: wrap; gap: 0.3rem; align-items: baseline; }
.ev-tier { color: var(--ev-muted); font-size: 0.75rem; }
.ev-verdict { font-weight: 600; }
.ev-group--contributor .ev-verdict { font-weight: 500; }

.ev-dist { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; font-size: 0.72rem; color: var(--ev-muted); }
.ev-dist-name { min-width: 4.6rem; }
.ev-bar {
  display: inline-flex;
  width: 64px;
  height: 6px;
  border-radius: 3px;
  overflow: hidden;
  background: var(--ev-track);
  flex-shrink: 0;
}
.ev-seg { display: block; height: 100%; flex-basis: 0; }
.ev-seg + .ev-seg { margin-left: 1px; }
.ev-seg--against { background: var(--ev-against); }
.ev-seg--inconclusive { background: var(--ev-inconclusive); }
.ev-seg--supported { background: var(--ev-supported); }
.ev-seg--weak { background: var(--ev-weak); }
.ev-seg--moderate { background: var(--ev-moderate); }
.ev-seg--strong { background: var(--ev-strong); }
</style>
