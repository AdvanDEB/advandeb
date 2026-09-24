<template>
  <section class="card evidence">
    <header class="ev-head">
      <h3>Evidence set</h3>
      <span class="count">{{ passages.length }} passages</span>
    </header>
    <p class="note">
      These are the same passages, in the same frozen set, that the model panel
      judged. Judge from these — not from what you know beyond them.
    </p>

    <ol class="passages">
      <li v-for="(p, i) in passages" :key="p.passage_id || i" class="passage">
        <div class="p-meta">
          <span class="n">{{ i + 1 }}</span>
          <span class="src">{{ p.title || '(untitled source)' }}</span>
          <span v-if="p.year" class="year">{{ p.year }}</span>
          <a v-if="p.doi" :href="`https://doi.org/${p.doi}`" target="_blank"
             rel="noopener" class="doi">DOI</a>
          <span v-if="p.peer_reviewed === false" class="preprint">preprint</span>
        </div>
        <p class="p-text">{{ p.text }}</p>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
export interface EvidencePassage {
  passage_id?: string
  text: string
  title?: string | null
  year?: string | number | null
  doi?: string | null
  similarity?: number | null
  peer_reviewed?: boolean | null
}

defineProps<{ passages: EvidencePassage[] }>()
</script>

<style scoped>
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 1.1rem 1.25rem; }
.ev-head { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; }
.ev-head h3 { font-size: 1rem; font-weight: 600; color: #111827; }
.count { font-size: 0.78rem; color: #9ca3af; }
.note { font-size: 0.82rem; color: #6b7280; margin: 0.35rem 0 0.9rem; line-height: 1.5; }

.passages { list-style: none; display: flex; flex-direction: column; gap: 0.85rem; max-height: 46vh; overflow-y: auto; padding-right: 0.4rem; }
.passage { border-left: 3px solid #e5e7eb; padding-left: 0.8rem; }
.p-meta { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; font-size: 0.75rem; color: #6b7280; margin-bottom: 0.3rem; }
.n { background: #f3f4f6; border-radius: 4px; padding: 0 0.35rem; font-weight: 600; color: #374151; }
.src { font-weight: 500; color: #4b5563; }
.doi { color: #3b82f6; text-decoration: none; }
.doi:hover { text-decoration: underline; }
.preprint { background: #fef3c7; color: #92400e; border-radius: 4px; padding: 0 0.3rem; font-weight: 600; }
.p-text { font-size: 0.87rem; line-height: 1.6; color: #374151; }
</style>
