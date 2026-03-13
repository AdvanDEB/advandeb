<template>
  <div class="graph-view">
    <KnowledgeGraph />
  </div>
</template>

<script setup lang="ts">
import KnowledgeGraph from '@/components/graph/KnowledgeGraph.vue'
</script>

<style scoped>
.graph-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
}
</style>
