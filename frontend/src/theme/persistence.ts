/**
 * Visual-mode preference persistence.
 *
 * Mirrors `src/i18n/persistence.ts` — `localStorage` wrapped in try/catch,
 * single `console.warn` per session when writes fail, and a test helper to
 * reset the dedup flag between tests.
 */

import { THEME_STORAGE_KEY } from './constants';
import type { VisualMode } from './types';

let persistWarned = false;

export function readStoredVisualMode(): string | null {
  try {
    if (typeof localStorage === 'undefined') return null;
    return localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function persistVisualMode(mode: VisualMode): void {
  try {
    if (typeof localStorage === 'undefined') return;
    localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    if (!persistWarned) {
      persistWarned = true;
      console.warn(
        `[theme] Failed to persist visual-mode preference to localStorage under key "${THEME_STORAGE_KEY}". ` +
          'Preference will not survive a page reload.',
      );
    }
  }
}

/** Test helper — resets the module-scoped warn flag. */
export function __resetThemePersistWarnedForTests(): void {
  persistWarned = false;
}
