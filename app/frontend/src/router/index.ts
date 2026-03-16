import { createRouter, createWebHistory, type RouteLocationNormalized, type NavigationGuardNext } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const KB_ROLES = ['administrator', 'knowledge_curator']

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue')
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue')
    },
    {
      path: '/documents',
      name: 'documents',
      component: () => import('@/views/DocumentsView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/facts',
      name: 'facts',
      component: () => import('@/views/FactsView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/graph',
      name: 'graph',
      component: () => import('@/views/GraphView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/chat',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/scenarios',
      name: 'scenarios',
      component: () => import('@/views/ScenariosView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/models',
      name: 'models',
      component: () => import('@/views/ModelsView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/kb',
      name: 'knowledge-builder',
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore — KnowledgeBuilderView uses plain JS Options API (no lang="ts")
      component: () => import('@/views/KnowledgeBuilderView.vue'),
      meta: { requiresAuth: true, requiresKB: true }
    }
  ]
})

router.beforeEach((to: RouteLocationNormalized, _from: RouteLocationNormalized, next: NavigationGuardNext) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'login' })
    return
  }

  if (to.meta.requiresKB && !KB_ROLES.some(role => authStore.hasRole(role))) {
    next({ name: 'home' })
    return
  }

  next()
})

export default router
