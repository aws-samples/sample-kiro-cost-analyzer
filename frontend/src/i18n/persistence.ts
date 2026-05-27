/**
 * Locale preference persistence.
 *
 * Wraps `localStorage` reads and writes in try/catch so that environments
 * where storage is unavailable (private browsing, disk quota, disabled via
 * policy) degrade gracefully without throwing.
 *
 * - `readStored()` returns the raw string (not validated against
 *   `SUPPORTED_LOCALES` — validation is the resolver's job).
 * - `persistLocale(locale)` writes the preference. On failure it emits a
 *   single `console.warn` per session, deduped via a module-scoped flag, to
 *   avoid log spam when the underlying storage is persistently broken.
 */

import { LOCALE_STORAGE_KEY } from './constants';
import type { SupportedLocale } from './types';

/** Module-scoped dedup flag for the single-warn-per-session contract. */
let persistWarned = false;

/**
 * Reads the stored locale preference. Returns `null` when:
 * - the key is absent
 * - `localStorage` throws (e.g., Safari private mode without override)
 * - `localStorage` is not defined (e.g., SSR, non-browser test env)
 */
export function readStored(): string | null {
  try {
    if (typeof localStorage === 'undefined') return null;
    return localStorage.getItem(LOCALE_STORAGE_KEY);
  } catch {
    return null;
  }
}

/**
 * Persists the locale preference. Swallows any exception raised by
 * `localStorage.setItem` (storage full, access denied) and warns exactly once
 * per session so the error is observable without flooding the console.
 */
export function persistLocale(locale: SupportedLocale): void {
  try {
    if (typeof localStorage === 'undefined') return;
    localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    if (!persistWarned) {
      persistWarned = true;
      console.warn(
        `[i18n] Failed to persist locale preference to localStorage under key "${LOCALE_STORAGE_KEY}". ` +
          'Preference will not survive a page reload.',
      );
    }
  }
}

/**
 * Test helper — resets the module-scoped `persistWarned` flag so unit tests
 * can assert the single-warn-per-session behavior across multiple cases
 * without leaking state between tests.
 */
export function __resetPersistWarnedForTests(): void {
  persistWarned = false;
}
