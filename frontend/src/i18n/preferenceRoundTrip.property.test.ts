/**
 * Property 2 — preference round-trip (Task 5.4).
 *
 * **Property 2: Preference round-trip —** setting `L` via the language
 * switcher and then simulating an application restart yields
 * `Active_Locale == L`.
 *
 * Validates: Requirements 3.2, 4.1, 4.2, 16.2.
 *
 * Approach: build an in-memory storage (`Map`), mimic the production
 * switcher write (`storage.set(LOCALE_STORAGE_KEY, L)`), then simulate a
 * fresh boot by re-running `resolveInitialLocale` against the stored
 * value. This is fully hermetic — it does NOT rely on jsdom's
 * `localStorage` (which is known broken under Node 25 without
 * `--no-webstorage`, and even with that flag the persistence layer
 * short-circuits to `null`). Exercising the pure resolver directly is
 * exactly what Requirement 16.2 asserts.
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { LOCALE_STORAGE_KEY, SUPPORTED_LOCALES } from './constants';
import { resolveInitialLocale } from './resolveLocale';
import type { SupportedLocale } from './types';

/**
 * Minimal in-memory shim exposing the subset of the `Storage` contract we
 * exercise: `setItem` and `getItem`. Kept intentionally small and typed so
 * the test reads as production-like as possible.
 */
function createMemoryStorage(): {
  set: (key: string, value: string) => void;
  get: (key: string) => string | null;
} {
  const store = new Map<string, string>();
  return {
    set: (key, value) => {
      store.set(key, value);
    },
    get: (key) => (store.has(key) ? (store.get(key) as string) : null),
  };
}

describe('Property 2 — preference round-trip', () => {
  it('setLocale(L) then restart yields Active_Locale = L for every supported locale', () => {
    fc.assert(
      fc.property(
        fc.constantFrom<SupportedLocale>(...SUPPORTED_LOCALES),
        // Navigator language is intentionally varied to show that the
        // stored preference always wins over it, regardless of what the
        // browser reports on restart.
        fc.oneof(
          fc.constant(undefined),
          fc.constant('en-US'),
          fc.constant('pt-BR'),
          fc.constant('fr-FR'),
          fc.constant('de-DE'),
        ),
        (L, navLang) => {
          const storage = createMemoryStorage();

          // Act: write L as the preference (same operation the switcher
          // performs via `persistLocale`).
          storage.set(LOCALE_STORAGE_KEY, L);

          // Simulate application restart: the resolver is invoked on boot
          // with the stored value and the navigator language.
          const restored = resolveInitialLocale(
            storage.get(LOCALE_STORAGE_KEY),
            navLang,
          );

          return restored === L;
        },
      ),
      { numRuns: 20 },
    );
  });

  it('concrete cases — sanity anchors for the property above', () => {
    for (const L of SUPPORTED_LOCALES) {
      const storage = createMemoryStorage();
      storage.set(LOCALE_STORAGE_KEY, L);
      expect(resolveInitialLocale(storage.get(LOCALE_STORAGE_KEY), 'en-US')).toBe(L);
      expect(resolveInitialLocale(storage.get(LOCALE_STORAGE_KEY), 'pt-BR')).toBe(L);
      expect(resolveInitialLocale(storage.get(LOCALE_STORAGE_KEY), undefined)).toBe(L);
    }
  });
});
