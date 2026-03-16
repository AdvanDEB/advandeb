# UI Merge Progress — Knowledge Builder into Main App

> **Purpose**: Handoff document for continuing work in a new session.
> **Plan reference**: `docs/UI-MERGE-PLAN.md`
> **All work is confined to `app/frontend/src/`** — no backend, no KB dev-server, no library changes.

---

## Phase Status Summary

| Phase | Description | Status |
|---|---|---|
| 1 | Dual-mode routing + `App.vue` bare-render | ✅ Complete |
| 2 | KB API client (`kbApi.ts`) + `.env.example` | ✅ Complete |
| 3 | Install KB npm deps | ✅ Complete |
| 4 | Migrate KB components (7 files) | ✅ Complete |
| 5 | Full `KnowledgeBuilderView.vue` (replace stub) | ❌ Not started |
| 6 | `App.vue` bare-render condition | ✅ Complete (done in Phase 1) |
| 7 | KB nav link in `AppLayout.vue` sidebar | ❌ Not started |
| 8 | `sigma-vendor` manual chunk in `vite.config.ts` | ❌ Not started |
| — | Final `npm run build` verification | ❌ Not done |

---

## What Is Done (in detail)

### Phase 1 — Routing (`src/router/index.ts`, `src/App.vue`)

- `/kb` route added → lazy-loads `KnowledgeBuilderView.vue`
- `meta: { requiresAuth: true, requiresKB: true }`
- `router.beforeEach` extended: redirects to `home` if `requiresKB` and user lacks `Administrator` or `Knowledge Curator` role
- `KB_ROLES = ['Administrator', 'Knowledge Curator']` constant defined at top of router file
- `App.vue`: `isBareRoute` computed covers `/login` and `/kb` (no `AppLayout` wrapper for these routes)
- **Build was verified clean after Phase 1**

### Phase 2 — KB API client

- `src/utils/kbApi.ts` created — full TypeScript Axios client, baseURL from `VITE_KB_API_URL` env var (fallback `http://localhost:8500/api`), no JWT
- Exports: `vizAPI`, `dbAPI`, `fsAPI`, `kgAPI`, `agentsAPI`, `ingestionAPI`
- `.env.example` updated with `VITE_KB_API_URL=http://localhost:8500/api`
- `src/vite-env.d.ts` updated with `VITE_KB_API_URL: string` declaration

### Phase 3 — npm deps

These packages were added to `app/frontend/package.json` and installed:
- `sigma ^3.0.2`
- `graphology ^0.26.0`
- `graphology-layout-forceatlas2`
- `graphology-layout`
- `element-plus ^2.13.5`

### Phase 4 — Component migration (all 7 files)

All components are in `app/frontend/src/components/kb/`. The **only** change from the KB dev-server source was replacing `import { ... } from '../services/api.js'` with `import { ... } from '@/utils/kbApi'`. Logic and styles are verbatim.

| File | Source | Notes |
|---|---|---|
| `GraphCanvas.vue` | `knowledge-builder/dev-server/frontend/src/components/GraphCanvas.vue` | `_edge` param renamed; unused `currentSearchQuery` kept |
| `NodeInspector.vue` | `knowledge-builder/dev-server/frontend/src/components/NodeInspector.vue` | Bug fixed: `props` shadowing → renamed computed ref to `nodeProps` |
| `SearchOverlay.vue` | `knowledge-builder/dev-server/frontend/src/components/SearchOverlay.vue` | Verbatim except import path |
| `IngestionDrawer.vue` | `knowledge-builder/dev-server/frontend/src/drawers/IngestionDrawer.vue` | Verbatim except import path |
| `DatabaseDrawer.vue` | `knowledge-builder/dev-server/frontend/src/drawers/DatabaseDrawer.vue` | Verbatim except import path |
| `FilesystemDrawer.vue` | `knowledge-builder/dev-server/frontend/src/drawers/FilesystemDrawer.vue` | Verbatim except import path |
| `KGBuilderDrawer.vue` | `knowledge-builder/dev-server/frontend/src/drawers/KGBuilderDrawer.vue` | ⚠️ File written to disk in this session but writing was interrupted — **verify it exists and is complete** before proceeding |

---

## What Needs to Be Done

### ⚠️ Verify KGBuilderDrawer.vue first

Before proceeding, check that `app/frontend/src/components/kb/KGBuilderDrawer.vue` exists and
contains the full file (447 lines from source). If it is missing or truncated, recreate it from
`knowledge-builder/dev-server/frontend/src/drawers/KGBuilderDrawer.vue` with the single
import-path change:

```
# In <script> block:
import { kgAPI, agentsAPI } from '@/utils/kbApi'   # was: from '../services/api.js'
```

---

### Phase 5 — Full `KnowledgeBuilderView.vue`

**File to replace**: `app/frontend/src/views/KnowledgeBuilderView.vue`
**Currently**: stub placeholder (23 lines)
**Source**: `knowledge-builder/dev-server/frontend/src/App.vue` (321 lines)

The view should be the KB `App.vue` transplanted verbatim, with these adjustments:

1. **Import paths** — change all component imports from KB-local paths to `@/components/kb/`:
   ```js
   import GraphCanvas      from '@/components/kb/GraphCanvas.vue'
   import NodeInspector    from '@/components/kb/NodeInspector.vue'
   import SearchOverlay    from '@/components/kb/SearchOverlay.vue'
   import IngestionDrawer  from '@/components/kb/IngestionDrawer.vue'
   import DatabaseDrawer   from '@/components/kb/DatabaseDrawer.vue'
   import FilesystemDrawer from '@/components/kb/FilesystemDrawer.vue'
   import KGBuilderDrawer  from '@/components/kb/KGBuilderDrawer.vue'
   import { vizAPI }       from '@/utils/kbApi'
   ```

