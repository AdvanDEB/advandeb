# Frontend Setup and Development Guide

## Quick Start

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Start Development Server

```bash
npm run dev
```

The frontend will be available at **http://localhost:5173**

## Project Structure

```
frontend/
├── src/
│   ├── main.ts                 # Application entry point
│   ├── App.vue                 # Root component
│   ├── router/
│   │   └── index.ts            # Vue Router configuration
│   ├── stores/
│   │   └── auth.ts             # Authentication state (Pinia)
│   ├── utils/
│   │   └── api.ts              # Axios HTTP client
│   ├── views/                  # Page components
│   │   ├── HomeView.vue        # Dashboard
│   │   ├── LoginView.vue       # Google OAuth login
│   │   ├── DocumentsView.vue   # Document management
│   │   ├── FactsView.vue       # Facts browser
│   │   ├── GraphView.vue       # Knowledge graph
│   │   ├── ChatView.vue        # AI chat interface
│   │   ├── ScenariosView.vue   # Modeling scenarios
│   │   └── ModelsView.vue      # Model builder
│   ├── components/             # Reusable components (to be added)
│   └── assets/                 # Static assets
├── public/                     # Public static files
├── index.html                  # HTML entry point
├── vite.config.ts             # Vite configuration
├── tsconfig.json              # TypeScript configuration
├── package.json               # Dependencies
└── .env.local                 # Environment variables (already configured)
```

## Key Technologies

- **Vue 3** - Progressive JavaScript framework with Composition API
- **TypeScript** - Type-safe JavaScript
- **Vite** - Fast build tool and dev server
- **Vue Router** - Client-side routing with auth guards
- **Pinia** - State management (Vuex successor)
- **Axios** - HTTP client with interceptors for JWT tokens

## Authentication Flow

### How It Works

1. User clicks "Sign in with Google" on `/login`
2. Redirects to Google OAuth consent screen
3. Google redirects back to `/login?code=...`
4. Frontend sends code to backend `/api/auth/google`
5. Backend validates with Google, creates/updates user
6. Backend returns JWT tokens and user data
7. Frontend stores tokens in localStorage and redirects to home

### Implementation

**Login Component** (`src/views/LoginView.vue`):
- Generates Google OAuth URL
- Handles OAuth callback with authorization code
- Calls auth store to complete login

**Auth Store** (`src/stores/auth.ts`):
- Manages authentication state
- Stores user info and tokens
- Provides `isAuthenticated`, `hasRole()`, `hasCapability()` helpers

**API Client** (`src/utils/api.ts`):
- Automatically adds JWT token to requests
- Handles 401 errors (redirects to login)

**Router Guards** (`src/router/index.ts`):
- Protects routes with `meta: { requiresAuth: true }`
- Redirects unauthenticated users to login

## Current Views

### ✅ Completed

1. **HomeView** - Dashboard with feature cards
2. **LoginView** - Google OAuth integration

### 🚧 To Be Implemented (Placeholders)

3. **DocumentsView** - Upload and browse documents
4. **FactsView** - Browse and create facts
5. **GraphView** - Visualize knowledge graph
6. **ChatView** - AI chat interface
7. **ScenariosView** - Create modeling scenarios
8. **ModelsView** - Build and manage models

## Development Workflow

### 1. Create New Components

```bash
# Example: Create a DocumentCard component
touch src/components/DocumentCard.vue
```

```vue
<template>
  <div class="document-card">
    <h3>{{ document.title }}</h3>
    <p>{{ document.source_type }}</p>
  </div>
</template>

<script setup lang="ts">
import { defineProps } from 'vue'

interface Document {
  id: string
  title: string
  source_type: string
}

defineProps<{
  document: Document
}>()
</script>

<style scoped>
.document-card {
  padding: 1rem;
  border: 1px solid #ddd;
  border-radius: 8px;
}
</style>
```

### 2. Add API Calls

Create service files in `src/utils/`:

```typescript
// src/utils/documents.ts
import api from './api'

export interface Document {
  id: string
  title: string
  source_type: string
  created_at: string
}

export const documentService = {
  async getAll(): Promise<Document[]> {
    const response = await api.get('/documents')
    return response.data
  },
  
  async upload(file: File): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return response.data
  }
}
```

### 3. Create Pinia Stores

```typescript
// src/stores/documents.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { documentService, type Document } from '@/utils/documents'

export const useDocumentsStore = defineStore('documents', () => {
  const documents = ref<Document[]>([])
  const loading = ref(false)
  
  async function fetchDocuments() {
    loading.value = true
    try {
      documents.value = await documentService.getAll()
    } finally {
      loading.value = false
    }
  }
  
  return { documents, loading, fetchDocuments }
})
```

### 4. Use in Components

```vue
<template>
  <div class="documents">
    <h1>Documents</h1>
    
    <div v-if="loading">Loading...</div>
    
    <div v-else class="document-list">
      <DocumentCard
        v-for="doc in documents"
        :key="doc.id"
        :document="doc"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useDocumentsStore } from '@/stores/documents'
import DocumentCard from '@/components/DocumentCard.vue'

const store = useDocumentsStore()
const { documents, loading } = store

onMounted(() => {
  store.fetchDocuments()
})
</script>
```

## Styling Approach

Currently using **scoped CSS** in components. Consider adding:

### Option 1: Tailwind CSS

