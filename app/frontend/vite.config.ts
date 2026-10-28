import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// The dev server forwards /api and /ws to the backend, which on this host is
// production. The e2e run points it at a closed port instead (playwright.config.ts).
const apiTarget = process.env.API_PROXY_TARGET || 'http://localhost:8400'

// Vendor chunks, assigned per npm package. Rollup also moves every static
// dependency of a manual-chunk module into that chunk, and when two chunks
// share a dependency the first to claim it wins. So anything shared has to be
// claimed here explicitly, or it lands in whichever vendor chunk Rollup meets
// first, and every importer then loads that whole chunk:
//  - bundler helpers. luma.gl (inside @cosmos.gl/graph) has a dynamic import,
//    so Vite's preload helper became part of cosmos-vendor; the entry needs
//    that helper for every lazy route, so the landing and login pages loaded
//    cosmos-vendor and, through it, tdeb-vendor and markdown-vendor (~1 MB).
//    They go to vue-vendor, which every page loads anyway.
//  - the d3 modules @cosmos.gl/graph shares with the tDEB network view. They
//    get their own chunk so the graph pages don't also load KaTeX and JSZip.
// src/tests/buildChunks.test.ts builds the app and checks the result.
const VENDOR_CHUNKS: Array<[chunk: string, packages: RegExp]> = [
  ['vue-vendor', /^(vue|@vue\/.+|vue-router|pinia)$/],
  // Only the highlight.js grammars utils/markdown.ts imports reach this
  // function, not all ~190.
  ['markdown-vendor', /^(marked|dompurify|highlight\.js)$/],
  ['cosmos-vendor', /^@cosmos\.gl\/graph$/],
  ['d3-vendor', /^(d3|d3-.+|internmap|delaunator|robust-predicates)$/],
  // Split out so the (large) Plotly bundle caches separately from the view
  // code and is re-fetched only when Plotly itself changes.
  ['plotly-vendor', /^plotly\.js$/],
  ['tdeb-vendor', /^(katex|jszip)$/],
]

export function vendorChunk(id: string): string | undefined {
  // Bundler-generated helpers: Vite's preload helper, the CommonJS interop
  // helpers, the Vue SFC export helper.
  if (id.startsWith('\0') && !id.includes('/node_modules/')) return 'vue-vendor'
  // Stylesheets stay with the module that imports them (main.ts imports
  // highlight.js's theme; it must not pull markdown-vendor into the entry).
  if (/\.css($|\?)/.test(id)) return undefined
  // The outermost package owns its nested node_modules: plotly.js's own
  // older d3 copies belong to plotly-vendor, not d3-vendor.
  const at = id.indexOf('/node_modules/')
  if (at < 0) return undefined
  const [scopeOrName, name] = id.slice(at + '/node_modules/'.length).split('/')
  const pkg = scopeOrName.startsWith('@') ? `${scopeOrName}/${name}` : scopeOrName
  return VENDOR_CHUNKS.find(([, packages]) => packages.test(pkg))?.[0]
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    }
  },
  server: {
    host: '0.0.0.0',  // Listen on all network interfaces
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true
      },
      '/ws': {
        target: apiTarget,
        changeOrigin: true,
        ws: true
      }
    }
  },
  build: {
    target: 'es2020',
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true
      }
    },
    rollupOptions: {
      output: {
        manualChunks: vendorChunk,
      }
    },
    chunkSizeWarningLimit: 1500,
    sourcemap: false
  }
})
