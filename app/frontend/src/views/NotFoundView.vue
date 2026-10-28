<template>
  <!-- Signed in, this renders inside AppLayout's <main>; signed out it is the
       whole page and has to be the main landmark itself. -->
  <component
    :is="inShell ? 'section' : 'main'"
    :id="inShell ? undefined : 'main-content'"
    :tabindex="inShell ? undefined : -1"
    class="not-found"
    aria-labelledby="nf-title"
  >
    <p class="code" aria-hidden="true">404</p>
    <h1 id="nf-title">Page not found</h1>
    <p class="detail">
      Nothing lives at <code>{{ route.fullPath }}</code>. The link may be out of
      date, or the address mistyped.
    </p>
    <div class="actions">
      <router-link to="/" class="btn primary">Go to Home</router-link>
      <button v-if="canGoBack" type="button" class="btn ghost" @click="router.back()">Go back</button>
    </div>
  </component>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
/** App.vue wraps signed-in, non-bare routes in AppLayout (which has <main>). */
const inShell = computed(() => authStore.isAuthenticated)

// A deep link opened in a fresh tab has nowhere to go back to.
const canGoBack = typeof window !== 'undefined' && window.history.length > 1
</script>

<style scoped>
.not-found:focus { outline: none; }

.not-found {
  max-width: 34rem;
  margin: 0 auto;
  padding: 4rem 1.5rem;
  text-align: center;
  color: var(--app-ink-2);
}

.code {
  font-size: 3.5rem;
  font-weight: 700;
  line-height: 1;
  /* Decorative (aria-hidden), but still text: 3:1 for large text, not the
     1.5:1 of --app-line-2. */
  color: var(--app-ink-3);
  margin-bottom: 0.75rem;
}

h1 {
  font-size: 1.5rem;
  color: var(--app-ink);
  margin-bottom: 0.75rem;
}

.detail {
  font-size: 0.95rem;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

code {
  font-family: ui-monospace, 'Fira Code', monospace;
  font-size: 0.85em;
  background: var(--app-bg-3);
  padding: 0.1em 0.35em;
  border-radius: var(--app-radius-sm);
}

.actions {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 1.75rem;
}

.btn {
  display: inline-flex;
  align-items: center;
  min-height: var(--app-touch);
  padding: 0 1.1rem;
  border-radius: var(--app-radius);
  font-size: 0.9rem;
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  border: 1px solid transparent;
}
.btn:focus-visible { outline: var(--app-focus); outline-offset: 2px; }
.btn.primary { background: var(--app-primary-strong); color: #fff; }
.btn.primary:hover { background: var(--app-primary-ink); }
.btn.ghost { background: var(--app-bg); border-color: var(--app-line-2); color: var(--app-ink-2); }
.btn.ghost:hover { background: var(--app-bg-3); }
</style>