```bash
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

### Option 2: Component Library

**Vuetify** (Material Design):
```bash
npm install vuetify @mdi/font
```

**PrimeVue**:
```bash
npm install primevue primeicons
```

**Element Plus**:
```bash
npm install element-plus
```

## Testing

### Add Vitest for Unit Tests

```bash
npm install -D vitest @vue/test-utils happy-dom
```

Update `vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'happy-dom'
  }
})
```

### Add E2E Tests with Cypress

```bash
npm install -D cypress
npx cypress open
```

## Common Development Tasks

### Check for Type Errors

```bash
npm run build  # TypeScript compiler will check types
```

### Add Environment Variables

Edit `frontend/.env.local`:
```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_GOOGLE_CLIENT_ID=your-client-id
VITE_APP_NAME=AdvanDEB Modeling Assistant
```

Access in code:
```typescript
const apiUrl = import.meta.env.VITE_API_BASE_URL
```

### Handle Authentication in Components

```vue
<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { computed } from 'vue'

const authStore = useAuthStore()

// Check if user is authenticated
const isLoggedIn = computed(() => authStore.isAuthenticated)

// Check user role
const isAdmin = computed(() => authStore.hasRole('administrator'))

// Check capability
const canCreateFacts = computed(() => authStore.hasCapability('knowledge_creation'))
</script>

<template>
  <div v-if="isLoggedIn">
    <button v-if="isAdmin">Admin Actions</button>
    <button v-if="canCreateFacts">Create Fact</button>
  </div>
</template>
```

## Next Steps - Implementation Priority

### Phase 1: Documents (Week 1)
1. Implement `DocumentsView.vue` with:
   - Document list/grid
   - Upload button and form
   - Document details modal
   - Delete confirmation
2. Create `DocumentCard.vue` component
3. Add `documents.ts` service
4. Add `documents` Pinia store

### Phase 2: Facts (Week 2)
1. Implement `FactsView.vue` with:
   - Fact list with filters (status, tags)
   - Create fact form
   - Edit/delete actions
2. Create `FactCard.vue` and `FactForm.vue` components
3. Add `facts.ts` service
4. Add `facts` store

### Phase 3: Knowledge Graph (Week 3)
1. Install visualization library:
   ```bash
   npm install vis-network
   # OR
   npm install cytoscape
   ```
2. Implement `GraphView.vue` with interactive visualization
3. Add zoom, pan, search capabilities

### Phase 4: Chat Interface (Week 4)
1. Implement `ChatView.vue` with:
   - Message list
   - Input box
   - Session management
2. WebSocket support for real-time updates (optional)
3. Create `ChatMessage.vue` component

### Phase 5: Scenarios & Models (Week 5-6)
1. Implement scenario builder
2. Implement model configuration UI
3. Add visualization for model parameters

## Tips & Best Practices

### 1. Use Composition API

✅ **Good:**
```vue
<script setup lang="ts">
import { ref, computed } from 'vue'

const count = ref(0)
const doubled = computed(() => count.value * 2)
</script>
```

❌ **Avoid Options API:**
```vue
<script lang="ts">
export default {
  data() {
    return { count: 0 }
  }
}
</script>
```

### 2. Define TypeScript Interfaces

```typescript
// src/types/models.ts
export interface User {
  id: string
  email: string
  full_name?: string
  roles: string[]
}

export interface Document {
  id: string
  title: string
  created_at: string
}
```

### 3. Extract Reusable Logic with Composables

```typescript
// src/composables/useDocuments.ts
import { ref } from 'vue'
import { documentService } from '@/utils/documents'

export function useDocuments() {
  const documents = ref([])
  const loading = ref(false)
  
  async function loadDocuments() {
    loading.value = true
    try {
      documents.value = await documentService.getAll()
    } finally {
      loading.value = false
    }
  }
  
  return { documents, loading, loadDocuments }
}
```

### 4. Handle Errors Gracefully

```typescript
try {
  await api.post('/documents', data)
} catch (error) {
  if (error.response?.status === 403) {
    alert('You do not have permission to do this')
  } else {
    alert('An error occurred')
  }
}
```

### 5. Use Async/Await with Error Handling

```typescript
async function handleUpload(file: File) {
  loading.value = true
  error.value = null
  
  try {
    const doc = await documentService.upload(file)
    documents.value.push(doc)
  } catch (e) {
    error.value = 'Upload failed'
    console.error(e)
  } finally {
    loading.value = false
  }
}
```

## Debugging

### Vue DevTools

Install browser extension: [Vue DevTools](https://devtools.vuejs.org/)

### Check API Calls

Open browser DevTools → Network tab to inspect requests/responses

### Common Issues

**Issue**: "Failed to fetch" errors
- **Fix**: Check backend is running on port 8000
- **Fix**: Verify CORS is configured correctly

**Issue**: Redirect loop to /login
- **Fix**: Check JWT token is stored correctly
- **Fix**: Verify token is not expired

**Issue**: Component not updating
- **Fix**: Ensure reactive variables use `ref()` or `reactive()`
- **Fix**: Check if data is properly computed

## Resources

- [Vue 3 Documentation](https://vuejs.org/)
- [Pinia Documentation](https://pinia.vuejs.org/)
- [Vue Router Documentation](https://router.vuejs.org/)
- [Vite Documentation](https://vitejs.dev/)
- [TypeScript + Vue](https://vuejs.org/guide/typescript/overview.html)

## Getting Help

If you encounter issues:
1. Check browser console for errors
2. Check backend logs
3. Verify `.env.local` is configured
4. Ensure backend is running
5. Check API endpoint URLs match

**Backend API Docs**: http://localhost:8000/docs
