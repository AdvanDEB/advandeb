<template>
  <div class="app-layout">
    <!-- Mobile top bar -->
    <div class="mobile-topbar">
      <button
        class="hamburger"
        :aria-expanded="mobileOpen"
        aria-controls="app-sidebar"
        aria-label="Navigation menu"
        @click="mobileOpen = !mobileOpen"
      >
        <span class="bars" :class="{ open: mobileOpen }" aria-hidden="true">
          <i></i><i></i><i></i>
        </span>
      </button>
      <span class="mobile-brand">AdvanDEB</span>
    </div>

    <!-- Tapping outside is how a drawer gets closed on a phone; without this the
         only way back is the hamburger, which the drawer partly covers. -->
    <Transition name="fade">
      <div v-if="mobileOpen" class="scrim" @click="mobileOpen = false"></div>
    </Transition>

    <!-- Sidebar navigation -->
    <nav
      id="app-sidebar"
      ref="sidebarEl"
      :class="['sidebar', { 'mobile-open': mobileOpen, expanded }]"
      aria-label="Main navigation"
    >
      <div class="sidebar-brand">
        <span class="brand-icon" aria-hidden="true">🧬</span>
        <span class="brand-name">AdvanDEB</span>
        <!-- Labels used to appear only on :hover. Between 641px and 1024px — a
             tablet — there is no hover and the mobile layout has not engaged, so
             the rail was twelve unlabelled emoji and the logout button did not
             exist. An explicit toggle works for a mouse, a keyboard and a
             thumb alike. -->
        <button
          class="rail-toggle"
          :aria-expanded="expanded"
          :aria-label="expanded ? 'Collapse navigation labels' : 'Expand navigation labels'"
          @click="setExpanded(!expanded)"
        >
          <span aria-hidden="true">{{ expanded ? '«' : '»' }}</span>
        </button>
      </div>

      <ul class="nav-links">
        <li v-for="link in navLinks" :key="link.path">
          <router-link
            :to="link.path"
            :class="['nav-link', { active: isActive(link.path) }]"
            :aria-label="link.label"
            :aria-current="isActive(link.path) ? 'page' : undefined"
          >
            <span class="nav-icon" aria-hidden="true">{{ link.icon }}</span>
            <span class="nav-label">{{ link.label }}</span>
          </router-link>
        </li>
      </ul>

      <div class="sidebar-footer">
        <div v-if="authStore.user" class="user-info">
          <img
            v-if="authStore.user.avatar_url"
            :src="authStore.user.avatar_url"
            class="user-avatar"
            alt=""
          />
          <div v-else class="user-avatar-placeholder" aria-hidden="true">
            {{ initials }}
          </div>
          <span class="user-name">{{ authStore.user.full_name || authStore.user.email }}</span>
        </div>
        <button class="logout-btn" aria-label="Log out" @click="handleLogout">
          <span class="logout-icon" aria-hidden="true">⏏</span>
          <span class="logout-label">Log out</span>
        </button>
      </div>
    </nav>

    <!-- Main content area -->
    <main class="main-content">
      <slot />
    </main>

    <ToastNotifications />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import ToastNotifications from './ToastNotifications.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const mobileOpen = ref(false)
const sidebarEl = ref<HTMLElement | null>(null)

// The rail state is a preference, not a transient: re-collapsing it on every
// page load would make the labels feel like something you keep losing.
const expanded = ref(readExpanded())

function readExpanded(): boolean {
  try { return localStorage.getItem('advandeb.nav.expanded') === '1' } catch { return false }
}
function setExpanded(v: boolean) {
  expanded.value = v
  try { localStorage.setItem('advandeb.nav.expanded', v ? '1' : '0') } catch { /* private mode */ }
}

const baseLinks = [
  { path: '/',           icon: '⌂',  label: 'Home' },
  { path: '/chat',       icon: '💬', label: 'Chat' },
  { path: '/documents',  icon: '📄', label: 'Documents' },
  { path: '/facts',      icon: '🔬', label: 'Facts' },
  { path: '/documentation', icon: '?', label: 'Docs' },
  { path: '/models',     icon: '📐', label: 'Models' },
  { path: '/settings/llm-keys', icon: '🔑', label: 'LLM Keys' },
  { path: '/settings/privacy', icon: '🔒', label: 'Privacy' },
]

