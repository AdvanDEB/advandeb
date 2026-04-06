import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useAuthStore } from '@/stores/auth'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

// Hydrate the user from the stored token before the router resolves its
// first navigation. Without this, the navigation guard sees user=null on a
// hard refresh and redirects away from protected routes like /kb.
const authStore = useAuthStore()
authStore.fetchCurrentUser().finally(() => {
  app.mount('#app')
})
