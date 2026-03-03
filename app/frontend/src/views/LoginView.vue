<template>
  <div class="login">
    <h1>Login to AdvanDEB</h1>

    <form class="login-form" @submit.prevent="handleNativeLogin">
      <div class="field">
        <label for="email">Email</label>
        <input
          id="email"
          v-model="email"
          type="email"
          autocomplete="email"
          placeholder="you@example.com"
          required
        />
      </div>
      <div class="field">
        <label for="password">Password</label>
        <input
          id="password"
          v-model="password"
          type="password"
          autocomplete="current-password"
          placeholder="Password"
          required
        />
      </div>
      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
      <button type="submit" :disabled="loading" class="submit-btn">
        {{ loading ? 'Signing in…' : 'Sign in' }}
      </button>
    </form>

    <div v-if="authStore.googleOAuthEnabled" class="divider">or</div>

    <button
      v-if="authStore.googleOAuthEnabled"
      @click="handleGoogleLogin"
      class="google-btn"
    >
      Sign in with Google
    </button>

    <p class="hint">Don't have an account? Contact an administrator.</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const authStore = useAuthStore()
const router = useRouter()

const email = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

async function handleNativeLogin() {
  errorMessage.value = ''
  loading.value = true
  try {
    await authStore.loginNative(email.value, password.value)
    router.push('/')
  } catch {
    errorMessage.value = 'Invalid email or password.'
  } finally {
    loading.value = false
  }
}

function handleGoogleLogin() {
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
  const redirectUri = `${window.location.origin}/login`
  const scope = 'openid email profile'

  const authUrl =
    `https://accounts.google.com/o/oauth2/v2/auth?` +
    `client_id=${clientId}&` +
    `redirect_uri=${encodeURIComponent(redirectUri)}&` +
    `response_type=code&` +
    `scope=${encodeURIComponent(scope)}&` +
    `access_type=offline&` +
    `prompt=consent`

  window.location.href = authUrl
}

// Handle OAuth callback
const urlParams = new URLSearchParams(window.location.search)
const code = urlParams.get('code')

if (code) {
  const redirectUri = `${window.location.origin}/login`
  authStore.login(code, redirectUri).then(() => {
    router.push('/')
  }).catch((error) => {
    console.error('Google login failed:', error)
    errorMessage.value = 'Google sign-in failed. Please try again.'
  })
}
</script>

<style scoped>
.login {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 2rem;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  width: 100%;
  max-width: 360px;
  margin-top: 2rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.field label {
  font-size: 0.875rem;
  font-weight: 500;
}

.field input {
  padding: 0.6rem 0.75rem;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 1rem;
}

.field input:focus {
  outline: none;
  border-color: #4285f4;
}

.error {
  color: #d32f2f;
  font-size: 0.875rem;
}

.submit-btn {
  padding: 0.75rem;
  background: #4285f4;
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.2s;
}

.submit-btn:hover:not(:disabled) {
  background: #357ae8;
}

.submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.divider {
  margin: 1.5rem 0 0.5rem;
  color: #888;
  font-size: 0.875rem;
}

.google-btn {
  padding: 0.75rem 2rem;
  background: white;
  color: #444;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.2s;
}

.google-btn:hover {
  background: #f5f5f5;
}

.hint {
  margin-top: 2rem;
  font-size: 0.8rem;
  color: #888;
}
</style>
