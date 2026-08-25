<template>
  <div class="privacy-view">
    <header class="page-header">
      <h1>Privacy</h1>
      <p class="subtitle">
        AdvanDEB is a research project. AdvanDEB staff (administrators) may review
        conversation history to improve the assistant and support the research —
        you agreed to this when you joined. You can opt out at any time below;
        this only affects future staff access, not whether the app works.
      </p>
    </header>

    <section class="card">
      <h2>Staff access to my chat history</h2>
      <p v-if="loading" class="muted">Loading…</p>
      <div v-else class="toggle-row">
        <label class="switch">
          <input type="checkbox" :checked="optedIn" :disabled="saving" @change="onToggle" />
          <span class="slider"></span>
        </label>
        <div class="toggle-label">
          <strong>{{ optedIn ? 'Staff can view my chats' : "Staff can't view my chats" }}</strong>
          <p class="muted">
            {{ optedIn
              ? 'Administrators may open your conversation history for research review.'
              : 'You have opted out — administrators cannot open your conversation history.' }}
          </p>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Who has looked at my chats</h2>
      <p v-if="logLoading" class="muted">Loading…</p>
      <p v-else-if="log.length === 0" class="muted">No staff member has accessed your chat history yet.</p>
      <table v-else class="log-table">
        <thead>
          <tr>
            <th>Staff member</th>
            <th>What</th>
            <th>When</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(entry, i) in log" :key="i">
            <td>{{ entry.admin_email }}</td>
            <td>{{ entry.session_id ? 'Opened a conversation' : 'Viewed your conversation list' }}</td>
            <td>{{ formatDate(entry.accessed_at) }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import { updateMyProfile } from '@/utils/usersApi'
import { getMyAccessLog } from '@/utils/adminChatApi'
import type { ChatAccessLogEntry } from '@/types/adminChat'

const authStore = useAuthStore()
const notifs = useNotificationsStore()

const loading = ref(true)
const saving = ref(false)
const log = ref<ChatAccessLogEntry[]>([])
const logLoading = ref(true)

const optedIn = computed(() => authStore.user?.chat_history_visible_to_admin ?? true)

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

async function onToggle(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  saving.value = true
  try {
    const updated = await updateMyProfile({ chat_history_visible_to_admin: checked })
    if (authStore.user) authStore.user.chat_history_visible_to_admin = updated.chat_history_visible_to_admin
    notifs.success(checked ? 'Staff can now view your chats' : 'You have opted out of staff chat access')
  } catch {
    // interceptor toasts the failure; revert the checkbox by re-render
    (event.target as HTMLInputElement).checked = optedIn.value
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  loading.value = false
  try {
    log.value = await getMyAccessLog()
  } catch {
    // interceptor toasts
  } finally {
    logLoading.value = false
  }
})
</script>

<style scoped>
.privacy-view {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  max-width: 700px;
}
.page-header h1 { font-size: 1.5rem; font-weight: 700; color: #111827; }
.subtitle { color: #6b7280; line-height: 1.6; margin-top: 0.4rem; }

.card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 1.25rem 1.5rem;
}
.card h2 { font-size: 1.05rem; font-weight: 600; color: #374151; margin-bottom: 1rem; }

.muted { color: #9ca3af; font-size: 0.9rem; }

.toggle-row { display: flex; align-items: center; gap: 1rem; }

.switch { position: relative; display: inline-block; width: 44px; height: 24px; flex-shrink: 0; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider {
  position: absolute; cursor: pointer; inset: 0;
  background-color: #d1d5db; transition: 0.2s; border-radius: 999px;
}
.slider::before {
  position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px;
  background-color: white; transition: 0.2s; border-radius: 50%;
}
.switch input:checked + .slider { background-color: #3b82f6; }
.switch input:checked + .slider::before { transform: translateX(20px); }
.switch input:disabled + .slider { opacity: 0.6; cursor: not-allowed; }

.toggle-label strong { font-size: 0.95rem; color: #111827; }
.toggle-label p { margin-top: 0.2rem; }

.log-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.log-table th {
  text-align: left;
  padding: 0.5rem 0.6rem;
  border-bottom: 2px solid #e5e7eb;
  color: #6b7280;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.log-table td { padding: 0.55rem 0.6rem; border-bottom: 1px solid #f3f4f6; }
</style>
