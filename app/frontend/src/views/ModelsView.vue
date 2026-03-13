<template>
  <div class="models-view">
    <header class="page-header">
      <h1>Models</h1>
    </header>
    <div class="coming-soon">
      <span class="icon">📐</span>
      <h2>Model builder coming soon</h2>
      <p>
        Build, calibrate, and visualize DEB (Dynamic Energy Budget) models
        linked directly to your knowledge graph.
      </p>
      <router-link to="/graph" class="cta-link">
        Explore the Knowledge Graph →
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
// Models feature — future scope
</script>

<style scoped>
.models-view {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 2rem;
}
.page-header h1 { font-size: 1.5rem; font-weight: 700; color: #111827; }
.coming-soon {
  display: flex; flex-direction: column; align-items: center;
  text-align: center; padding: 4rem 2rem; gap: 1rem;
}
.icon { font-size: 3rem; }
.coming-soon h2 { font-size: 1.3rem; font-weight: 600; color: #374151; }
.coming-soon p { color: #6b7280; max-width: 480px; line-height: 1.6; }
.cta-link {
  color: #3b82f6; text-decoration: none; font-size: 0.9rem;
  border: 1px solid #bfdbfe; border-radius: 6px; padding: 0.4rem 1rem;
}
.cta-link:hover { background: #eff6ff; }
</style>