// An external contributor holds the elicitation capability and nothing else
// (advandeb_methods/docs/10 §4.1). They get a stripped sidebar: their queue and
// their own settings, with no link to documents, chat, knowledge or models —
// sections they cannot open. The router enforces the same boundary, so this is
// presentation rather than the security control.
const externalOnly = computed(() => {
  const roles = authStore.user?.roles || []
  return roles.length > 0 && roles.every(r => r === 'external_contributor')
})

const canElicit = computed(() =>
  authStore.hasCapability('sf_elicitation') ||
  authStore.hasRole('administrator') ||
  authStore.hasRole('knowledge_curator'))

const navLinks = computed(() => {
  if (externalOnly.value) {
    // Their queue, and nothing else. Privacy settings are deliberately not
    // advertised here — that page is about chat-history visibility, and an
    // external contributor has no chat. The route stays reachable if they are
    // sent there directly; it simply is not offered.
    return [{ path: '/elicitation', icon: '✎', label: 'Elicitation' }]
  }

  const links = [...baseLinks]
  // Elicitation is capability-gated: the DEB experts who provide the judgments
  // hold knowledge_explorator only, so the link follows the capability rather
  // than the role. Showing it to everyone would mean a 403 on click.
  if (canElicit.value) {
    links.push({ path: '/elicitation', icon: '✎', label: 'Elicitation' })
  }
  if (authStore.hasRole('administrator') || authStore.hasRole('knowledge_curator')) {
    links.push({ path: '/kb', icon: '⬡', label: 'Knowledge' })
  }
  if (authStore.hasRole('administrator')) {
    links.push({ path: '/admin/experts', icon: '🎓', label: 'Experts' })
    links.push({ path: '/admin/users', icon: '👤', label: 'Admin' })
  }
  return links
})

const initials = computed(() => {
  const name = authStore.user?.full_name || authStore.user?.email || '?'
  return name.slice(0, 2).toUpperCase()
})

function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && mobileOpen.value) mobileOpen.value = false
}

// Opening the drawer moves focus into it, so a keyboard or screen-reader user
// lands on the navigation rather than continuing behind it.
watch(mobileOpen, async (open) => {
  if (!open) return
  await nextTick()
  sidebarEl.value?.querySelector<HTMLElement>('a, button')?.focus()
})

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

// Close mobile nav on route change
router.afterEach(() => { mobileOpen.value = false })
</script>

<style scoped>
@import '@/styles/elicitation-tokens.css';

/* The navigation is a dark surface of its own; these are its local values, not
   a second design language. Everything else on the page uses the shared tokens. */
.app-layout {
  --nav-bg: #1e293b;
  --nav-line: #334155;
  --nav-ink: #cbd5e1;
  --nav-ink-dim: #94a3b8;
  --nav-hover: #334155;
  --nav-active: #2563eb;   /* white on this is 5.2:1 — the old #3b82f6 was 3.1 */

  display: flex;
  /* dvh, not vh: on iOS the URL bar collapse makes 100vh taller than the
     viewport, which cuts the bottom of the sidebar off. */
  height: 100dvh;
  overflow: hidden;
}

.sidebar {
  width: 60px;
  background: var(--nav-bg);
  display: flex;
  flex-direction: column;
  padding: var(--el-s2) 0;
  flex-shrink: 0;
  transition: width var(--el-t) var(--el-ease);
  overflow: hidden;
}

.sidebar.expanded { width: 200px; }

/* Hover-expand stays, but only where hover genuinely exists, and only as a
   convenience on top of the toggle — never as the sole way to read a label. */
