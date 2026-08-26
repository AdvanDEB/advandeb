<template>
  <div class="legend-wrap">
    <button
      class="legend-toggle"
      :class="{ open }"
      :title="open ? 'Hide layout notes' : 'What am I looking at?'"
      @click="open = !open"
    >{{ open ? '✕' : 'i' }}</button>

    <Transition name="legend-fade">
      <aside v-if="open" class="legend-card">
        <header class="legend-header">
          <h4 class="legend-title">{{ info.title }}</h4>
          <span class="legend-kind" :class="`kind-${info.kind}`">{{ kindLabel }}</span>
        </header>

        <dl class="legend-body">
          <dt>Grouping</dt>
          <dd>{{ info.grouping }}</dd>
          <dt>Position</dt>
          <dd>{{ info.position }}</dd>
        </dl>

        <ul v-if="info.notes.length" class="legend-notes">
          <li v-for="(note, i) in info.notes" :key="i">{{ note }}</li>
        </ul>

        <footer class="legend-footer">
          <span class="legend-mode-label">Layout</span>
          <div class="legend-modes">
            <button
              v-for="mode in MODES"
              :key="mode.value"
              class="legend-mode"
              :class="{ active: layoutMode === mode.value }"
              :disabled="mode.value === 'server' && !hasStoredLayout"
              :title="modeTitle(mode.value)"
              @click="$emit('update:layoutMode', mode.value)"
            >{{ mode.label }}</button>
          </div>
        </footer>
        <p class="legend-effective">
          Showing: <strong>{{ effectiveLabel }}</strong>
          <span v-if="!hasStoredLayout" class="legend-warn">
            — this graph has no usable stored layout, so the simulation is the only option.
          </span>
        </p>
      </aside>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { schemaLayoutInfo, prefersServerLayout } from '@/utils/kbGraphLayouts'

type LayoutMode = 'auto' | 'server' | 'force'

const props = defineProps<{
  schemaName: string
  layoutMode: LayoutMode
  /** False when the artifact carries no layout this renderer can draw. */
  hasStoredLayout: boolean
}>()

defineEmits<{ (e: 'update:layoutMode', mode: LayoutMode): void }>()

const open = ref(false)

const MODES: { value: LayoutMode; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'server', label: 'Computed' },
  { value: 'force', label: 'Force' },
]

const info = computed(() => schemaLayoutInfo(props.schemaName))

const kindLabel = computed(() => ({
  tree: 'hierarchy',
  community: 'communities',
  grouped: 'force-directed',
}[info.value.kind]))

const usingServer = computed(() => {
  if (!props.hasStoredLayout) return false
  if (props.layoutMode === 'server') return true
  if (props.layoutMode === 'force') return false
  return prefersServerLayout(props.schemaName)
})

const effectiveLabel = computed(() =>
  usingServer.value ? 'layout computed on the server' : 'force simulation in the browser',
)

function modeTitle(mode: LayoutMode): string {
  if (mode === 'auto') return 'Use whichever suits this graph'
  if (mode === 'server') {
    return props.hasStoredLayout
      ? 'Draw the layout computed on the server, without simulating'
      : 'Unavailable — no usable stored layout for this graph'
  }
  return 'Ignore the stored layout and simulate in the browser'
}
</script>

<style scoped>
.legend-wrap {
  position: absolute;
  top: 0.65rem;
  right: 0.65rem;
  z-index: 6;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.45rem;
  /* The wrapper spans nothing clickable itself — only the button and card
     take pointer events, so panning the canvas underneath still works. */
  pointer-events: none;
}

.legend-toggle,
.legend-card { pointer-events: auto; }

.legend-toggle {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(15, 17, 23, 0.85);
  color: #8b93ab;
  font-size: 0.7rem;
  font-style: italic;
  font-weight: 600;
  cursor: pointer;
  line-height: 1;
  backdrop-filter: blur(6px);
  transition: color 0.15s, border-color 0.15s;
}
.legend-toggle:hover { color: #d4d8e8; border-color: rgba(255, 255, 255, 0.3); }
.legend-toggle.open { font-style: normal; }

.legend-card {
  width: 290px;
  max-height: calc(100% - 3rem);
  overflow-y: auto;
  padding: 0.75rem 0.85rem 0.7rem;
  border-radius: 8px;
  border: 1px solid rgba(120, 140, 200, 0.22);
  background: rgba(12, 14, 21, 0.93);
  backdrop-filter: blur(8px);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.55);
  font-size: 0.72rem;
  line-height: 1.5;
  color: #b0b8cc;
  scrollbar-width: thin;
  scrollbar-color: #2a2f3e transparent;
}

.legend-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.legend-title {
  margin: 0;
  font-size: 0.8rem;
  font-weight: 600;
  color: #e2e6f2;
}
.legend-kind {
  flex-shrink: 0;
  font-size: 0.6rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  border: 1px solid currentColor;
  opacity: 0.75;
}
.kind-tree { color: #e05ca3; }
.kind-community { color: #63b3ff; }
.kind-grouped { color: #34e79e; }

.legend-body { margin: 0 0 0.55rem; }
.legend-body dt {
  font-size: 0.6rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: #5f6884;
  margin-top: 0.4rem;
}
.legend-body dd { margin: 0.1rem 0 0; }

.legend-notes {
  margin: 0 0 0.6rem;
  padding-left: 0.9rem;
  color: #939bb2;
}
.legend-notes li { margin-bottom: 0.2rem; }

.legend-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding-top: 0.55rem;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
}
.legend-mode-label {
  font-size: 0.6rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: #5f6884;
}
.legend-modes { display: flex; gap: 0.2rem; }
.legend-mode {
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: none;
  color: #8b93ab;
  font-size: 0.65rem;
  padding: 0.16rem 0.4rem;
  border-radius: 4px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
}
.legend-mode:hover:not(:disabled) { color: #d4d8e8; border-color: rgba(255, 255, 255, 0.28); }
.legend-mode.active {
  color: #c8d0e8;
  border-color: rgba(120, 140, 220, 0.55);
  background: rgba(90, 110, 200, 0.18);
}
.legend-mode:disabled { opacity: 0.35; cursor: not-allowed; }

.legend-effective {
  margin: 0.5rem 0 0;
  font-size: 0.66rem;
  color: #6f778f;
}
.legend-effective strong { color: #9aa3bd; font-weight: 500; }
.legend-warn { color: #b08a5a; }

.legend-fade-enter-active, .legend-fade-leave-active { transition: opacity 0.15s, transform 0.15s; }
.legend-fade-enter-from, .legend-fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
