/**
 * i18n constants for the Kiro Cost Analyzer frontend.
 *
 * These constants are consumed by the i18n runtime (`I18nProvider`, `resolveLocale`,
 * `persistence`) and by downstream modules that need to reason about the set of
 * supported locales or the brand literal.
 *
 * `DEFAULT_LOCALE` is set to `'pt-BR'` in Step 1 so scaffolding this module does
 * not change existing behavior. It is flipped to `'en'` in Step 6 of the
 * migration plan (see `.kiro/specs/i18n-english-default/tasks.md`).
 */

import type { SupportedLocale } from './types';

/**
 * Ordered tuple of locales the application supports. The order is also the
 * display order in the `LanguageSwitcher` dropdown.
 */
export const SUPPORTED_LOCALES = ['en', 'pt-BR'] as const satisfies readonly SupportedLocale[];

/**
 * Locale used as the final fallback when neither `localStorage` nor
 * `navigator.language` yields a supported locale. Also wired to i18next's
 * `fallbackLng` so missing keys in any other catalog fall back to this one.
 *
 * Flipped from `'pt-BR'` to `'en'` in Step 6 — the single change that
 * shifts first-load behavior for users whose browser language is neither en
 * nor pt. Brazilian browsers still resolve to pt-BR via the navigator step
 * of the resolution chain.
 */
export const DEFAULT_LOCALE: SupportedLocale = 'en';

/**
 * `localStorage` key under which the user's explicit locale preference is
 * persisted. Prefixed with `kiro_` following the convention used by the auth
 * module for other client-side storage keys.
 */
export const LOCALE_STORAGE_KEY = 'kiro_locale';

/**
 * Canonical brand literals. These values are identical across every supported
 * locale (brand invariance — Requirement 9.1). They are surfaced through
 * `brand.*` catalog keys so call sites still go through `t(key)` and so the
 * key-parity check covers them.
 */
export const BRAND_STRINGS = {
  productName: 'Kiro Cost Analyzer',
  short: 'Kiro',
} as const;
