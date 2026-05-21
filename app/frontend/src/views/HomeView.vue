<template>
  <div class="home">
    <div v-if="authStore.isAuthenticated" class="dashboard">
      <h1>AdvanDEB Modeling Assistant</h1>
      <p>Main platform GUI for knowledge building and modeling</p>
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

        <router-link to="/kb" class="feature-card">
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

    <div v-else class="anonymous">
      <section class="hero">
        <h1>AdvanDEB</h1>
        <p class="subtitle">A curated knowledge graph for Dynamic Energy Budget biology</p>
        <p class="lede">
          AdvanDEB consolidates roughly 1,300 ingested research papers into a queryable
          knowledge graph backed by ArangoDB. A multi-agent retrieval-augmented generation
          system answers questions about DEB theory and its applications, while preserving
          full provenance from every answer back to the supporting fact, the originating
          chunk, and the source document.
        </p>
        <div class="cta-row">
          <router-link to="/login" class="cta-primary">Sign in</router-link>
          <a href="#how-it-works" class="cta-secondary">Learn more</a>
        </div>
      </section>

      <section id="how-it-works" class="section">
        <h2>How it works</h2>
        <div class="cards">
          <article class="card">
            <div class="step">1</div>
            <h3>Ingest</h3>
            <p>
              PDFs flow through chunking, embedding (ChromaDB), and entity/fact extraction
              (Ollama-hosted local LLMs).
            </p>
          </article>
          <article class="card">
            <div class="step">2</div>
            <h3>Curate</h3>
            <p>
              Knowledge curators review extracted facts and stylized facts; only published
              items enter the graph.
            </p>
          </article>
          <article class="card">
            <div class="step">3</div>
            <h3>Explore</h3>
            <p>
              Query the graph via the chat assistant; every answer carries a full citation
              trail back to the original paper.
            </p>
          </article>
        </div>
      </section>

      <section class="section">
        <h2>Components</h2>
        <div class="cards">
          <article class="card">
            <h3>Modeling Assistant</h3>
            <p>
              The web GUI for asking questions, browsing facts, and inspecting the
              provenance trail behind each answer.
            </p>
          </article>
          <article class="card">
            <h3>Knowledge Builder</h3>
            <p>
              A reusable Python library that handles ingestion, embedding, fact extraction,
              and graph construction across the corpus.
            </p>
          </article>
          <article class="card">
            <h3>MCP gateway and agents</h3>
            <p>
              A Model Context Protocol server exposing graph and retrieval tools to the
              curator, planner, retrieval, and synthesis agents.
            </p>
          </article>
        </div>
      </section>

      <footer class="site-footer">
        <p>
          AdvanDEB is a research platform for DEB-biology knowledge.
          Contact: <a href="mailto:domagojhack@gmail.com">domagojhack@gmail.com</a>.
        </p>
      </footer>
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
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, Cantarell, sans-serif;
  color: #1f2937;
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

/* Anonymous landing */
.anonymous {
  display: flex;
  flex-direction: column;
  gap: 4rem;
}

.hero {
  padding: 3rem 0 1rem;
  text-align: left;
}

.hero h1 {
  font-size: 3rem;
  margin: 0 0 0.5rem;
  letter-spacing: -0.02em;
}

.subtitle {
  font-size: 1.25rem;
  color: #4b5563;
  margin: 0 0 1.5rem;
}

.lede {
  font-size: 1rem;
  line-height: 1.6;
  color: #374151;
  max-width: 720px;
  margin: 0 0 2rem;
}

.cta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.cta-primary {
  display: inline-block;
  padding: 0.75rem 1.5rem;
  background: #4285f4;
  color: white;
  text-decoration: none;
  border-radius: 4px;
  font-weight: 500;
  transition: background 0.2s;
}

.cta-primary:hover {
  background: #357ae8;
}

.cta-secondary {
  display: inline-block;
  padding: 0.75rem 1.5rem;
  background: transparent;
  color: #1f2937;
  text-decoration: none;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-weight: 500;
  transition: background 0.2s;
}

.cta-secondary:hover {
  background: #f3f4f6;
}

.section h2 {
  font-size: 1.75rem;
  margin: 0 0 1.5rem;
  color: #111827;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 1.5rem;
}

.card {
  padding: 1.75rem;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
}

.card h3 {
  margin: 0 0 0.5rem;
  font-size: 1.15rem;
  color: #111827;
}

.card p {
  margin: 0;
  color: #4b5563;
  line-height: 1.55;
  font-size: 0.95rem;
}

.card .step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  background: #4285f4;
  color: white;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.site-footer {
  border-top: 1px solid #e5e7eb;
  padding: 1.5rem 0 0;
  color: #6b7280;
  font-size: 0.9rem;
}

.site-footer a {
  color: #4285f4;
  text-decoration: none;
}

.site-footer a:hover {
  text-decoration: underline;
}
</style>
