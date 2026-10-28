<template>
  <div class="app-root">
    <!-- Not id="app": main.ts mounts into index.html's #app and this renders
         inside it, so the id would be on the page twice. -->
    <!-- Authenticated routes use the sidebar layout -->
    <AppLayout v-if="authStore.isAuthenticated && !isBareRoute">
      <router-view />
    </AppLayout>

    <!-- Login and KB mode render without the sidebar layout -->
    <router-view v-else />

    <!-- Outside AppLayout so confirmations also work on the bare /kb view. -->
    <AppDialogHost />
    <RouteFocus />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/components/layout/AppLayout.vue'
import AppDialogHost from '@/components/common/AppDialogHost.vue'
import RouteFocus from '@/components/common/RouteFocus.vue'

const authStore = useAuthStore()
const route = useRoute()

const isBareRoute = computed(() =>
  route.path === '/login' || route.path.startsWith('/kb')
)

onMounted(async () => {
  await authStore.fetchAuthConfig()
  // main.ts already started hydration before mounting; hydrate() is memoised,
  // so this awaits that same request instead of fetching /users/me again.
  await authStore.hydrate()
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app,
.app-root {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  height: 100vh;
}
</style>
