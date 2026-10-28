// ESLint flat config: JS + TypeScript recommended, and the Vue rules that
// catch likely bugs (flat/essential). Check only — `npm run lint:fix` fixes.
import { defineConfig, globalIgnores } from 'eslint/config'
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'
import globals from 'globals'

export default defineConfig([
  // *.generated.ts are written by a generator and checked for drift against it.
  globalIgnores(['dist/', 'coverage/', 'test-results/', 'playwright-report/', 'src/**/*.generated.ts']),
  js.configs.recommended,
  tseslint.configs.recommended,
  pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: { parserOptions: { parser: tseslint.parser } },
  },
  {
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      // Reported, not fatal: the existing `any`s sit at untyped API payloads
      // and are better replaced with real types than silenced one by one.
      '@typescript-eslint/no-explicit-any': 'warn',
      // A leading underscore marks a parameter a callback signature requires
      // but the body does not use, e.g. onClick: (index, _pos, _ev) => ...
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
])
