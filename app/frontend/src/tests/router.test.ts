import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, RouterLinkStub, flushPromises } from '@vue/test-utils'
import { useAuthStore, type User } from '@/stores/auth'
import { canElicit, isAllowedForExternal, isExternalOnly } from '@/utils/access'

/**
 * Pins what each kind of account can reach, and that the presentation (Home
 * cards) agrees with the guard. Before: an unknown URL rendered an empty page,
 * /elicitation was gated in the sidebar but not on the route, and Home offered
 * the Knowledge Graph card to people the router would silently bounce.
 */

// Heavy views are irrelevant to routing decisions; stand-ins keep the test to
// what the guard does.
const stub = (name: string) => ({ default: { name, template: `<div data-view="${name}" />` } })
vi.mock('@/views/ElicitationView.vue', () => stub('ElicitationView'))
vi.mock('@/views/KnowledgeBuilderView.vue', () => stub('KnowledgeBuilderView'))
vi.mock('@/views/AdminUsersView.vue', () => stub('AdminUsersView'))
vi.mock('@/views/ChatView.vue', () => stub('ChatView'))
vi.mock('@/views/LLMKeysView.vue', () => stub('LLMKeysView'))
vi.mock('@/views/EnrolmentView.vue', () => stub('EnrolmentView'))

const { default: router } = await import('@/router')
const { default: HomeView } = await import('@/views/HomeView.vue')

function user(roles: string[], capabilities: string[] = []): User {
  return {
    id: 'u1', email: 'u@example.org', roles, capabilities,
    chat_history_visible_to_admin: true,
  }
}

function signIn(u: User | null) {
  if (u) localStorage.setItem('access_token', 'token')
  else localStorage.removeItem('access_token')
  const auth = useAuthStore()
  auth.accessToken = u ? 'token' : null
  auth.user = u
  return auth
}

async function go(path: string) {
  // Start every case from a neutral page so a redirect to the current
  // location is not swallowed as a duplicate navigation.
  await router.replace('/login')
  await router.push(path).catch(() => {})
  await router.isReady()
  return router.currentRoute.value
}

const explorer = user(['knowledge_explorator'])
const expert = user(['knowledge_explorator'], ['sf_elicitation'])
const curator = user(['knowledge_curator'])
const admin = user(['administrator'])
const external = user(['external_contributor'])

describe('router', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('unknown URLs', () => {
    it('resolve to the not-found route instead of an empty page', async () => {
      signIn(explorer)
      const route = await go('/no/such/page')
      expect(route.name).toBe('not-found')
      expect(route.fullPath).toBe('/no/such/page')
    })

    it('work for a signed-out visitor too', async () => {
      signIn(null)
      const route = await go('/definitely-not-here')
      expect(route.name).toBe('not-found')
    })

    it('do not shadow real routes', async () => {
      signIn(curator)
      expect((await go('/kb')).name).toBe('knowledge-builder')
      expect((await go('/elicitation/join')).name).toBe('elicitation-join')
    })
  })

  describe('/elicitation', () => {
    it('is closed to an explorer without the capability', async () => {
      signIn(explorer)
      expect((await go('/elicitation')).name).toBe('home')
    })

    it('is open to an explorer holding sf_elicitation', async () => {
      signIn(expert)
      expect((await go('/elicitation')).name).toBe('elicitation')
    })

    it('is open to curators and administrators', async () => {
      signIn(curator)
      expect((await go('/elicitation')).name).toBe('elicitation')
      signIn(admin)
      expect((await go('/elicitation')).name).toBe('elicitation')
    })

    it('is open to an external contributor, whose role implies it', async () => {
      // The backend's require_capability lets this role through; the frontend
      // must too, or the external-only redirect and this gate bounce forever.
      signIn(external)
      expect((await go('/elicitation')).name).toBe('elicitation')
      expect((await go('/chat')).name).toBe('elicitation')
      expect((await go('/no/such/page')).name).toBe('elicitation')
    })

    it('needs a session at all', async () => {
      signIn(null)
      expect((await go('/elicitation')).name).toBe('login')
    })
  })

  describe('role-gated sections', () => {
    it('keep /kb to curators and administrators', async () => {
      signIn(explorer)
      expect((await go('/kb')).name).toBe('home')
      signIn(curator)
      expect((await go('/kb')).name).toBe('knowledge-builder')
    })

    it('keep /admin to administrators', async () => {
      signIn(curator)
      expect((await go('/admin/users')).name).toBe('home')
      signIn(admin)
      expect((await go('/admin/users')).name).toBe('admin-users')
    })
  })
})

describe('Home cards agree with the guard', () => {
  function home(u: User) {
    signIn(u)
    return mount(HomeView, { global: { stubs: { RouterLink: RouterLinkStub } } })
  }
  const targets = (w: ReturnType<typeof home>) =>
    w.findAllComponents(RouterLinkStub).map(l => l.props('to'))

  it('hides the Knowledge Graph card from non-curators', async () => {
    const w = home(explorer)
    await flushPromises()
    expect(targets(w)).not.toContain('/kb')
    expect(targets(w)).not.toContain('/elicitation')
  })

  it('shows it to curators', async () => {
    const w = home(curator)
    await flushPromises()
    expect(targets(w)).toContain('/kb')
    expect(targets(w)).toContain('/elicitation')
  })

  it('shows Elicitation to a capability holder without offering /kb', async () => {
    const w = home(expert)
    await flushPromises()
    expect(targets(w)).toContain('/elicitation')
    expect(targets(w)).not.toContain('/kb')
  })
})

describe('access rules', () => {
  it('recognise an external-only account', () => {
    expect(isExternalOnly(external)).toBe(true)
    expect(isExternalOnly(user(['external_contributor', 'knowledge_explorator']))).toBe(false)
    expect(isExternalOnly(user([]))).toBe(false)
  })

  it('confine external contributors to whole path segments', () => {
    expect(isAllowedForExternal('/elicitation')).toBe(true)
    expect(isAllowedForExternal('/elicitation/join')).toBe(true)
    expect(isAllowedForExternal('/settings/privacy')).toBe(true)
    expect(isAllowedForExternal('/settingsx')).toBe(false)
    expect(isAllowedForExternal('/chat')).toBe(false)
  })

  it('grant elicitation by capability or implying role', () => {
    expect(canElicit(explorer)).toBe(false)
    expect(canElicit(expert)).toBe(true)
    expect(canElicit(curator)).toBe(true)
    expect(canElicit(external)).toBe(true)
    expect(canElicit(null)).toBe(false)
  })
})
