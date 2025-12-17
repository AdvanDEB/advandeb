<template>
  <div class="login">
    <h1>Login to AdvanDEB</h1>
    <p>Sign in with your Google account to access the platform</p>
    <button @click="handleGoogleLogin" class="google-btn">
      Sign in with Google
    </button>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const authStore = useAuthStore()
const router = useRouter()

function handleGoogleLogin() {
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
  const redirectUri = `${window.location.origin}/login`
  const scope = 'openid email profile'
  
  const authUrl = `https://accounts.google.com/o/oauth2/v2/auth?` +
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
    console.error('Login failed:', error)
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

.google-btn {
  margin-top: 2rem;
  padding: 1rem 2rem;
  background: #4285f4;
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.3s;
}

.google-btn:hover {
  background: #357ae8;
}
</style>
