/**
 * Shared i18n types.
 *
 * These types are intentionally framework-agnostic (they do not depend on
 * `react-i18next`) so pure modules like `resolveLocale` and `formatters` can
 * import them without pulling in React.
 */

import type { Formatters } from './formatters';

/**
 * Literal union of locale tags supported by the application. Must match the
 * runtime tuple declared in `./constants.ts` (`SUPPORTED_LOCALES`).
 */
export type SupportedLocale = 'en' | 'pt-BR';

/**
 * Extras published on top of the `react-i18next` context. `useI18n()` merges
 * `t` from `useTranslation()` with these extras into the user-facing API.
 *
 * - `locale` is the active locale, narrowed to `SupportedLocale`.
 * - `setLocale(next)` persists the preference first, then asks i18next to
 *   change language. It resolves after the new catalog is loaded and applied.
 * - Formatter members come from `Formatters` and are memoized against
 *   `locale` inside `I18nProvider`.
 */
export interface I18nContextExtras extends Formatters {
  locale: SupportedLocale;
  setLocale: (next: SupportedLocale) => Promise<void>;
}
