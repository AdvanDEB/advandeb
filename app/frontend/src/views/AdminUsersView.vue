<template>
  <div class="admin-users-view">
    <header class="page-header">
      <h1>Users</h1>
      <p class="subtitle">Create, search, and manage AdvanDEB accounts.</p>
    </header>

    <!-- Filters -->
    <section class="card">
      <form class="filters" @submit.prevent="onSearch">
        <div class="field grow">
          <label for="q">Search</label>
          <input id="q" v-model="filters.q" type="text" placeholder="Email or name…" />
        </div>
        <div class="field">
          <label for="role">Role</label>
          <select id="role" v-model="filters.role">
            <option value="">Any</option>
            <option v-for="r in USER_ROLES" :key="r" :value="r">{{ roleLabel(r) }}</option>
          </select>
        </div>
        <div class="field">
          <label for="status">Status</label>
          <select id="status" v-model="filters.status">
            <option value="">Any</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
          </select>
        </div>
        <button type="submit" class="btn">Search</button>
        <button type="button" class="btn primary new-user-btn" @click="openCreateModal">+ New user</button>
      </form>
    </section>

    <!-- Table -->
    <section class="card">
      <p v-if="loading" class="muted">Loading…</p>
      <p v-else-if="users.length === 0" class="muted">No users match this search.</p>
      <table v-else class="users-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Name</th>
            <th>Roles</th>
            <th>Status</th>
            <th>Created</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.email }}</td>
            <td>{{ u.full_name || '—' }}</td>
            <td>
              <span
                v-for="r in USER_ROLES"
                :key="r"
                :class="['role-pill', { active: u.roles.includes(r) }]"
                :title="u.roles.includes(r) ? `Remove ${roleLabel(r)}` : `Grant ${roleLabel(r)}`"
                @click="toggleRole(u, r)"
              >
                {{ roleLabel(r) }}
              </span>
            </td>
            <td>
              <span :class="['status-badge', u.status]">{{ u.status }}</span>
              <span v-if="!u.chat_history_visible_to_admin" class="opted-out-badge" title="This user has opted out of staff chat access">
                opted out
              </span>
            </td>
            <td>{{ formatDate(u.created_at) }}</td>
            <td class="actions">
              <button
                class="btn small"
                :disabled="!u.chat_history_visible_to_admin"
                :title="!u.chat_history_visible_to_admin ? 'User has opted out of staff chat access' : ''"
                @click="viewChats(u)"
              >
                Chats
              </button>
              <button
                class="btn small"
                :disabled="busyId === u.id || isSelf(u)"
                :title="isSelf(u) ? 'You cannot change your own status' : ''"
                @click="onToggleStatus(u)"
              >
                {{ u.status === 'suspended' ? 'Activate' : 'Suspend' }}
              </button>
              <button class="btn small" :disabled="busyId === u.id" @click="onResetPassword(u)">
                Reset password
              </button>
              <button
                class="btn small danger"
                :disabled="busyId === u.id || isSelf(u)"
                :title="isSelf(u) ? 'You cannot delete your own account' : ''"
                @click="onDelete(u)"
              >
                Delete
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="!loading && total > 0" class="pagination">
        <span class="muted">Showing {{ rangeStart }}–{{ rangeEnd }} of {{ total }}</span>
        <div class="pagination-buttons">
          <button class="btn small" :disabled="skip === 0" @click="prevPage">Prev</button>
          <button class="btn small" :disabled="rangeEnd >= total" @click="nextPage">Next</button>
        </div>
      </div>
    </section>

    <!-- Create-user modal -->
    <div v-if="showCreateModal" class="modal-backdrop" @click.self="showCreateModal = false">
      <div class="modal">
        <h3>New user</h3>
        <form class="create-form" @submit.prevent="onCreate">
          <div class="field">
            <label for="new-email">Email</label>
            <input id="new-email" v-model="createForm.email" type="email" required autocomplete="off" />
          </div>
          <div class="field">
            <label for="new-name">Full name <span class="optional">(optional)</span></label>
            <input id="new-name" v-model="createForm.full_name" type="text" />
          </div>
          <div class="field">
            <label>Roles</label>
            <div class="role-checkboxes">
              <label v-for="r in USER_ROLES" :key="r" class="checkbox-label">
                <input type="checkbox" :value="r" v-model="createForm.roles" />
                {{ roleLabel(r) }}
              </label>
            </div>
          </div>
          <div class="field">
            <label for="new-password">Password</label>
            <div class="password-row">
              <input id="new-password" v-model="createForm.password" type="text" required autocomplete="off" />
              <button type="button" class="btn small" @click="createForm.password = generatePassword()">
                Generate
              </button>
            </div>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn small" @click="showCreateModal = false">Cancel</button>
            <button type="submit" class="btn primary small" :disabled="creating">
              {{ creating ? 'Creating…' : 'Create user' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Password-reveal modal (create + reset share this) -->
    <div v-if="revealed" class="modal-backdrop" @click.self="revealed = null">
      <div class="modal">
        <h3>Password for {{ revealed.email }}</h3>
        <p class="muted">This is shown once — copy it now and share it with the user directly.</p>
        <div class="password-reveal">
          <code>{{ revealed.password }}</code>
          <button class="btn small" @click="copyPassword">{{ copied ? 'Copied!' : 'Copy' }}</button>
        </div>
        <div class="modal-actions">
          <button class="btn small" @click="revealed = null">Done</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import {
  assignRole,
  createUser,
  deleteUser,
  generatePassword,
  listUsers,
  removeRole,
  resetPassword,
  setStatus,
} from '@/utils/usersApi'
import { USER_ROLES, type AdminUser } from '@/types/user'

const authStore = useAuthStore()
const notifs = useNotificationsStore()
const router = useRouter()

const users = ref<AdminUser[]>([])
const total = ref(0)
const loading = ref(true)
const skip = ref(0)
const limit = 20
const busyId = ref<string | null>(null)

const filters = reactive({ q: '', role: '', status: '' })

const showCreateModal = ref(false)
const creating = ref(false)
const createForm = reactive({
  email: '',
  full_name: '',
  password: generatePassword(),
  roles: ['knowledge_explorator'] as string[],
})

const revealed = ref<{ email: string; password: string } | null>(null)
const copied = ref(false)

const rangeStart = computed(() => (total.value === 0 ? 0 : skip.value + 1))
const rangeEnd = computed(() => Math.min(skip.value + users.value.length, total.value))

const ROLE_LABELS: Record<string, string> = {
  administrator: 'Admin',
  knowledge_curator: 'Curator',
  knowledge_explorator: 'User',
}

function roleLabel(role: string): string {
  return ROLE_LABELS[role] || role
}

function isSelf(u: AdminUser): boolean {
  return u.id === authStore.user?.id
}

function viewChats(u: AdminUser) {
  if (!u.chat_history_visible_to_admin) return
  router.push(`/admin/users/${u.id}/chats`)
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString()
  } catch {
    return iso
  }
}

async function refreshUsers() {
  loading.value = true
  try {
    const res = await listUsers({
      skip: skip.value,
      limit,
      q: filters.q || undefined,
      role: filters.role || undefined,
      status: filters.status || undefined,
    })
    users.value = res.items
    total.value = res.total
  } catch {
    // api interceptor already toasts non-401 errors
  } finally {
    loading.value = false
  }
}

function onSearch() {
  skip.value = 0
  refreshUsers()
}

function nextPage() {
  skip.value += limit
  refreshUsers()
}

function prevPage() {
  skip.value = Math.max(0, skip.value - limit)
  refreshUsers()
}

function openCreateModal() {
  createForm.email = ''
  createForm.full_name = ''
  createForm.password = generatePassword()
  createForm.roles = ['knowledge_explorator']
  showCreateModal.value = true
}

async function onCreate() {
  if (!createForm.email || !createForm.password) return
  creating.value = true
  try {
    await createUser({
      email: createForm.email,
      full_name: createForm.full_name || undefined,
      password: createForm.password,
      roles: createForm.roles,
    })
    revealed.value = { email: createForm.email, password: createForm.password }
    showCreateModal.value = false
    notifs.success(`User ${createForm.email} created`)
    await refreshUsers()
  } catch {
    // interceptor surfaces the sanitized backend detail
  } finally {
    creating.value = false
  }
}

async function toggleRole(u: AdminUser, role: string) {
  if (isSelf(u) && role === 'administrator' && u.roles.includes(role)) {
    notifs.error('You cannot remove your own administrator role')
    return
  }
  busyId.value = u.id
  try {
    const updated = u.roles.includes(role) ? await removeRole(u.id, role) : await assignRole(u.id, role)
    const idx = users.value.findIndex((x) => x.id === u.id)
    if (idx !== -1) users.value[idx] = updated
  } catch {
    // interceptor toasts the failure
  } finally {
    busyId.value = null
  }
}

async function onToggleStatus(u: AdminUser) {
  const next = u.status === 'suspended' ? 'active' : 'suspended'
  if (next === 'suspended' && !confirm(`Suspend ${u.email}? They won't be able to log in.`)) return
  busyId.value = u.id
  try {
    const updated = await setStatus(u.id, next)
    const idx = users.value.findIndex((x) => x.id === u.id)
    if (idx !== -1) users.value[idx] = updated
    notifs.success(`${u.email} ${next === 'suspended' ? 'suspended' : 'reactivated'}`)
  } catch {
    // interceptor toasts the failure
  } finally {
    busyId.value = null
  }
}

async function onResetPassword(u: AdminUser) {
  if (!confirm(`Generate a new password for ${u.email}? Their current password will stop working.`)) return
  busyId.value = u.id
  try {
    const { password } = await resetPassword(u.id)
    revealed.value = { email: u.email, password }
  } catch {
    // interceptor toasts the failure
  } finally {
    busyId.value = null
  }
}

async function onDelete(u: AdminUser) {
  if (!confirm(`Permanently delete ${u.email}? This cannot be undone.`)) return
  busyId.value = u.id
  try {
    await deleteUser(u.id)
    notifs.info(`${u.email} deleted`)
    await refreshUsers()
  } catch {
    // interceptor toasts the failure
  } finally {
    busyId.value = null
  }
}

async function copyPassword() {
  if (!revealed.value) return
  try {
    await navigator.clipboard.writeText(revealed.value.password)
    copied.value = true
    setTimeout(() => (copied.value = false), 2000)
  } catch {
    // clipboard API unavailable — user can still select/copy manually
  }
}

onMounted(refreshUsers)
</script>

<style scoped>
.admin-users-view {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  max-width: 1100px;
}
.page-header h1 { font-size: 1.5rem; font-weight: 700; color: #111827; }
.subtitle { color: #6b7280; line-height: 1.6; margin-top: 0.4rem; }

.card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 1.25rem 1.5rem;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: flex-end;
}
.new-user-btn { margin-left: auto; }

.field { display: flex; flex-direction: column; gap: 0.3rem; min-width: 140px; }
.field.grow { flex: 1; min-width: 220px; }
.field label { font-size: 0.8rem; font-weight: 600; color: #4b5563; }
.optional { font-weight: 400; color: #9ca3af; }
.field input, .field select {
  padding: 0.5rem 0.6rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 0.9rem;
}

.btn {
  padding: 0.5rem 1rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #fff;
  color: #374151;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
}
.btn:hover:not(:disabled) { background: #f3f4f6; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.small { padding: 0.35rem 0.7rem; font-size: 0.8rem; }
.btn.primary { background: #3b82f6; border-color: #3b82f6; color: #fff; }
.btn.primary:hover:not(:disabled) { background: #2563eb; }
.btn.danger { color: #dc2626; border-color: #fecaca; }
.btn.danger:hover:not(:disabled) { background: #fef2f2; }

.muted { color: #9ca3af; font-size: 0.9rem; }

.users-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.users-table th {
  text-align: left;
  padding: 0.5rem 0.6rem;
  border-bottom: 2px solid #e5e7eb;
  color: #6b7280;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.users-table td { padding: 0.6rem; border-bottom: 1px solid #f3f4f6; vertical-align: middle; }

.role-pill {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  margin: 0 0.2rem 0.2rem 0;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid #e5e7eb;
  color: #9ca3af;
  background: #f9fafb;
  user-select: none;
}
.role-pill.active { background: #dbeafe; border-color: #93c5fd; color: #1d4ed8; }

.status-badge {
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
}
.status-badge.active { background: #dcfce7; color: #15803d; }
.status-badge.suspended { background: #fee2e2; color: #b91c1c; }

.opted-out-badge {
  display: inline-block;
  margin-left: 0.4rem;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
  background: #f3f4f6;
  color: #6b7280;
}

.actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }

.pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 1rem;
}
.pagination-buttons { display: flex; gap: 0.5rem; }

.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 300;
}
.modal {
  background: #fff;
  border-radius: 10px;
  padding: 1.5rem;
  width: 100%;
  max-width: 420px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
}
.modal h3 { font-size: 1.1rem; font-weight: 700; margin-bottom: 0.75rem; color: #111827; }

.create-form { display: flex; flex-direction: column; gap: 0.9rem; }
.role-checkboxes { display: flex; flex-direction: column; gap: 0.35rem; }
.checkbox-label { display: flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; color: #374151; }
.password-row { display: flex; gap: 0.5rem; }
.password-row input { flex: 1; }

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.password-reveal {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  background: #f3f4f6;
  border-radius: 6px;
  padding: 0.6rem 0.8rem;
  margin: 0.75rem 0;
}
.password-reveal code {
  flex: 1;
  font-size: 0.95rem;
  word-break: break-all;
}
</style>
