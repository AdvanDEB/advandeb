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
      path: '/chat',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/documentation',
      name: 'documentation',
      component: () => import('@/views/DocumentationView.vue'),
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
      path: '/settings/llm-keys',
      name: 'llm-keys',
      component: () => import('@/views/LLMKeysView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/settings/privacy',
      name: 'privacy-settings',
      component: () => import('@/views/PrivacySettingsView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/kb',
      name: 'knowledge-builder',
      component: () => import('@/views/KnowledgeBuilderView.vue'),
      meta: { requiresAuth: true, requiresKB: true }
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('@/views/AdminUsersView.vue'),
      meta: { requiresAuth: true, requiresAdmin: true }
    },
    {
      path: '/admin/users/:id/chats',
      name: 'admin-user-chats',
      component: () => import('@/views/AdminUserChatsView.vue'),
      meta: { requiresAuth: true, requiresAdmin: true }
    }
  ]
})

router.beforeEach(async (to: RouteLocationNormalized, _from: RouteLocationNormalized, next: NavigationGuardNext) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'login' })
    return
  }

  // Role checks below read authStore.user. On a hard load of a deep link the
  // token is in localStorage but the profile hasn't come back yet, so wait for
  // it — otherwise /kb and /admin/* redirect to home on every refresh.
  if ((to.meta.requiresKB || to.meta.requiresAdmin) && !authStore.user) {
    await authStore.hydrate()
  }

  if (to.meta.requiresKB && !KB_ROLES.some(r => authStore.hasRole(r))) {
    next({ name: 'home' })
    return
  }

  if (to.meta.requiresAdmin && !authStore.hasRole('administrator')) {
    next({ name: 'home' })
    return
  }

  next()
})

export default router