@media (hover: hover) and (pointer: fine) {
  .sidebar:hover { width: 200px; }
  .sidebar:hover .nav-label,
  .sidebar:hover .brand-name,
  .sidebar:hover .user-name,
  .sidebar:hover .logout-label { opacity: 1; }
}
.sidebar:focus-within { width: 200px; }
.sidebar:focus-within .nav-label,
.sidebar:focus-within .brand-name,
.sidebar:focus-within .user-name,
.sidebar:focus-within .logout-label { opacity: 1; }

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: var(--el-s2);
  color: #fff;
  font-weight: 700;
  font-size: var(--el-fs-sm);
  padding: 0 var(--el-s2);
  min-height: var(--el-touch);
  white-space: nowrap;
  width: 100%;
  margin-bottom: var(--el-s3);
}

.brand-icon { font-size: 1.35rem; flex-shrink: 0; width: 24px; text-align: center; }
.brand-name {
  opacity: 0; flex: 1; min-width: 0; overflow: hidden;
  transition: opacity var(--el-t-fast) var(--el-ease);
}
.sidebar.expanded .brand-name { opacity: 1; }

.rail-toggle {
  width: var(--el-touch); height: var(--el-touch);
  flex-shrink: 0; margin-right: calc(var(--el-s2) * -1);
  background: none; border: 0; cursor: pointer;
  color: var(--nav-ink-dim); font-size: 1rem; line-height: 1;
  border-radius: var(--el-radius-sm);
  transition: color var(--el-t) var(--el-ease), background var(--el-t) var(--el-ease);
}
.rail-toggle:hover { color: #fff; background: var(--nav-hover); }
.rail-toggle:focus-visible { outline: 2px solid #fff; outline-offset: -2px; }

.nav-links {
  list-style: none;
  width: 100%;
  flex: 1;
  min-height: 0;
  /* An administrator has twelve links. On a short window the list used to be
     clipped by the sidebar's overflow:hidden with no way to scroll to the rest. */
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: var(--el-s3);
  min-height: var(--el-touch);
  padding: 0 var(--el-s3);
  color: var(--nav-ink);
  text-decoration: none;
  border-radius: var(--el-radius-sm);
  margin: 0 var(--el-s1);
  white-space: nowrap;
  font-size: var(--el-fs-sm);
  transition: background var(--el-t-fast) var(--el-ease),
              color var(--el-t-fast) var(--el-ease);
}

.nav-link:hover { background: var(--nav-hover); color: #fff; }
.nav-link:focus-visible { outline: 2px solid #fff; outline-offset: -2px; }
.nav-link.active { background: var(--nav-active); color: #fff; font-weight: 600; }

.nav-icon { font-size: 1.05rem; flex-shrink: 0; width: 22px; text-align: center; }
.nav-label {
  opacity: 0; overflow: hidden;
  transition: opacity var(--el-t-fast) var(--el-ease);
}
.sidebar.expanded .nav-label { opacity: 1; }

.sidebar-footer {
  display: flex;
  align-items: center;
  width: 100%;
  padding: var(--el-s2) var(--el-s2) 0;
  gap: var(--el-s2);
  border-top: 1px solid var(--nav-line);
  margin-top: auto;
  overflow: hidden;
}

.user-info {
  display: flex;
  align-items: center;
  gap: var(--el-s2);
  flex: 1;
  min-width: 0;
}

.user-avatar,
.user-avatar-placeholder {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  flex-shrink: 0;
}

.user-avatar { object-fit: cover; }
.user-avatar-placeholder {
  background: #475569;
  color: #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.65rem;
  font-weight: 700;
}

.user-name {
  font-size: var(--el-fs-xs);
  color: var(--nav-ink-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0;
  transition: opacity var(--el-t-fast) var(--el-ease);
}
.sidebar.expanded .user-name { opacity: 1; }

/* Was display:none until :hover — which meant no logout at all on a tablet.
   It is always present now, and always has an accessible name. */
.logout-btn {
  display: flex;
  align-items: center;
  gap: var(--el-s2);
  min-width: var(--el-touch);
  min-height: var(--el-touch);
  justify-content: center;
  background: none;
  border: 0;
  cursor: pointer;
  color: var(--nav-ink-dim);
  font-size: var(--el-fs-sm);
  flex-shrink: 0;
  padding: 0 var(--el-s2);
  border-radius: var(--el-radius-sm);
  transition: color var(--el-t) var(--el-ease), background var(--el-t) var(--el-ease);
}
.logout-icon { font-size: 1rem; }
.logout-label {
  opacity: 0; white-space: nowrap;
  transition: opacity var(--el-t-fast) var(--el-ease);
}
.sidebar.expanded .logout-label { opacity: 1; }
.logout-btn:hover { color: #fca5a5; background: var(--nav-hover); }
.logout-btn:focus-visible { outline: 2px solid #fff; outline-offset: -2px; }

.main-content {
  flex: 1;
  overflow: auto;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.scrim { display: none; }

/* ── Mobile ────────────────────────── */
.mobile-topbar {
  display: none;
  align-items: center;
  gap: var(--el-s2);
  padding: 0 var(--el-s3);
  background: var(--nav-bg);
  color: #fff;
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 200;
  height: 52px;
  /* The bar is fixed to the top, so it owns the notch inset itself. */
  padding-top: env(safe-area-inset-top, 0px);
  height: calc(52px + env(safe-area-inset-top, 0px));
}

.hamburger {
  width: var(--el-touch); height: var(--el-touch);
  display: flex; align-items: center; justify-content: center;
  background: none; border: 0; cursor: pointer;
  border-radius: var(--el-radius-sm);
  margin-left: calc(var(--el-s2) * -1);
}
.hamburger:focus-visible { outline: 2px solid #fff; outline-offset: -2px; }

/* Drawn rather than a ☰ glyph, so it can become an × when the drawer is open —
   the control says what the next tap does. */
.bars { display: block; width: 20px; height: 14px; position: relative; }
.bars i {
  position: absolute; left: 0; right: 0; height: 2px;
  background: #fff; border-radius: 2px;
  transition: transform var(--el-t) var(--el-ease),
              opacity var(--el-t-fast) var(--el-ease);
}
.bars i:nth-child(1) { top: 0; }
.bars i:nth-child(2) { top: 6px; }
.bars i:nth-child(3) { top: 12px; }
.bars.open i:nth-child(1) { transform: translateY(6px) rotate(45deg); }
.bars.open i:nth-child(2) { opacity: 0; }
.bars.open i:nth-child(3) { transform: translateY(-6px) rotate(-45deg); }

.mobile-brand { font-weight: 700; font-size: var(--el-fs-sm); }

/* Aligned with the shared 720px breakpoint. It was 640px, which left tablets in
   a gap: too wide for the drawer, no hover to open the rail. */
@media (max-width: 720px) {
  .app-layout { flex-direction: column; }

  .mobile-topbar { display: flex; }

  .scrim {
    display: block;
    position: fixed; inset: 0;
    background: rgba(15, 23, 42, 0.45);
    z-index: 90;
  }

  .sidebar {
    position: fixed;
    top: calc(52px + env(safe-area-inset-top, 0px));
    left: 0; bottom: 0;
    width: 260px;
    transform: translateX(-100%);
    transition: transform var(--el-t-slow) var(--el-ease);
    z-index: 100;
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  .sidebar:hover, .sidebar:focus-within { width: 260px; }

  .sidebar.mobile-open { transform: translateX(0); }

  /* On a phone the drawer is always the wide form — there is no rail to expand,
     so the toggle has nothing to do and is removed rather than left inert. */
  .rail-toggle { display: none; }
  .nav-label, .brand-name, .user-name, .logout-label { opacity: 1 !important; }
  .nav-link { min-height: var(--el-touch-lg); }

  .main-content { padding-top: calc(52px + env(safe-area-inset-top, 0px)); }
}

.fade-enter-active, .fade-leave-active { transition: opacity var(--el-t) var(--el-ease); }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .sidebar, .bars i, .nav-label, .brand-name, .user-name, .logout-label {
    transition: none;
  }
}
</style>
