/**
 * i18next initialization for the Kiro Cost Analyzer frontend.
 *
 * A single app-wide i18next instance is created synchronously on module load
 * and wired with:
 *
 * - `initReactI18next` — React bindings (`useTranslation`, `I18nextProvider`).
 * - `i18next-resources-to-backend` — lazy catalog loader. The `en` catalog is
 *   bundled statically (imported at the top of this module) so first render
 *   with `Active_Locale = 'en'` never waits on the network. Other locales are
 *   dynamic-imported and emitted as separate chunks by Vite.
 *
 * Init options are tuned for flat dot-notation keys:
 * - `keySeparator: false` and `nsSeparator: false` keep dots literal inside
 *   keys (`'dashboard.header.title'` is one key, not navigation into a nested
 *   object).
 * - `interpolation.prefix`/`suffix` keep the default `{{name}}` syntax.
 * - `missingKeyHandler` logs a single `console.error` per key per session via
 *   the exported `reportMissing` helper (non-production only).
 *
 * On every `languageChanged` event the preference is persisted to
 * `localStorage`. After init resolves, if the resolved locale differs from
 * what is stored, we realign storage so the preference is observable on the
 * next boot (Requirement 2.4).
 */

import i18next, { type i18n as I18n } from 'i18next';
import { initReactI18next } from 'react-i18next';
import resourcesToBackend from 'i18next-resources-to-backend';
import enCatalog from '../locales/en.json';
import { SUPPORTED_LOCALES } from './constants';
import { resolveInitialLocale } from './resolveLocale';
import { readStored, persistLocale } from './persistence';
import type { SupportedLocale } from './types';

const initialLocale = resolveInitialLocale(
  readStored(),
  typeof navigator !== 'undefined' ? navigator.language : undefined,
);

/** Shared app-wide i18next instance. Exported for tests and advanced callers. */
export const i18n: I18n = i18next.createInstance();

/**
 * Module-scoped dedup set for the single-error-per-key-per-session contract
 * of the missing-key handler. Exported as `reportMissing` (the function, not
 * the set) for testability — tests can re-import and exercise it directly.
 */
const missingSeen = new Set<string>();

/**
 * Emits one `console.error` per missing key per session, deduped via
 * `missingSeen`. Called from i18next's `missingKeyHandler` in non-production
 * builds only.
 */
export function reportMissing(key: string, langs: readonly string[]): void {
  if (missingSeen.has(key)) return;
  missingSeen.add(key);
  console.error(`[i18n] Missing key in catalogs ${langs.join(', ')}: ${key}`);
}

i18n
  .use(initReactI18next)
  .use(
    resourcesToBackend(async (language: string, _namespace: string) => { // eslint-disable-line @typescript-eslint/no-unused-vars
      // `en` is bundled statically; serve it synchronously to avoid the
      // round-trip on first render when the resolved locale is `en`.
      if (language === 'en') return enCatalog;
      // Every other locale is a Vite-emitted chunk, loaded on demand.
      const mod = await import(`../locales/${language}.json`);
      return mod.default;
    }),
  )
  .init({
    lng: initialLocale,
    // Fallback is always `'en'` — it is the source-of-truth catalog for the
    // key set and the terminal step of i18next's runtime fallback chain.
    fallbackLng: 'en',
    supportedLngs: SUPPORTED_LOCALES as unknown as string[],
    defaultNS: 'translation',
    ns: ['translation'],
    // Flat dot-notation keys — keep separators literal.
    keySeparator: false,
    nsSeparator: false,
    interpolation: {
      // React escapes output; i18next must not double-escape.
      escapeValue: false,
      prefix: '{{',
      suffix: '}}',
    },
    returnNull: false,
    saveMissing: import.meta.env.DEV,
    missingKeyHandler: (lngs, _ns, key) => {
      if (!import.meta.env.PROD) {
        reportMissing(key, lngs as readonly string[]);
      }
    },
  })
  .then(() => {
    // Align stored preference with the effective locale on first boot so the
    // resolution chain is idempotent across restarts (Requirement 2.4).
    if (readStored() !== i18n.language) {
      persistLocale(i18n.language as SupportedLocale);
    }
  });

// Persist any external language change (e.g., direct calls to
// `i18n.changeLanguage` outside React). `setLocale` in the provider already
// persists before calling `changeLanguage`; this handler is a safety net.
i18n.on('languageChanged', (lng) => {
  persistLocale(lng as SupportedLocale);
});
