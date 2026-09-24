import { createRouter, createWebHistory, type RouteLocationNormalized, type NavigationGuardNext } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const KB_ROLES = ['administrator', 'knowledge_curator']

// An external contributor holds the elicitation capability and nothing else
// (advandeb_methods/docs/10 §4.1). Confining them to their own queue is what
// makes "a contributor never sees a link that 403s" true of the *routes* and
// not only of the sidebar — Home, for one, renders cards pointing at sections
// they cannot open.
const EXTERNAL_ALLOWED_PREFIXES = ['/elicitation', '/settings', '/login']

function isExternalOnly(roles: string[] | undefined): boolean {
  const r = roles || []
  return r.length > 0 && r.every(x => x === 'external_contributor')
}

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
      path: '/elicitation',
      name: 'elicitation',
      component: () => import('@/views/ElicitationView.vue'),
      meta: { requiresAuth: true }
    },
    {
      // Public on purpose: external collaborators reach this before they have
      // an account. App.vue renders it without the sidebar, because an
      // unauthenticated visitor falls through to the bare <router-view>.
      path: '/elicitation/join',
      name: 'elicitation-join',
      component: () => import('@/views/EnrolmentView.vue')
    },
    {
      path: '/models',
      name: 'models',
      component: () => import('@/views/ModelsLibraryView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/models/:id',
      name: 'model-editor',
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
      path: '/admin/experts',
      name: 'admin-experts',
      component: () => import('@/views/AdminExpertsView.vue'),
      meta: { requiresAuth: true, requiresAdmin: true }
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
  // The external-contributor check has the same requirement, and applies to
  // every route, so hydrate whenever we hold a token. hydrate() is memoised,
  // so this costs one request per session rather than one per navigation.
  if (authStore.isAuthenticated && !authStore.user) {
    await authStore.hydrate()
  }

  if (
    authStore.isAuthenticated &&
    isExternalOnly(authStore.user?.roles) &&
    !EXTERNAL_ALLOWED_PREFIXES.some(p => to.path.startsWith(p))
  ) {
    next({ name: 'elicitation' })
    return
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
