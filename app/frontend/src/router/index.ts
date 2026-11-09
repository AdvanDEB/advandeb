import { createRouter, createWebHistory, type RouteLocationNormalized, type NavigationGuardNext } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  canElicit, canSeeWorkshop, canUseKnowledgeBuilder, isAdmin, isAllowedForExternal, isExternalOnly,
} from '@/utils/access'
import { forgetAutoReload, isChunkLoadError, recoverFromChunkError } from '@/utils/staleChunk'
import { preferredLang } from '@/utils/wikiText'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    /** Administrators and knowledge curators. */
    requiresKB?: boolean
    requiresAdmin?: boolean
    /** The sf_elicitation capability, or a role that implies it (utils/access.ts canElicit). */
    requiresElicitation?: boolean
    /** The 2026Workshop wiki: administrators and accounts granted it (utils/access.ts canSeeWorkshop). */
    requiresWorkshop?: boolean
    /** Shown as "<title> · AdvanDEB" in the tab; home keeps APP_TITLE. */
    title?: string
  }
}

/** index.html's <title>, kept for the home page. */
export const APP_TITLE = 'AdvanDEB — Knowledge Graph for DEB Biology'

export function pageTitle(route: Pick<RouteLocationNormalized, 'meta'>): string {
  return route.meta.title ? `${route.meta.title} · AdvanDEB` : APP_TITLE
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
      component: () => import('@/views/LoginView.vue'),
      meta: { title: 'Sign in' }
    },
    {
      path: '/documents',
      name: 'documents',
      component: () => import('@/views/DocumentsView.vue'),
      meta: { title: 'Corpus', requiresAuth: true }
    },
    {
      path: '/facts',
      name: 'facts',
      component: () => import('@/views/FactsView.vue'),
      meta: { title: 'Facts', requiresAuth: true }
    },
    {
      path: '/chat',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { title: 'Chat', requiresAuth: true }
    },
    {
      path: '/documentation',
      name: 'documentation',
      component: () => import('@/views/DocumentationView.vue'),
      meta: { title: 'Documentation', requiresAuth: true }
    },
    // The workshop wiki. Every page carries its language, so a link opens in
    // the language it was shared in; /2026Workshop alone picks the reader's.
    {
      path: '/2026Workshop',
      name: 'wiki',
      redirect: () => ({ name: 'wiki-home', params: { lang: preferredLang() } }),
      meta: { title: 'Wiki', requiresAuth: true, requiresWorkshop: true }
    },
    {
      path: '/2026Workshop/:lang(hr|en)',
      name: 'wiki-home',
      component: () => import('@/views/WikiView.vue'),
      meta: { title: 'Wiki', requiresAuth: true, requiresWorkshop: true }
    },
    {
      path: '/2026Workshop/:lang(hr|en)/n/:id',
      name: 'wiki-note',
      component: () => import('@/views/WikiView.vue'),
      meta: { title: 'Wiki', requiresAuth: true, requiresWorkshop: true }
    },
    {
      path: '/2026Workshop/:lang(hr|en)/graph',
      name: 'wiki-graph',
      component: () => import('@/views/WikiView.vue'),
      meta: { title: 'Wiki', requiresAuth: true, requiresWorkshop: true }
    },
    {
      path: '/2026Workshop/:lang(hr|en)/search',
      name: 'wiki-search',
      component: () => import('@/views/WikiView.vue'),
      meta: { title: 'Wiki', requiresAuth: true, requiresWorkshop: true }
    },
    {
      path: '/2026Workshop/:lang(hr|en)/tag/:tag(.*)',
      name: 'wiki-tag',
      component: () => import('@/views/WikiView.vue'),
      meta: { title: 'Wiki', requiresAuth: true, requiresWorkshop: true }
    },
    // The wiki's first address. Kept so that links shared before the rename
    // still open the same page.
    {
      path: '/wiki/:rest(.*)*',
      name: 'wiki-legacy',
      redirect: (to) => {
        const rest = ([] as string[]).concat(to.params.rest ?? []).map(encodeURIComponent).join('/')
        return { path: `/2026Workshop${rest ? `/${rest}` : ''}`, query: to.query, hash: to.hash }
      },
      meta: { title: 'Wiki', requiresAuth: true, requiresWorkshop: true }
    },
    {
      path: '/elicitation',
      name: 'elicitation',
      component: () => import('@/views/ElicitationView.vue'),
      // The sidebar link was capability-gated but the route was not, so a
      // typed or bookmarked URL opened a queue whose every request 403s.
      meta: { title: 'Elicitation', requiresAuth: true, requiresElicitation: true }
    },
    {
      // Public on purpose: external collaborators reach this before they have
      // an account. App.vue renders it without the sidebar, because an
      // unauthenticated visitor falls through to the bare <router-view>.
      path: '/elicitation/join',
      name: 'elicitation-join',
      component: () => import('@/views/EnrolmentView.vue'),
      meta: { title: 'Join the elicitation' }
    },
    {
      path: '/models',
      name: 'models',
      component: () => import('@/views/ModelsLibraryView.vue'),
      meta: { title: 'Models', requiresAuth: true }
    },
    {
      path: '/models/:id',
      name: 'model-editor',
      component: () => import('@/views/ModelsView.vue'),
      meta: { title: 'Model editor', requiresAuth: true }
    },
    {
      path: '/settings/llm-keys',
      name: 'llm-keys',
      component: () => import('@/views/LLMKeysView.vue'),
      meta: { title: 'LLM API keys', requiresAuth: true }
    },
    {
      path: '/settings/privacy',
      name: 'privacy-settings',
      component: () => import('@/views/PrivacySettingsView.vue'),
      meta: { title: 'Privacy', requiresAuth: true }
    },
    {
      path: '/kb',
      name: 'knowledge-builder',
      component: () => import('@/views/KnowledgeBuilderView.vue'),
      meta: { title: 'Knowledge graph', requiresAuth: true, requiresKB: true }
    },
    {
      path: '/admin/experts',
      name: 'admin-experts',
      component: () => import('@/views/AdminExpertsView.vue'),
      meta: { title: 'Experts', requiresAuth: true, requiresAdmin: true }
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('@/views/AdminUsersView.vue'),
      meta: { title: 'Users', requiresAuth: true, requiresAdmin: true }
    },
    {
      path: '/admin/users/:id/chats',
      name: 'admin-user-chats',
      component: () => import('@/views/AdminUserChatsView.vue'),
      meta: { title: 'User conversations', requiresAuth: true, requiresAdmin: true }
    },
    {
      // Last, so every real route wins. Without it an unknown URL rendered an
      // empty main area with no hint that the address was wrong.
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { title: 'Page not found' }
    }
  ]
})

router.beforeEach(async (to: RouteLocationNormalized, _from: RouteLocationNormalized, next: NavigationGuardNext) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    // In the URL, not only in memory (route.redirectedFrom), so the way back
    // survives a reload of /login. LoginView passes it through safeRedirect.
    next({ name: 'login', query: { redirect: to.fullPath } })
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
    !isAllowedForExternal(to.path, user)
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

  if (to.meta.requiresWorkshop && !canSeeWorkshop(user)) {
    next({ name: 'home' })
    return
  }

  if (to.meta.requiresElicitation && !canElicit(user)) {
    next({ name: 'home' })
    return
  }

  next()
})

router.afterEach((to, _from, failure) => {
  if (failure) return
  document.title = pageTitle(to)
  forgetAutoReload(router.resolve(to).href)
})

// After a deploy, an open tab's next lazy route 404s and the navigation is
// silently aborted. Load the destination afresh instead (utils/staleChunk.ts).
router.onError((error, to) => {
  if (isChunkLoadError(error)) {
    void recoverFromChunkError(router.resolve(to).href)
    return
  }
  // Registering a handler stops vue-router logging the rest itself.
  console.error(error)
})

export default router
