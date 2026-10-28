import { describe, it, expect, vi, afterEach } from 'vitest'
import { createApp, type App as VueApp } from 'vue'
import { getActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { flushPromises } from '@vue/test-utils'
import App from '@/App.vue'
import { useAuthStore } from '@/stores/auth'

/**
 * Mounted the way main.ts does it: into index.html's <div id="app">. Before,
 * App.vue's root element also carried id="app", so the page had two elements
 * with that id (invalid HTML, an axe violation, and `#app` matched twice).
 */

let app: VueApp | undefined
afterEach(() => {
  app?.unmount()
  document.body.innerHTML = ''
})

describe('App mount', () => {
  it('leaves exactly one #app on the page', async () => {
    document.body.innerHTML = '<div id="app"></div>'
    const auth = useAuthStore()
    vi.spyOn(auth, 'fetchAuthConfig').mockResolvedValue(undefined)
    vi.spyOn(auth, 'hydrate').mockResolvedValue(undefined)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/login', component: { template: '<h1>Login</h1>' } }],
    })
    await router.push('/login')

    app = createApp(App).use(getActivePinia()!).use(router)
    app.mount('#app')
    await flushPromises()

    expect(document.querySelector('h1')?.textContent).toBe('Login')
    expect(document.querySelectorAll('#app')).toHaveLength(1)
    // The root element still takes the full viewport height via its class.
    expect(document.querySelector('#app > .app-root')).not.toBeNull()
  })
})
