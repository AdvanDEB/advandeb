<template>
  <div class="documentation-view">
    <header class="doc-header">
      <div class="header-copy">
        <p class="eyebrow">User documentation</p>
        <h1>Documentation</h1>
        <p class="subtitle">
          Practical guidance for using AdvanDEB, written for users who know basic
          scientific reading but do not need to know the internal code.
        </p>
      </div>

      <div class="role-panel" aria-label="Documentation access">
        <span class="role-label">Showing guidance for</span>
        <div class="role-chips">
          <span v-for="role in displayRoles" :key="role" class="role-chip">
            {{ roleLabel(role) }}
          </span>
        </div>
      </div>
    </header>

    <div class="doc-shell">
      <aside class="toc" aria-label="Documentation contents">
        <span class="toc-title">Contents</span>
        <a
          v-for="section in visibleSections"
          :key="section.id"
          class="toc-link"
          :href="`#${section.id}`"
        >
          {{ section.title }}
        </a>
      </aside>

      <main class="doc-content">
        <section
          v-for="section in visibleSections"
          :id="section.id"
          :key="section.id"
          class="doc-section"
        >
          <div class="section-heading">
            <div>
              <p class="section-kicker">{{ audienceSummary(section.audiences) }}</p>
              <h2>{{ section.title }}</h2>
            </div>
            <span class="section-badge">{{ section.badge }}</span>
          </div>

          <p
            v-for="paragraph in section.paragraphs"
            :key="paragraph"
            class="doc-paragraph"
          >
            {{ paragraph }}
          </p>

          <div v-if="section.items?.length" class="item-list">
            <article v-for="item in section.items" :key="item.title" class="doc-item">
              <h3>{{ item.title }}</h3>
              <p>{{ item.text }}</p>
            </article>
          </div>

          <div v-if="section.note" class="doc-note">
            <strong>{{ section.note.title }}</strong>
            <p>{{ section.note.text }}</p>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

type RoleName = 'knowledge_explorator' | 'knowledge_curator' | 'administrator'
type Audience = 'all' | RoleName

interface DocItem {
  title: string
  text: string
}

interface DocSection {
  id: string
  title: string
  badge: string
  audiences: Audience[]
  paragraphs: string[]
  items?: DocItem[]
  note?: DocItem
}

const authStore = useAuthStore()

const roleLabels: Record<RoleName, string> = {
  knowledge_explorator: 'Knowledge explorer',
  knowledge_curator: 'Knowledge curator',
  administrator: 'Administrator',
}

function isRoleName(role: string): role is RoleName {
  return role === 'knowledge_explorator'
    || role === 'knowledge_curator'
    || role === 'administrator'
}

const displayRoles = computed<RoleName[]>(() => {
  const roles = (authStore.user?.roles ?? []).filter(isRoleName)
  return roles.length ? roles : ['knowledge_explorator']
})

const effectiveRoles = computed<Set<RoleName>>(() => {
  const roles = new Set(displayRoles.value)
  if (roles.has('administrator')) {
    roles.add('knowledge_curator')
  }
  return roles
})

const visibleSections = computed(() => documentationSections.filter((section) =>
  section.audiences.includes('all')
  || section.audiences.some((audience) =>
    audience !== 'all' && effectiveRoles.value.has(audience),
  ),
))

function roleLabel(role: RoleName): string {
  return roleLabels[role]
}

function audienceSummary(audiences: Audience[]): string {
  if (audiences.includes('all')) return 'All users'
  return audiences
    .filter((audience): audience is RoleName => audience !== 'all')
    .map(roleLabel)
    .join(', ')
}

