<template>
  <div class="familiarity">
    <!-- Step 1 — pick the areas.
         Twelve stacked 1–5 scales is the obvious control and the wrong one: on a
         390px screen it is twelve rows of five targets, and most people have a
         view on three or four areas. Selecting first turns the common case into
         ~3 taps plus ~3 ratings instead of 12 decisions. -->
    <fieldset class="pick">
      <legend class="legend-title">
        Which areas do you have a view on?
        <span class="count" :class="{ some: selected.length }">
          {{ selected.length }} selected
        </span>
      </legend>

      <div class="chips">
        <button
          v-for="cat in SF_CATEGORIES"
          :key="cat.key"
          type="button"
          class="chip"
          :class="{ on: isSelected(cat.key) }"
          :aria-pressed="isSelected(cat.key)"
          @click="toggle(cat.key)"
        >
          <span class="chip-tick" aria-hidden="true">{{ isSelected(cat.key) ? '✓' : '+' }}</span>
          {{ cat.label }}
        </button>
      </div>

      <p class="skip-note">
        Leaving an area out is a real answer, and a more useful one than a guess —
        these ratings decide which facts reach you.
      </p>
    </fieldset>

    <!-- Step 2 — rate only what was picked. -->
    <TransitionGroup v-if="selected.length" name="rate" tag="div" class="rates">
      <div v-for="cat in selectedCats" :key="cat.key" class="rate-row">
        <div class="rate-head">
          <span class="rate-label">{{ cat.label }}</span>
          <button
            type="button"
            class="drop"
            :aria-label="`Remove ${cat.label}`"
            @click="toggle(cat.key)"
          >×</button>
        </div>

        <div class="scale" role="radiogroup" :aria-label="`Familiarity with ${cat.label}`">
          <button
            v-for="n in 5"
            :key="n"
            type="button"
            role="radio"
            class="step"
            :class="{ on: modelValue[cat.key] === n }"
            :aria-checked="modelValue[cat.key] === n"
            :aria-label="`${n} — ${FAMILIARITY_LABELS[n]}`"
            @click="set(cat.key, n)"
          >
            <span class="step-n">{{ n }}</span>
          </button>
        </div>

        <!-- The anchor is shown as text, not a tooltip: a `title` attribute is
             invisible on a touch device, which is where this form gets filled. -->
        <p class="anchor" :class="{ unset: !modelValue[cat.key] }">
          {{ modelValue[cat.key]
            ? FAMILIARITY_LABELS[modelValue[cat.key]]
            : 'Not yet rated' }}
        </p>
      </div>
    </TransitionGroup>

    <p class="legend">
      <strong>1</strong> {{ FAMILIARITY_LABELS[1] }}
      <span aria-hidden="true">·</span>
      <strong>3</strong> {{ FAMILIARITY_LABELS[3] }}
      <span aria-hidden="true">·</span>
      <strong>5</strong> {{ FAMILIARITY_LABELS[5] }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { FAMILIARITY_LABELS, SF_CATEGORIES } from './categories'

const props = defineProps<{ modelValue: Record<string, number> }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: Record<string, number>): void }>()

// Selection is local: an area can be picked before it is rated, and a rated
// area is necessarily picked. Seeded from the model so the control survives a
// remount with values already present.
const picked = ref<string[]>(Object.keys(props.modelValue || {}))

const selected = computed(() => picked.value)
const selectedCats = computed(() =>
  SF_CATEGORIES.filter(c => picked.value.includes(c.key)))

function isSelected(key: string) {
  return picked.value.includes(key)
}

function toggle(key: string) {
  if (isSelected(key)) {
    picked.value = picked.value.filter(k => k !== key)
    // Dropping an area clears its rating — leaving a stale number behind would
    // submit expertise the person just withdrew.
    if (props.modelValue[key] !== undefined) {
      const next = { ...props.modelValue }
      delete next[key]
      emit('update:modelValue', next)
    }
  } else {
    picked.value = [...picked.value, key]
  }
}

function set(key: string, n: number) {
  const next = { ...props.modelValue }
  if (next[key] === n) delete next[key]   // tapping the active value clears it
  else next[key] = n
  emit('update:modelValue', next)
}
</script>

<style scoped>
@import '@/styles/elicitation-tokens.css';

.familiarity { display: flex; flex-direction: column; gap: var(--el-s4); }

