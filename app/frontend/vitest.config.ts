import { configDefaults, defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'url'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/tests/setup.ts'],
    // tests/e2e/*.spec.ts are Playwright specs (`npm run test:e2e`); loaded
    // by vitest they abort with "did not expect test.describe()". tests/live
    // holds the read-only review of the deployed site (its own config).
    exclude: [...configDefaults.exclude, 'tests/e2e/**', 'tests/live/**'],
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
