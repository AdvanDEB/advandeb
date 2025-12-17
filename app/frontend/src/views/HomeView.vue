<template>
  <div class="home">
    <h1>AdvanDEB Modeling Assistant</h1>
    <p>Main platform GUI for knowledge building and modeling</p>
    
    <div v-if="authStore.isAuthenticated" class="dashboard">
      <h2>Welcome, {{ authStore.user?.full_name || authStore.user?.email }}</h2>
      <div class="features">
        <router-link to="/documents" class="feature-card">
          <h3>Documents</h3>
          <p>Upload and manage documents</p>
        </router-link>
        
        <router-link to="/facts" class="feature-card">
          <h3>Facts</h3>
          <p>Browse and create knowledge facts</p>
        </router-link>
        
        <router-link to="/graph" class="feature-card">
          <h3>Knowledge Graph</h3>
          <p>Explore the knowledge network</p>
        </router-link>
        
        <router-link to="/chat" class="feature-card">
          <h3>Chat Assistant</h3>
          <p>AI-powered knowledge assistant</p>
        </router-link>
        
        <router-link to="/scenarios" class="feature-card">
          <h3>Scenarios</h3>
          <p>Create modeling scenarios</p>
        </router-link>
        
        <router-link to="/models" class="feature-card">
          <h3>Models</h3>
          <p>Build and manage models</p>
        </router-link>
      </div>
    </div>
    
    <div v-else class="welcome">
      <router-link to="/login" class="login-btn">Login with Google</router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
</script>

<style scoped>
.home {
  padding: 2rem;
  max-width: 1200px;
  margin: 0 auto;
}

h1 {
  font-size: 2.5rem;
  margin-bottom: 1rem;
}

.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 1.5rem;
  margin-top: 2rem;
}

.feature-card {
  padding: 2rem;
  border: 1px solid #ddd;
  border-radius: 8px;
  text-decoration: none;
  color: inherit;
  transition: all 0.3s;
}

.feature-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

.feature-card h3 {
  margin-bottom: 0.5rem;
}

.login-btn {
  display: inline-block;
  padding: 1rem 2rem;
  background: #4285f4;
  color: white;
  text-decoration: none;
  border-radius: 4px;
  margin-top: 2rem;
}
</style>
