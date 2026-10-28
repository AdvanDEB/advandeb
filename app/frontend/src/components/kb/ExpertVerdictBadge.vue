<template>
  <span v-if="summary?.withheld" class="ev-badge ev-badge--withheld" :title="WITHHELD_TEXT">
    Hidden<span class="sr-only"> while you may still judge this fact</span>
  </span>
  <span
    v-else-if="headline && text"
    :class="['ev-badge', `ev-badge--${verdictKey(headline.group)}`, { 'ev-badge--contributors': headline.contributorsOnly }]"
    :title="headline.contributorsOnly ? 'Contributors only — no panel verdict yet' : undefined"
  >{{ text }}</span>
  <span v-else class="ev-none"><span aria-hidden="true">—</span><span class="sr-only">No expert verdict</span></span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ExpertVerdictSummary } from '@/types/expertVerdict.generated'
import { DEFAULT_MIN_N, WITHHELD_TEXT, badgeText, pickHeadline, verdictKey } from './expertVerdict'

const props = withDefaults(
  defineProps<{ summary?: ExpertVerdictSummary | null; minN?: number }>(),
  { summary: null, minN: DEFAULT_MIN_N },
)

const headline = computed(() => pickHeadline(props.summary, props.minN))
const text = computed(() => badgeText(props.summary, props.minN))
</script>

<style scoped>
.ev-badge {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 500;
  border-radius: 4px;
  padding: 0.1rem 0.4rem;
  white-space: nowrap;
  border: 1px solid transparent;
}
.ev-badge--supported { background: #dcfce7; color: #166534; }
.ev-badge--inconclusive { background: #f3f4f6; color: #374151; }
.ev-badge--against { background: #fee2e2; color: #991b1b; }
.ev-badge--split { background: #fef9c3; color: #713f12; }
/* Contributors stand in only when no panel group qualifies: muted, outlined. */
.ev-badge--contributors { background: transparent; color: #6b7280; border-color: #d1d5db; font-weight: 400; }
.ev-badge--withheld { background: transparent; color: #6b7280; border-color: #e5e7eb; border-style: dashed; font-weight: 400; }
.ev-none { color: #9ca3af; font-size: 0.8rem; }
</style>
