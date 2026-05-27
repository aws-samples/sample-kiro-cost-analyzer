/**
 * Pure locale-resolution logic.
 *
 * `resolveInitialLocale` is the deterministic chain used on first load to pick
 * the active locale. It is side-effect free so it can be unit- and
 * property-tested without mocks (see Property 1 in the design).
 *
 * Resolution order:
 * 1. `stored` — honored iff it is already in `SUPPORTED_LOCALES`.
 * 2. `navigatorLanguage` — normalized via `normalizeToSupported` so any
 *    primary-subtag match (`'en'`, `'en-*'`, `'pt'`, `'pt-*'`, `'pt_*'`) maps
 *    to a supported locale.
 * 3. `DEFAULT_LOCALE` — terminal fallback.
 */

import { DEFAULT_LOCALE, SUPPORTED_LOCALES } from './constants';
import type { SupportedLocale } from './types';

/**
 * Normalizes an arbitrary BCP-47-ish language tag to a supported locale,
 * matching only on the primary subtag.
 *
 * - `'en'`, `'en-US'`, `'en-GB'`, `'EN'`, … → `'en'`
 * - `'pt'`, `'pt-BR'`, `'pt-PT'`, `'pt-br'`, `'pt_PT'`, … → `'pt-BR'`
 * - anything else (including `undefined`, empty string, `'fr'`, `'de-DE'`) →
 *   `null`, signaling "fall through to the next step of the resolution chain".
 *
 * The comparison is case-insensitive on the primary subtag. Both `-` and `_`
 * are accepted as subtag separators so POSIX-style tags like `'pt_BR'` are
 * tolerated.
 */
export function normalizeToSupported(lang: string | undefined): SupportedLocale | null {
  if (!lang) return null;
  // Split on either `-` or `_` and keep only the primary subtag, lowercased.
  const primary = lang.split(/[-_]/)[0]?.toLowerCase();
  if (!primary) return null;
  if (primary === 'en') return 'en';
  if (primary === 'pt') return 'pt-BR';
  return null;
}

/**
 * Resolves the initial locale deterministically given the persisted value and
 * the navigator language. Always returns a member of `SUPPORTED_LOCALES`
 * (totality — Property 1).
 */
export function resolveInitialLocale(
  stored: string | null,
  navigatorLanguage: string | undefined,
): SupportedLocale {
  if (stored !== null && (SUPPORTED_LOCALES as readonly string[]).includes(stored)) {
    return stored as SupportedLocale;
  }
  const normalized = normalizeToSupported(navigatorLanguage);
  if (normalized !== null) return normalized;
  return DEFAULT_LOCALE;
}
