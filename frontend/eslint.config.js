import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // These two arrived with plugin upgrades (both dependencies are
      // caret-ranged) and flag established patterns across this codebase rather
      // than new mistakes. They are kept ON and visible as warnings, so `npm run
      // lint` reports them without failing CI on work that is unrelated to them.
      // Promote each back to "error" as its cleanup lands.
      //
      // react-hooks/set-state-in-effect (20 sites): every one is the
      // `useEffect(() => { fetchX(); }, [fetchX])` load-on-mount pattern used by
      // every data-driven page here. Satisfying the rule means moving data
      // fetching out of effects app-wide, which is an architectural change, not a
      // lint fix.
      //
      // react-refresh/only-export-components (14 sites): a dev-only Fast Refresh
      // concern — pure helpers, one context, and one constant exported next to a
      // component. No runtime effect. The fix is to relocate each symbol to its
      // own module and update every importer (several are unit-tested directly),
      // which belongs in its own change.
      'react-hooks/set-state-in-effect': 'warn',
      'react-refresh/only-export-components': 'warn',
    },
  },
])
