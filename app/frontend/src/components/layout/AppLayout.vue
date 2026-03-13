<template>
  <div class="app-layout">
    <!-- Mobile top bar -->
    <div class="mobile-topbar">
      <button
        class="hamburger"
        :aria-expanded="mobileOpen"
        aria-label="Toggle navigation"
        @click="mobileOpen = !mobileOpen"
      >
        ☰
      </button>
      <span class="mobile-brand">AdvanDEB</span>
    </div>

    <!-- Sidebar navigation -->
    <nav :class="['sidebar', { 'mobile-open': mobileOpen }]" aria-label="Main navigation">
      <div class="sidebar-brand">
        <span class="brand-icon">🧬</span>
        <span class="brand-name">AdvanDEB</span>
      </div>

      <ul class="nav-links">
        <li v-for="link in navLinks" :key="link.path">
          <router-link
            :to="link.path"
            :class="['nav-link', { active: isActive(link.path) }]"
            :title="link.label"
          >
            <span class="nav-icon">{{ link.icon }}</span>
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
            alt="User"
          />
          <div v-else class="user-avatar-placeholder">
            {{ initials }}
          </div>
          <span class="user-name">{{ authStore.user.full_name || authStore.user.email }}</span>
        </div>
        <button class="logout-btn" @click="handleLogout" title="Logout">⏏</button>
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
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import ToastNotifications from './ToastNotifications.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const mobileOpen = ref(false)

const navLinks = [
  { path: '/',           icon: '⌂',  label: 'Home' },
  { path: '/chat',       icon: '💬', label: 'Chat' },
  { path: '/documents',  icon: '📄', label: 'Documents' },
  { path: '/graph',      icon: '🕸',  label: 'Graph' },
  { path: '/facts',      icon: '🔬', label: 'Facts' },
  { path: '/scenarios',  icon: '⚗',  label: 'Scenarios' },
  { path: '/models',     icon: '📐', label: 'Models' },
]

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

// Close mobile nav on route change
router.afterEach(() => { mobileOpen.value = false })
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  width: 56px;
  background: #1e293b;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0.75rem 0;
  flex-shrink: 0;
  transition: width 0.2s;
  overflow: hidden;
}

.sidebar:hover {
  width: 180px;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: white;
  font-weight: 700;
  font-size: 0.9rem;
  padding: 0 0.75rem;
  height: 40px;
  white-space: nowrap;
  width: 100%;
  margin-bottom: 1rem;
}

.brand-icon { font-size: 1.4rem; flex-shrink: 0; }
.brand-name { opacity: 0; transition: opacity 0.15s; }
.sidebar:hover .brand-name { opacity: 1; }

.nav-links {
  list-style: none;
  width: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 0.75rem;
  color: #94a3b8;
  text-decoration: none;
  border-radius: 6px;
  margin: 0 0.25rem;
  white-space: nowrap;
  font-size: 0.85rem;
  transition: background 0.15s, color 0.15s;
}

.nav-link:hover { background: #334155; color: #e2e8f0; }
.nav-link.active { background: #3b82f6; color: white; }

.nav-icon { font-size: 1.1rem; flex-shrink: 0; width: 20px; text-align: center; }
.nav-label { opacity: 0; transition: opacity 0.15s; }
.sidebar:hover .nav-label { opacity: 1; }

.sidebar-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 0.5rem 0.75rem;
  gap: 0.5rem;
  border-top: 1px solid #334155;
  margin-top: auto;
  overflow: hidden;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
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
  font-size: 0.75rem;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0;
  transition: opacity 0.15s;
}

.sidebar:hover .user-name { opacity: 1; }

.logout-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: #64748b;
  font-size: 1rem;
  flex-shrink: 0;
  padding: 0.2rem;
  display: none;
}

.sidebar:hover .logout-btn { display: block; }
.logout-btn:hover { color: #ef4444; }

.main-content {
  flex: 1;
  overflow: auto;
  display: flex;
  flex-direction: column;
}

/* ── Mobile ────────────────────────── */
.mobile-topbar {
  display: none;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 1rem;
  background: #1e293b;
  color: white;
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 200;
  height: 48px;
}

.hamburger {
  background: none; border: none; color: white;
  font-size: 1.2rem; cursor: pointer; padding: 0.2rem;
}

.mobile-brand { font-weight: 700; font-size: 0.9rem; }

@media (max-width: 640px) {
  .app-layout { flex-direction: column; }

  .mobile-topbar { display: flex; }

  .sidebar {
    position: fixed;
    top: 48px; left: 0; bottom: 0;
    width: 200px;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    z-index: 100;
  }

  .sidebar.mobile-open { transform: translateX(0); }

  /* Show labels always on mobile */
  .nav-label { opacity: 1; }
  .brand-name { opacity: 1; }
  .user-name  { opacity: 1; }
  .logout-btn { display: block; }

  .main-content { padding-top: 48px; }
}
</style>
