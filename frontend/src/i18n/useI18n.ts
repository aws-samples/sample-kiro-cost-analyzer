/**
 * Public hook for the i18n runtime.
 *
 * Combines `react-i18next`'s `useTranslation()` with the extras published by
 * `I18nProvider` (locale, setLocale, formatters) into a single ergonomic
 * API. Throws if called outside the provider so missing wiring is caught
 * immediately in development.
 */

import { useContext } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { I18nExtrasContext } from './I18nExtrasContext';
import type { I18nContextExtras } from './types';

export interface UseI18nResult extends I18nContextExtras {
  /**
   * `react-i18next` translation function. `t(key)` looks up the active
   * catalog, falling back to `en` and then to the key itself. Placeholder
   * interpolation uses `{{name}}` syntax.
   */
  t: TFunction;
}

/**
 * Primary hook for accessing translations, formatters, and locale control.
 * Must be called inside an `<I18nProvider>`.
 */
export function useI18n(): UseI18nResult {
  const { t } = useTranslation();
  const extras = useContext(I18nExtrasContext);
  if (!extras) {
    throw new Error('useI18n must be used within <I18nProvider>');
  }
  return { ...extras, t };
}