const documentationSections: DocSection[] = [
  {
    id: 'quick-start',
    title: 'Quick start',
    badge: 'Start here',
    audiences: ['all'],
    paragraphs: [
      'AdvanDEB helps you explore research knowledge about Dynamic Energy Budget biology. A good first session is simple: sign in, open Chat, ask one focused scientific question, then inspect the cited sources behind the answer.',
      'The app works best when questions are specific. For example, ask how temperature affects maintenance costs in ectotherms, or which studies support a particular DEB assumption. Short, precise questions give the assistant a clearer search target.',
    ],
    items: [
      {
        title: '1. Sign in',
        text: 'Use the sign-in page provided by your deployment. Most users sign in with email and password; Google sign-in may also appear when it is configured.',
      },
      {
        title: '2. Open Chat',
        text: 'Use Chat for scientific questions. Read the answer, then use citations and provenance to check which documents or facts support it.',
      },
      {
        title: '3. Browse the evidence',
        text: 'Use Documents to inspect the corpus and Facts to inspect extracted facts, stylized facts, and submitted fact suggestions.',
      },
      {
        title: '4. Add your own model key when needed',
        text: 'Use LLM Keys if you want to use your own Claude, ChatGPT, Gemini, GitHub Models, or NVIDIA key instead of the shared default model.',
      },
    ],
  },
  {
    id: 'introduction',
    title: 'Introduction',
    badge: 'Purpose',
    audiences: ['all'],
    paragraphs: [
      'AdvanDEB is a research support application for Dynamic Energy Budget (DEB) biology. DEB theory describes how organisms take up, store, and use energy for maintenance, growth, development, and reproduction.',
      'The application combines a curated document corpus, extracted facts, stylized facts, a knowledge graph, and an AI chat assistant. Its goal is to help users find scientific claims and trace them back to supporting sources.',
      'The app is not a replacement for reading papers or making expert judgement. Treat it as a guide for discovery, comparison, and evidence tracing.',
    ],
  },
  {
    id: 'roles',
    title: 'Role-based access',
    badge: 'Access',
    audiences: ['all'],
    paragraphs: [
      'Documentation and app features are shown according to your role. This keeps everyday research tasks visible for all users while exposing ingestion, review, and administration guidance only to users who need it.',
    ],
    items: [
      {
        title: 'Knowledge explorer',
        text: 'The standard user role. Explorers can use Chat, browse the document corpus, inspect facts, submit new fact suggestions, manage their own LLM keys, and use future modeling views when available.',
      },
      {
        title: 'Knowledge curator',
        text: 'A review and maintenance role. Curators can upload or ingest documents, review document and fact suggestions, maintain graph links, and use the Knowledge Builder workspace.',
      },
      {
        title: 'Administrator',
        text: 'A governance role. Administrators can do curator work and also manage user roles and high-impact maintenance actions such as database reset tools when exposed by the deployment.',
      },
    ],
    note: {
      title: 'Why some pages may be missing',
      text: 'If you do not see Knowledge in the sidebar, your account is not a curator or administrator account. Ask an administrator if your work requires curator access.',
    },
  },
  {
    id: 'ui-overview',
    title: 'UI explanation',
    badge: 'Navigation',
    audiences: ['all'],
    paragraphs: [
      'Authenticated users see a left sidebar. On desktop the sidebar expands when hovered; on mobile it opens from the top menu. The main pages are Home, Chat, Documents, Facts, Scenarios, Models, LLM Keys, Documentation, and for curators or administrators, Knowledge.',
    ],
    items: [
      {
        title: 'Home',
        text: 'A starting dashboard with links to the main research areas.',
      },
      {
        title: 'Chat',
        text: 'The conversational assistant for asking scientific questions and checking cited answers.',
      },
      {
        title: 'Documents',
        text: 'A searchable corpus view for source documents and their processing status.',
      },
      {
        title: 'Facts',
        text: 'A fact library with stylized facts, extracted knowledge-base facts, and submitted fact suggestions.',
      },
      {
        title: 'LLM Keys',
        text: 'A personal settings page for adding, testing, and deleting your own model provider credentials.',
      },
      {
        title: 'Knowledge',
        text: 'A curator workspace for graph exploration, ingestion, database inspection, graph-building tasks, and review queues.',
      },
    ],
  },
  {
    id: 'knowledge-base',
    title: 'Knowledge base description',
    badge: 'Concepts',
    audiences: ['all'],
    paragraphs: [
      'The knowledge base is the scientific memory behind the app. It contains source documents, document chunks, extracted facts, stylized facts, taxa, and graph links that connect these pieces.',
      'A document is a source such as a research paper. A chunk is a smaller passage from a document. A fact is a specific claim extracted from a source or submitted by a user. A stylized fact is a broader curated pattern or principle that can be supported or challenged by many facts. A taxon is an organism group, such as a species or genus.',
      'When the chat assistant answers, it searches this knowledge base and tries to connect its answer to supporting material. Use citations, document metadata, and provenance to judge whether the support is strong enough for your purpose.',
    ],
  },
  {
    id: 'chatbot',
    title: 'Chatbot explanation',
    badge: 'Chat',
    audiences: ['all'],
    paragraphs: [
      'The Chat page is designed for question-driven exploration. It keeps a conversation list on the left, the current conversation in the middle, and agent activity or provenance on the right.',
      'The assistant can use retrieval and graph tools to search the knowledge base before it writes an answer. It may show active steps while it is working. These steps are helpful context, but the final answer and its sources are what you should evaluate.',
    ],
    items: [
      {
        title: 'Conversations',
        text: 'Create a new conversation for each topic. You can search old sessions, rename a session by double-clicking its title, delete sessions you no longer need, and export a conversation.',
      },
      {
        title: 'Model source',
        text: 'Use the model selector to choose the shared default model or one of your stored LLM keys. A personal key can give you access to a provider or model that is better suited to your question.',
      },
      {
        title: 'Custom instructions',
        text: 'Use instructions for session-level preferences, such as asking for concise answers, a table, or a focus on marine organisms. Keep instructions short and specific.',
      },
      {
        title: 'Prompt library and follow-ups',
        text: 'Starter prompts help you begin common searches. Suggested follow-up questions appear when the app can offer a useful next step.',
      },
      {
        title: 'Citations and provenance',
        text: 'Citation badges connect an answer to source material. Open provenance to inspect how a cited item relates to facts, chunks, and documents.',
      },
    ],
    note: {
      title: 'Scientific caution',
      text: 'If the answer seems surprising, vague, or weakly cited, narrow the question and inspect the source documents before using the claim in scientific work.',
    },
  },
  {
    id: 'documents',
    title: 'Documents view explanation',
    badge: 'Corpus',
    audiences: ['all'],
    paragraphs: [
      'The Documents page shows the corpus used by the knowledge base. It is the best place to check whether a paper or source has been included and how far it has moved through processing.',
      'Use search and filters to narrow the list. Document rows can include title, authors, publication details, source type, processing status, chunk counts, fact counts, and flags.',
    ],
    items: [
      {
        title: 'Processing status',
        text: 'Status values indicate whether a document is pending, processing, completed, or failed. Completed documents have already contributed searchable chunks or facts.',
      },
      {
        title: 'Flags',
        text: 'Any authenticated user can flag a document that appears irrelevant or problematic. Curators review these flags and decide whether to keep, unflag, or remove eligible records.',
      },
      {
        title: 'Uploads',
        text: 'Curators see document upload controls. Explorers can browse the corpus and should contact a curator when a new source needs to be added.',
      },
    ],
  },
  {
    id: 'facts',
    title: 'Facts view explanation',
    badge: 'Evidence',
    audiences: ['all'],
    paragraphs: [
      'The Facts page organizes scientific claims into three working views: Stylized Facts, KB Facts, and Submissions.',
    ],
    items: [
      {
        title: 'Stylized Facts',
        text: 'Broad, curated statements about DEB biology. They are useful for understanding general patterns, assumptions, or repeated findings across sources.',
      },
      {
        title: 'KB Facts',
        text: 'Specific extracted claims from the knowledge base. These are often closer to the wording or evidence found in individual source documents.',
      },
      {
        title: 'Submissions',
        text: 'User-submitted fact suggestions. You can create a new fact suggestion with a clear statement, optional tags, and a confidence estimate. Curators decide whether suggestions are published or rejected.',
      },
      {
        title: 'Searching and filtering',
        text: 'Use search fields, category filters, domain filters, status filters, and pagination to narrow large result sets before reading individual rows.',
      },
    ],
  },
  {
    id: 'llm-keys',
    title: 'LLM API key management',
    badge: 'Settings',
    audiences: ['all'],
    paragraphs: [
      'The LLM Keys page lets you bring your own model credentials for supported providers. Stored keys are used only to power chat reasoning over the knowledge base for your account.',
      'The app validates a key before saving it. The saved credential is encrypted at rest, and the interface shows only the provider, optional label, model, last-used time, and the last four characters. The full key is not shown again.',
    ],
    items: [
      {
        title: 'Add a key',
        text: 'Choose a provider, optionally add a label such as work key or personal key, paste the key, and save it. If validation fails, check that the key is active and allowed to call models for that provider.',
      },
      {
        title: 'Connect with GitHub',
        text: 'When enabled, GitHub Models can be connected through GitHub authorization instead of a pasted key. Follow the on-screen code and authorization link.',
      },
      {
        title: 'Use a key in Chat',
        text: 'Open Chat, select the model source, then choose a stored key and model. The selected source applies to that chat session.',
      },
      {
        title: 'Test or delete keys',
        text: 'Use Test to confirm that a stored credential still works. Delete keys that are old, revoked, shared by mistake, or no longer needed.',
      },
    ],
    note: {
      title: 'Key safety',
      text: 'Do not paste API keys into chat messages, document uploads, or fact submissions. Add them only on the LLM Keys page.',
    },
  },
  {
    id: 'scenarios-models',
    title: 'Scenarios and models',
    badge: 'In progress',
    audiences: ['all'],
    paragraphs: [
      'Scenarios and Models are visible as app areas for future DEB modeling workflows. In the current interface they explain the planned direction and link back to Chat or Knowledge Graph exploration where useful.',
      'Use Chat and the knowledge base today to gather assumptions, evidence, and candidate model context. Use the future modeling views when your deployment enables them.',
    ],
  },
  {
    id: 'curator-workflow',
    title: 'Curator workflow',
    badge: 'Curator',
    audiences: ['knowledge_curator'],
    paragraphs: [
      'Curators maintain the quality and freshness of the knowledge base. The curator workflow starts with source selection, continues through ingestion, and ends with review of suggestions and graph links.',
    ],
    items: [
      {
        title: 'Upload and ingest documents',
        text: 'Use Knowledge, then Ingestion, to upload PDFs or scan approved source folders. Start ingestion batches and monitor progress before relying on newly added material.',
      },
      {
        title: 'Review suggestions',
        text: 'Use the Suggestions tab to approve or reject document suggestions, fact suggestions, and stylized fact suggestions. Publishing makes accepted material visible to the wider knowledge base.',
      },
      {
        title: 'Inspect the graph',
        text: 'Use the Graph tab to explore graph schemas, select nodes, inspect connections, and reload graph data after important ingestion or linking work.',
      },
      {
        title: 'Maintain document-taxon links',
        text: 'Use KG Builder to suggest, confirm, or reject document-taxon relations. Rebuild the knowledge graph schema after link changes when needed.',
      },
    ],
    note: {
      title: 'Curation standard',
      text: 'Approve material only when the statement is clear, scientifically meaningful, and traceable to a suitable source.',
    },
  },
  {
    id: 'knowledge-builder',
    title: 'Knowledge Builder explanation',
    badge: 'Curator',
    audiences: ['knowledge_curator'],
    paragraphs: [
      'Knowledge Builder is the advanced workspace for curators and administrators. It is separate from the regular sidebar because it is a focused maintenance environment.',
    ],
    items: [
      {
        title: 'Graph',
        text: 'Visualize available graph schemas, inspect nodes, open the node table, and refresh graph data.',
      },
      {
        title: 'Ingestion',
        text: 'Stage local PDFs or select source folders, start ingestion, and manage ingestion batches and jobs.',
      },
      {
        title: 'Database',
        text: 'Inspect database collections and sample records when checking whether ingestion and graph-building steps produced the expected records.',
      },
      {
        title: 'KG Builder',
        text: 'Build and review document-taxon links, then rebuild graph structure when links are ready.',
      },
      {
        title: 'Suggestions',
        text: 'Review user-submitted document, fact, and stylized fact suggestions.',
      },
    ],
  },
  {
    id: 'administrator-notes',
    title: 'Administrator notes',
    badge: 'Admin',
    audiences: ['administrator'],
    paragraphs: [
      'Administrators are responsible for user access, role assignment, and high-impact maintenance controls. Keep administrator access limited to people who understand the consequences of changing roles or resetting data.',
    ],
    items: [
      {
        title: 'User roles',
        text: 'Assign knowledge_explorator for normal research use, knowledge_curator for ingestion and review work, and administrator only for trusted project maintainers.',
      },
      {
        title: 'Account management',
        text: 'Administrators can create or update native accounts and assign or remove roles through the deployment administration process. Some deployments expose this through API or operational tooling rather than an in-app user screen.',
      },
      {
        title: 'Reset controls',
        text: 'The Knowledge Builder header can expose a reset action for administrators. Use it only after confirming backups and understanding which records will be removed or preserved.',
      },
      {
        title: 'Provider and key policy',
        text: 'Users manage their own LLM keys. Administrators should define which providers are acceptable for project data and should remove user access when accounts leave the project.',
      },
    ],
  },
  {
    id: 'good-use',
    title: 'Good scientific use',
    badge: 'Practice',
    audiences: ['all'],
    paragraphs: [
      'Use AdvanDEB as a structured assistant, not as an authority. The strongest workflow is to ask a narrow question, read the cited answer, inspect the source trail, compare related facts, and then decide whether the evidence supports your scientific use case.',
      'When citing results outside the app, cite the original papers or sources, not the chatbot. The chatbot can help you find and compare evidence, but the source documents remain the scientific record.',
    ],
  },
]
</script>

