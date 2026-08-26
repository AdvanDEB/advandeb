import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useAuthStore } from '@/stores/auth'
import 'highlight.js/styles/github.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

// Kick off hydration before mounting so the first paint already knows who the
// user is. The router guard awaits the same shared promise, so a slow or
// retried /users/me can't race a role-gated route into a redirect.
const authStore = useAuthStore()
authStore.hydrate().finally(() => {
  app.mount('#app')
})
