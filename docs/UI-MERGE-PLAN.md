# UI Merge Plan: Knowledge Builder into Main App

## Goal

Merge the Knowledge Builder dev-server UI (`knowledge-builder/dev-server/frontend`) into
the main app UI (`app/frontend`) as a **second, distinctive mode** — without merging any
backend services.

## Two Modes

| Mode | Layout | Route | Access |
|---|---|---|---|
| **Assistant Mode** | Sidebar nav, Tailwind, Cytoscape.js | `/`, `/documents`, `/facts`, etc. | All authenticated users |
| **Knowledge Builder Mode** | Top toolbar, full-screen Sigma.js canvas, bottom-sheet drawers | `/kb` | Administrator, Knowledge Curator |

Authentication is **shared** — one login (`LoginView.vue`, `authStore`) covers both modes.
The KB mode is gated behind the existing role guard on the frontend router; the KB
dev-server backend remains unauthenticated internally.

## What Does NOT Change

- `app/backend` (FastAPI) — no changes
- `knowledge-builder/dev-server` backend (FastAPI at port 8500) — stays running separately
- `advandeb_kb` Python library — no changes
- Rust MCP Gateway — no changes
- KB dev-server frontend (`knowledge-builder/dev-server/frontend`) — kept as-is, still usable standalone

## Implementation Phases

### Phase 1 — Dual-mode routing

**File:** `app/frontend/src/router/index.ts`

- Add `/kb` route pointing to `KnowledgeBuilderView` with `meta: { requiresAuth: true, requiresKB: true }`
- Extend `router.beforeEach` guard:
  - Existing: redirect to `/login` if `requiresAuth` and not authenticated
  - New: redirect to `/` if `requiresKB` and user lacks `Administrator` or `Knowledge Curator` role
- KB view bypasses `AppLayout` — handled in `App.vue` (same pattern as `/login`)

### Phase 2 — KB API client

**File:** `app/frontend/src/utils/kbApi.ts` (new)

- Dedicated Axios instance with `baseURL = import.meta.env.VITE_KB_API_URL`
- No JWT header — KB dev-server is unauthenticated internally
- Exports `vizAPI`, `dbAPI`, `fsAPI`, `kgAPI`, `agentsAPI`, `ingestionAPI`
  (TypeScript conversion of `knowledge-builder/dev-server/frontend/src/services/api.js`)

**File:** `app/frontend/.env.example` — add `VITE_KB_API_URL=http://localhost:8500/api`

### Phase 3 — Install KB npm dependencies

**File:** `app/frontend/package.json` — add:

```
sigma ^3.0.0
graphology ^0.25.4
graphology-layout-forceatlas2 ^0.10.1
graphology-layout ^0.6.1
element-plus ^2.4.4
```

### Phase 4 — Migrate KB components

Copy into `app/frontend/src/components/kb/`:

| Source (KB dev-server) | Destination |
|---|---|
| `components/GraphCanvas.vue` | `components/kb/GraphCanvas.vue` |
| `components/NodeInspector.vue` | `components/kb/NodeInspector.vue` |
| `components/SearchOverlay.vue` | `components/kb/SearchOverlay.vue` |
| `drawers/IngestionDrawer.vue` | `components/kb/IngestionDrawer.vue` |
| `drawers/DatabaseDrawer.vue` | `components/kb/DatabaseDrawer.vue` |
| `drawers/FilesystemDrawer.vue` | `components/kb/FilesystemDrawer.vue` |
| `drawers/KGBuilderDrawer.vue` | `components/kb/KGBuilderDrawer.vue` |

Adjustments during migration:
- Replace `import from '../services/api.js'` → `import from '@/utils/kbApi'`
- Scoped styles stay as-is (no Tailwind conflict — KB mode does not use `AppLayout`)
- Plain JavaScript inside `.vue` files is acceptable (no forced TS conversion)

### Phase 5 — Create `KnowledgeBuilderView.vue`

**File:** `app/frontend/src/views/KnowledgeBuilderView.vue` (new)

Essentially the KB `App.vue` transplanted into the main app's views:
- Toolbar + full-screen Sigma.js canvas + bottom-sheet drawers
- Imports all components from `@/components/kb/`
- Self-contained styles (no Tailwind dependency)
- Includes a "← Back to Assistant" button linking to `/`

### Phase 6 — Update `App.vue` for bare KB rendering

**File:** `app/frontend/src/App.vue`

Extend the existing `isLoginRoute` bare-render condition to also cover `/kb`:

```ts
const isBareRoute = computed(() =>
  route.path === '/login' || route.path.startsWith('/kb')
)
```

Replace `v-if` / `v-else` to use `isBareRoute`.

### Phase 7 — Add KB link in `AppLayout` sidebar

**File:** `app/frontend/src/components/layout/AppLayout.vue`

- Add "Knowledge Builder" nav entry at the bottom of the sidebar
- Visible only when `authStore.hasRole('Administrator') || authStore.hasRole('Knowledge Curator')`
- Routes to `/kb`

### Phase 8 — Vite bundle splitting

**File:** `app/frontend/vite.config.ts`

Add `sigma-vendor` manual chunk for `sigma`, `graphology`, `graphology-layout`,
`graphology-layout-forceatlas2` so they are not loaded for users who never visit `/kb`.

## Dependency Map

```
LoginView.vue + authStore    ← shared by both modes (single JWT session)
        │
        ├── Assistant Mode (existing routes)
        │     └── AppLayout → sidebar nav → existing views
        │
        └── KB Mode  /kb
              └── KnowledgeBuilderView → components/kb/* → kbApi.ts → KB dev-server :8500
```
