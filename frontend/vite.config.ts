/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Single version source: the root VERSION file. Read at config-eval time —
// a missing file fails the build loudly instead of embedding a placeholder.
const appVersion = readFileSync(
  fileURLToPath(new URL('../VERSION', import.meta.url)),
  'utf-8',
).trim()

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    define: {
      global: 'globalThis',
      __APP_VERSION__: JSON.stringify(appVersion),
    },
    build: {
      rollupOptions: {
        // amazon-cognito-identity-js ships a CookieStorage module that calls
        // `Cookies.get()` against the js-cookie default export. We pin
        // js-cookie to 3.x via package.json `overrides` to clear a high-sev
        // advisory (GHSA-qjx8-664m-686j); 3.x dropped the default export,
        // which makes Rollup warn that the import is undefined. This app
        // configures Cognito with the default localStorage backend (see
        // src/auth/AuthProvider.tsx — no `Storage` option), so CookieStorage
        // is never instantiated and the warning is benign. Filter only this
        // exact case; let every other warning through.
        onwarn(warning, defaultHandler) {
          if (
            warning.code === 'IMPORT_IS_UNDEFINED' &&
            typeof warning.id === 'string' &&
            warning.id.includes('amazon-cognito-identity-js') &&
            warning.id.includes('CookieStorage')
          ) {
            return
          }
          defaultHandler(warning)
        },
      },
    },
    server: {
      proxy: {
        '/api': {
          target: env.VITE_API_URL || 'http://localhost:3001',
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
    },
  }
})
