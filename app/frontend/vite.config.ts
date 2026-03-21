import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
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
    // Production optimizations
    target: 'es2015',
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,  // Remove console.log in production
        drop_debugger: true
      }
    },
    rollupOptions: {
      output: {
        // Manual chunking for better caching
        manualChunks: {
          'vue-vendor':      ['vue', 'vue-router', 'pinia'],
          'markdown-vendor': ['marked', 'highlight.js'],
          'force-graph-3d-vendor': ['3d-force-graph'],
          'force-graph-vendor':    ['force-graph'],
        }
      }
    },
    chunkSizeWarningLimit: 1000,  // Warn if chunks exceed 1MB
    sourcemap: false  // Disable sourcemaps in production for smaller size
  }
})