<style scoped>
.documentation-view {
  min-height: 100%;
  padding: 1.5rem 2rem 2rem;
  color: #111827;
  background: #f8fafc;
}

.doc-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1.5rem;
  margin-bottom: 1.25rem;
}

.header-copy {
  max-width: 760px;
}

.eyebrow {
  color: #2563eb;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin-bottom: 0.25rem;
}

.doc-header h1 {
  font-size: 1.6rem;
  line-height: 1.2;
  margin-bottom: 0.35rem;
}

.subtitle {
  color: #64748b;
  font-size: 0.92rem;
  line-height: 1.55;
}

.role-panel {
  min-width: 220px;
  padding: 0.8rem;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
}

.role-label {
  display: block;
  color: #64748b;
  font-size: 0.75rem;
  margin-bottom: 0.45rem;
}

.role-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.role-chip,
.section-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 9999px;
  font-size: 0.72rem;
  font-weight: 600;
  white-space: nowrap;
}

.role-chip {
  padding: 0.18rem 0.5rem;
  background: #ecfdf5;
  color: #047857;
}

.doc-shell {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 1.25rem;
  align-items: start;
}

.toc {
  position: sticky;
  top: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.8rem;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
  max-height: calc(100vh - 3rem);
  overflow-y: auto;
}

