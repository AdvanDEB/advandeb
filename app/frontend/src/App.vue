<template>
  <div id="app">
    <!-- Authenticated routes use the sidebar layout -->
    <AppLayout v-if="authStore.isAuthenticated && !isLoginRoute">
      <router-view />
    </AppLayout>

    <!-- Login / unauthenticated pages render without layout -->
    <router-view v-else />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/components/layout/AppLayout.vue'

const authStore = useAuthStore()
const route = useRoute()

const isLoginRoute = computed(() => route.path === '/login')

onMounted(async () => {
  await authStore.fetchAuthConfig()
  await authStore.fetchCurrentUser()
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  height: 100vh;
}
</style>