2. **Back button** — add a "← Back to Assistant" `<router-link to="/">` button in the toolbar
   (left side, before the brand), styled to match the dark toolbar.

3. **Component name** — change `name: 'App'` to `name: 'KnowledgeBuilderView'`

4. **Global styles** — the source `App.vue` has a `<style>` (non-scoped) block that resets
   `*, html, body, #app`. **Do NOT include these global resets** — they will break the main app.
   Only keep the `<style scoped>` block.

5. **Keep plain JS** — the `<script>` block stays as Options API plain JavaScript (not TypeScript).
   This is intentional.

---

### Phase 7 — KB nav link in `AppLayout.vue`

**File**: `app/frontend/src/components/layout/AppLayout.vue`

Add a conditional KB entry to the `navLinks` array. The array is currently a plain static
`const` — convert it to a `computed` that adds the KB entry only for permitted roles:

```ts
// Replace the static navLinks const with:
const baseLinks = [
  { path: '/',           icon: '⌂',  label: 'Home' },
  { path: '/chat',       icon: '💬', label: 'Chat' },
  { path: '/documents',  icon: '📄', label: 'Documents' },
  { path: '/graph',      icon: '🕸',  label: 'Graph' },
  { path: '/facts',      icon: '🔬', label: 'Facts' },
  { path: '/scenarios',  icon: '⚗',  label: 'Scenarios' },
  { path: '/models',     icon: '📐', label: 'Models' },
]

const navLinks = computed(() => {
  const links = [...baseLinks]
  if (authStore.hasRole('Administrator') || authStore.hasRole('Knowledge Curator')) {
    links.push({ path: '/kb', icon: '🧠', label: 'Knowledge Builder' })
  }
  return links
})
```

`authStore` is already imported in that file (`useAuthStore`).

---

### Phase 8 — Sigma vendor chunk in `vite.config.ts`

**File**: `app/frontend/vite.config.ts`

Add `sigma-vendor` to the existing `manualChunks` object in `build.rollupOptions.output`:

```ts
manualChunks: {
  'vue-vendor':      ['vue', 'vue-router', 'pinia'],
  'graph-vendor':    ['cytoscape'],
  'ui-vendor':       ['@vueuse/core'],
  'markdown-vendor': ['marked', 'highlight.js'],
  'sigma-vendor':    ['sigma', 'graphology', 'graphology-layout', 'graphology-layout-forceatlas2'],
},
```

---

### Final — Build verification

```bash
cd app/frontend
npm run build
```

Expected: clean build, no TypeScript errors, no missing module errors.
The `KnowledgeBuilderView` and all `components/kb/` files use plain JS Options API —
the TypeScript compiler allows plain JS inside `.vue` files in this project.

---

## Key File Locations

### Modified / created (all in `app/frontend/`)

| File | State |
|---|---|
| `src/router/index.ts` | ✅ Done |
| `src/App.vue` | ✅ Done |
| `src/vite-env.d.ts` | ✅ Done (added `VITE_KB_API_URL`) |
| `src/utils/kbApi.ts` | ✅ Done |
| `.env.example` | ✅ Done |
| `package.json` | ✅ Done (sigma/graphology/element-plus added) |
| `src/components/kb/GraphCanvas.vue` | ✅ Done |
| `src/components/kb/NodeInspector.vue` | ✅ Done |
| `src/components/kb/SearchOverlay.vue` | ✅ Done |
| `src/components/kb/IngestionDrawer.vue` | ✅ Done |
| `src/components/kb/DatabaseDrawer.vue` | ✅ Done |
| `src/components/kb/FilesystemDrawer.vue` | ✅ Done |
| `src/components/kb/KGBuilderDrawer.vue` | ⚠️ Verify completeness |
| `src/views/KnowledgeBuilderView.vue` | ❌ Still a stub — needs Phase 5 |
| `src/components/layout/AppLayout.vue` | ❌ Needs Phase 7 (KB nav link) |
| `vite.config.ts` | ❌ Needs Phase 8 (sigma-vendor chunk) |

### Read-only source files (KB dev-server — do not modify)

| File | Used for |
|---|---|
| `knowledge-builder/dev-server/frontend/src/App.vue` | Source for Phase 5 `KnowledgeBuilderView.vue` |
| `knowledge-builder/dev-server/frontend/src/drawers/KGBuilderDrawer.vue` | Verify/recreate `components/kb/KGBuilderDrawer.vue` if needed |

---

## Important Notes

- **Role names** (case-sensitive, from `app/backend/app/core/dependencies.py`):
  `'Administrator'` and `'Knowledge Curator'`
- **No backend changes** in any phase — `app/backend`, KB dev-server backend, and Rust MCP Gateway are untouched
- **Plain JS components are fine** — KB components stay as Options API `.vue` files; TypeScript compiler does not reject them
- **No global CSS resets** in `KnowledgeBuilderView.vue` — the source `App.vue` has non-scoped style resets that must be omitted
- **`declare module 'vue-router'`** augmentation was removed from `vite-env.d.ts` during Phase 1 — do not re-add it; it conflicts with vue-router's own type resolution given `"types": []` in the base tsconfig