.toc-title {
  color: #334155;
  font-size: 0.76rem;
  font-weight: 700;
  margin-bottom: 0.25rem;
}

.toc-link {
  color: #475569;
  text-decoration: none;
  font-size: 0.82rem;
  line-height: 1.3;
  padding: 0.35rem 0.45rem;
  border-radius: 5px;
}

.toc-link:hover {
  color: #1d4ed8;
  background: #eff6ff;
}

.doc-content {
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
}

.doc-section {
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid #e5e7eb;
  scroll-margin-top: 1rem;
}

.doc-section:last-child {
  border-bottom: none;
}

.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.section-kicker {
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 0.2rem;
}

.section-heading h2 {
  font-size: 1.15rem;
  line-height: 1.3;
}

.section-badge {
  flex-shrink: 0;
  padding: 0.2rem 0.55rem;
  background: #eef2ff;
  color: #4338ca;
}

.doc-paragraph {
  color: #374151;
  font-size: 0.92rem;
  line-height: 1.7;
  max-width: 900px;
  margin-bottom: 0.7rem;
}

.item-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 0.75rem;
  margin-top: 0.8rem;
}

.doc-item {
  padding: 0.75rem 0.85rem;
  border-left: 3px solid #93c5fd;
  background: #f8fafc;
  border-radius: 0 6px 6px 0;
}

.doc-item h3 {
  font-size: 0.9rem;
  line-height: 1.35;
  margin-bottom: 0.25rem;
}

.doc-item p {
  color: #4b5563;
  font-size: 0.84rem;
  line-height: 1.6;
}

.doc-note {
  max-width: 900px;
  margin-top: 0.9rem;
  padding: 0.75rem 0.85rem;
  border: 1px solid #fde68a;
  border-radius: 8px;
  background: #fffbeb;
}

.doc-note strong {
  display: block;
  color: #92400e;
  font-size: 0.86rem;
  margin-bottom: 0.2rem;
}

.doc-note p {
  color: #78350f;
  font-size: 0.84rem;
  line-height: 1.55;
}

@media (max-width: 900px) {
  .documentation-view {
    padding: 1rem;
  }

  .doc-header {
    flex-direction: column;
  }

  .role-panel {
    width: 100%;
  }

  .doc-shell {
    grid-template-columns: 1fr;
  }

  .toc {
    position: static;
    max-height: none;
  }
}

@media (max-width: 640px) {
  .doc-section {
    padding: 1rem;
  }

  .section-heading {
    flex-direction: column;
    gap: 0.5rem;
  }

  .item-list {
    grid-template-columns: 1fr;
  }
}
</style>
