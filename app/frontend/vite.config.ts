import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

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
        target: 'http://localhost:8400',
        changeOrigin: true
      },
      '/ws': {
        target: 'http://localhost:8400',
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
        manualChunks: {
          'vue-vendor':      ['vue', 'vue-router', 'pinia'],
          'markdown-vendor': ['marked', 'highlight.js'],
          'cosmos-vendor':   ['@cosmos.gl/graph'],
          // tDEB simulator libraries. Split out so the (large) Plotly bundle
          // caches separately from the view code and is re-fetched only when
          // Plotly itself changes.
          'plotly-vendor':   ['plotly.js/lib/core'],
          'tdeb-vendor':     ['d3', 'katex', 'jszip'],
        }
      }
    },
    chunkSizeWarningLimit: 1500,
    sourcemap: false
  }
})
