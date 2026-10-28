<template>
  <!-- The page's main landmark: the login page renders outside AppLayout. -->
  <main id="main-content" class="login" tabindex="-1">
    <router-link to="/" class="home-link">← AdvanDEB home</router-link>
    <h1>Sign in to AdvanDEB</h1>
    <p v-if="sentHere" class="why">Sign in to continue to that page.</p>

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
          :aria-invalid="errorMessage ? 'true' : undefined"
          :aria-describedby="errorMessage ? 'login-error' : undefined"
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
          :aria-invalid="errorMessage ? 'true' : undefined"
          :aria-describedby="errorMessage ? 'login-error' : undefined"
        />
      </div>
      <!-- role=alert: a failed sign-in is announced, not just painted red. -->
      <p v-if="errorMessage" id="login-error" class="error" role="alert">{{ errorMessage }}</p>
      <button type="submit" :disabled="loading" class="submit-btn">
        {{ loading ? 'Signing in…' : 'Sign in' }}
      </button>
    </form>

    <!-- Temporarily hidden; flip GOOGLE_LOGIN_HIDDEN to false to restore -->
    <div v-if="authStore.googleOAuthEnabled && !GOOGLE_LOGIN_HIDDEN" class="divider">or</div>

    <button
      v-if="authStore.googleOAuthEnabled && !GOOGLE_LOGIN_HIDDEN"
      @click="handleGoogleLogin"
      class="google-btn"
    >
      Sign in with Google
    </button>

    <p class="hint">Don't have an account? Contact an administrator.</p>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import axios from 'axios'
import { useAuthStore } from '@/stores/auth'
import { useRoute, useRouter } from 'vue-router'
import { beginGoogleFlow, pkceChallenge, safeRedirect, takeGoogleFlow } from '@/utils/oauth'

const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()

const GOOGLE_LOGIN_HIDDEN = true

const email = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

/**
 * Where to go once signed in: the page that sent the visitor here — as
 * `?redirect=` when a session expired on it, or the route the guard turned
 * away — and home otherwise.
 */
function afterLogin(): string {
  return safeRedirect(route.query.redirect ?? route.redirectedFrom?.fullPath)
}

/** Sent here from a page that needs an account (the router adds ?redirect=). */
const sentHere = computed(() => afterLogin() !== '/')

/** The server's reason, for the refusals worth telling apart. */
function loginError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err) && err.response?.status === 403) {
    const detail = err.response.data?.detail
    if (detail === 'Account suspended') return 'This account is suspended. Contact an administrator.'
    if (typeof detail === 'string') return detail
  }
  return fallback
}

async function handleNativeLogin() {
  errorMessage.value = ''
  loading.value = true
  try {
    await authStore.loginNative(email.value, password.value)
    router.replace(afterLogin())
  } catch (err) {
    errorMessage.value = loginError(err, 'Invalid email or password.')
  } finally {
    loading.value = false
  }
}

async function handleGoogleLogin() {
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
  if (!clientId) {
    errorMessage.value = 'Google sign-in is not configured.'
    return
  }
  const redirectUri = `${window.location.origin}/login`
  // `state` ties the callback to this tab's request (no login CSRF); PKCE
  // makes an intercepted authorization code useless without the verifier.
  const flow = beginGoogleFlow(afterLogin())
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: 'openid email profile',
    state: flow.state,
    code_challenge: await pkceChallenge(flow.codeVerifier),
    code_challenge_method: 'S256',
  })

  window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?${params}`
}

// Handle OAuth callback
const urlParams = new URLSearchParams(window.location.search)
const code = urlParams.get('code')

if (code || urlParams.get('error')) {
  const flow = takeGoogleFlow(urlParams.get('state'))
  // Drop code/state from the address bar whatever happens next.
  router.replace({ name: 'login', query: {} })

  if (!code) {
    errorMessage.value = 'Google sign-in was cancelled.'
  } else if (!flow) {
    errorMessage.value = 'Google sign-in could not be verified. Please try again.'
  } else {
    const redirectUri = `${window.location.origin}/login`
    authStore.login(code, redirectUri, flow.codeVerifier).then(() => {
      router.replace(flow.redirect)
    }).catch((error) => {
      console.error('Google login failed:', error)
      errorMessage.value = loginError(error, 'Google sign-in failed. Please try again.')
    })
  }
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

.login:focus { outline: none; }   /* focused only by the skip link / route focus */

.home-link {
  /* Left edge of the form column. */
  width: 100%;
  max-width: 360px;
  display: inline-flex;
  align-items: center;
  min-height: var(--app-touch);
  color: var(--app-primary-strong);
  text-decoration: none;
  font-size: 0.9rem;
}
.home-link:hover { text-decoration: underline; }
.home-link:focus-visible { outline: var(--app-focus); outline-offset: 2px; }

.why {
  margin-top: 0.75rem;
  color: #4b5563;
  font-size: 0.9rem;
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
  min-height: var(--app-touch);   /* 44px: was 39px on a phone */
}

/* Was outline:none with only a 1px border hue change. */
.field input:focus {
  outline: var(--app-focus);
  outline-offset: 1px;
  border-color: var(--app-primary-strong);
}

.field input[aria-invalid='true'] { border-color: #d32f2f; }

.error {
  color: #d32f2f;
  font-size: 0.875rem;
}

.submit-btn {
  min-height: var(--app-touch);
  padding: 0.75rem;
  background: var(--app-primary-strong);   /* was #4285f4: 3.56:1 with white */
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.2s;
}

.submit-btn:hover:not(:disabled) {
  background: var(--app-primary-ink);
}

.submit-btn:focus-visible { outline: var(--app-focus); outline-offset: 2px; }

.submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.divider {
  margin: 1.5rem 0 0.5rem;
  color: var(--app-ink-3);
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
  color: var(--app-ink-3);   /* #6b7280, 4.8:1 (was #888, 3.5:1) */
}
</style>