.pick { border: 0; padding: 0; margin: 0; }
.legend-title {
  display: flex; align-items: baseline; gap: var(--el-s2); flex-wrap: wrap;
  font-size: var(--el-fs-sm); font-weight: 600; color: var(--el-ink-2);
  padding: 0; margin-bottom: var(--el-s3);
}
.count {
  font-size: var(--el-fs-xs); font-weight: 600;
  color: var(--el-ink-4); background: var(--el-bg-3);
  border-radius: 999px; padding: 0.1rem 0.5rem;
  transition: background var(--el-t) var(--el-ease), color var(--el-t) var(--el-ease);
}
.count.some { background: var(--el-info-bg); color: var(--el-info-ink); }

.chips { display: flex; flex-wrap: wrap; gap: var(--el-s2); }

.chip {
  display: inline-flex; align-items: center; gap: var(--el-s2);
  min-height: var(--el-touch);
  padding: var(--el-s2) var(--el-s3);
  border: 1px solid var(--el-line-2);
  border-radius: var(--el-radius-sm);
  background: var(--el-bg);
  color: var(--el-ink-2);
  font-size: var(--el-fs-sm);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--el-t) var(--el-ease),
              border-color var(--el-t) var(--el-ease),
              color var(--el-t) var(--el-ease);
}
.chip:focus-visible { outline: 2px solid var(--el-accent); outline-offset: 2px; }
.chip.on {
  background: var(--el-accent); border-color: var(--el-accent); color: #fff;
  font-weight: 600;
}
.chip-tick {
  font-size: var(--el-fs-xs); opacity: 0.65;
  width: 0.9em; flex-shrink: 0;
}
.chip.on .chip-tick { opacity: 1; }

.skip-note {
  font-size: var(--el-fs-xs); color: var(--el-ink-4);
  line-height: 1.5; margin-top: var(--el-s3);
}

.rates { display: flex; flex-direction: column; gap: var(--el-s3); }

.rate-row {
  border: 1px solid var(--el-line);
  border-radius: var(--el-radius-sm);
  padding: var(--el-s3);
  background: var(--el-bg-2);
}
.rate-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--el-s2); margin-bottom: var(--el-s2);
}
.rate-label { font-size: var(--el-fs-sm); font-weight: 600; color: var(--el-ink); }

.drop {
  width: var(--el-touch); height: var(--el-touch);
  flex-shrink: 0; margin: calc(var(--el-s2) * -1) calc(var(--el-s2) * -1) 0 0;
  border: 0; background: none; cursor: pointer;
  color: var(--el-ink-4); font-size: 1.25rem; line-height: 1;
  border-radius: var(--el-radius-sm);
  transition: color var(--el-t) var(--el-ease), background var(--el-t) var(--el-ease);
}
.drop:hover, .drop:focus-visible { color: var(--el-ink-2); background: var(--el-bg-3); }

/* Five targets that fill the row: at 360px each is ~62px wide and 44px tall,
   comfortably above the platform minimum and easy to hit with a thumb. */
.scale { display: flex; gap: var(--el-s1); }
.step {
  flex: 1;
  min-height: var(--el-touch);
  border: 1px solid var(--el-line-2);
  border-radius: var(--el-radius-sm);
  background: var(--el-bg);
  color: var(--el-ink-3);
  font-size: var(--el-fs-base);
  font-family: inherit;
  cursor: pointer;
  transition: background var(--el-t) var(--el-ease),
              border-color var(--el-t) var(--el-ease),
              color var(--el-t) var(--el-ease);
}
.step:focus-visible { outline: 2px solid var(--el-accent); outline-offset: 2px; }
.step.on {
  background: var(--el-accent); border-color: var(--el-accent);
  color: #fff; font-weight: 700;
}
.step-n { pointer-events: none; }

.anchor {
  font-size: var(--el-fs-xs); color: var(--el-ink-2);
  margin-top: var(--el-s2); min-height: 1.1em;
}
.anchor.unset { color: var(--el-ink-4); font-style: italic; }

.legend {
  font-size: var(--el-fs-xs); color: var(--el-ink-4);
  line-height: 1.6; border-top: 1px solid var(--el-line); padding-top: var(--el-s3);
}
.legend strong { color: var(--el-ink-2); }

/* A rated area appearing or leaving is a state change worth showing — it is
   what tells you the tap registered. */
.rate-enter-active, .rate-leave-active {
  transition: opacity var(--el-t) var(--el-ease),
              transform var(--el-t) var(--el-ease);
}
.rate-enter-from { opacity: 0; transform: translateY(-4px); }
.rate-leave-to { opacity: 0; transform: translateY(-4px); }
.rate-leave-active { position: absolute; }
</style>
