<template>
  <div :class="['skeleton', shape]" :style="sizeStyle" aria-busy="true" aria-label="Loading…"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    width?: string
    height?: string
    shape?: 'line' | 'rect' | 'circle'
  }>(),
  { width: '100%', height: '1rem', shape: 'line' }
)

const sizeStyle = computed(() => ({
  width: props.width,
  height: props.height,
}))
</script>

<style scoped>
.skeleton {
  background: linear-gradient(90deg, #f3f4f6 25%, #e5e7eb 50%, #f3f4f6 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
  border-radius: 4px;
  display: block;
}

.skeleton.circle { border-radius: 50%; }
.skeleton.rect   { border-radius: 6px; }

@keyframes shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
