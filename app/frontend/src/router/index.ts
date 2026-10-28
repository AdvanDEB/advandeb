import { createRouter, createWebHistory, type RouteLocationNormalized, type NavigationGuardNext } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  canElicit, canUseKnowledgeBuilder, isAdmin, isAllowedForExternal, isExternalOnly,
} from '@/utils/access'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    /** Administrators and knowledge curators. */
    requiresKB?: boolean
    requiresAdmin?: boolean
    /** The sf_elicitation capability, or a role that implies it (utils/access.ts canElicit). */
    requiresElicitation?: boolean
  }
}

// An external contributor holds the elicitation capability and nothing else
// (advandeb_methods/docs/10 §4.1). Confining them to their own queue is what
// makes "a contributor never sees a link that 403s" true of the *routes* and
// not only of the sidebar — Home, for one, renders cards pointing at sections
// they cannot open. The rules themselves live in utils/access.ts, shared with
// the sidebar and Home so the three cannot drift apart again.

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
      // The sidebar link was capability-gated but the route was not, so a
      // typed or bookmarked URL opened a queue whose every request 403s.
      meta: { requiresAuth: true, requiresElicitation: true }
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
    },
    {
      // Last, so every real route wins. Without it an unknown URL rendered an
      // empty main area with no hint that the address was wrong.
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue')
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

  const user = authStore.user

  if (
    authStore.isAuthenticated &&
    isExternalOnly(user) &&
    !isAllowedForExternal(to.path)
  ) {
    next({ name: 'elicitation' })
    return
  }

  if (to.meta.requiresKB && !canUseKnowledgeBuilder(user)) {
    next({ name: 'home' })
    return
  }

  if (to.meta.requiresAdmin && !isAdmin(user)) {
    next({ name: 'home' })
    return
  }

  if (to.meta.requiresElicitation && !canElicit(user)) {
    next({ name: 'home' })
    return
  }

  next()
})

export default router
