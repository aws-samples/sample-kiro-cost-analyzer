/**
 * React provider composing the i18n runtime for the application.
 *
 * Layers, outer to inner:
 * 1. `I18nextProvider` — binds the shared `i18next` instance to
 *    `useTranslation()` throughout the tree.
 * 2. `InnerProvider` — reads `useTranslation()` so it re-renders when the
 *    active language changes, memoizes the `Formatters` against the active
 *    locale, and publishes the `I18nContextExtras` (locale, setLocale,
 *    formatters) on `I18nExtrasContext`.
 * 3. Cloudscape `I18nProvider` — receives the active locale and the matching
 *    message bundle so native Cloudscape component strings (DatePicker,
 *    Table empty states, etc.) flip atomically with our app strings.
 *
 * `setLocale(next)` persists the preference **before** calling
 * `instance.changeLanguage(next)` so the localStorage write is causally
 * upstream of the React re-render (Requirement 4.1).
 */

import { useCallback, useMemo, type ReactNode } from 'react';
import { I18nextProvider, useTranslation } from 'react-i18next';
import {
  I18nProvider as CloudscapeI18nProvider,
  type I18nProviderProps as CloudscapeI18nProviderProps,
} from '@cloudscape-design/components/i18n';
import enMessages from '@cloudscape-design/components/i18n/messages/all.en.json';
import ptBRMessages from '@cloudscape-design/components/i18n/messages/all.pt-BR.json';
import { i18n } from './index';
import { createFormatters, type Formatters } from './formatters';
import { persistLocale } from './persistence';
import { I18nExtrasContext } from './I18nExtrasContext';
import type { I18nContextExtras, SupportedLocale } from './types';

/**
 * Cloudscape message bundles keyed by supported locale. Both bundles ship
 * with `@cloudscape-design/components` and are imported statically — they
 * are small and Cloudscape dedupes message lookups per component.
 */
const CS_MESSAGES: Record<SupportedLocale, CloudscapeI18nProviderProps.Messages> = {
  en: enMessages as unknown as CloudscapeI18nProviderProps.Messages,
  'pt-BR': ptBRMessages as unknown as CloudscapeI18nProviderProps.Messages,
};

export interface I18nProviderProps {
  children: ReactNode;
}

export function I18nProvider({ children }: I18nProviderProps) {
  return (
    <I18nextProvider i18n={i18n}>
      <InnerProvider>{children}</InnerProvider>
    </I18nextProvider>
  );
}

function InnerProvider({ children }: { children: ReactNode }) {
  // `useTranslation` re-renders this subtree when `i18n.language` changes,
  // giving us a single React commit per locale switch.
  const { i18n: instance } = useTranslation();
  const locale = instance.language as SupportedLocale;

  const setLocale = useCallback(
    async (next: SupportedLocale) => {
      // Persist first so the preference is causally upstream of the
      // re-render (Req. 4.1). Even if `changeLanguage` rejects (network
      // error loading a lazy catalog), the preference is already saved.
      persistLocale(next);
      await instance.changeLanguage(next);
    },
    [instance],
  );

  const formatters = useMemo<Formatters>(() => createFormatters(locale), [locale]);

  const extras = useMemo<I18nContextExtras>(
    () => ({ locale, setLocale, ...formatters }),
    [locale, setLocale, formatters],
  );

  return (
    <I18nExtrasContext.Provider value={extras}>
      <CloudscapeI18nProvider locale={locale} messages={[CS_MESSAGES[locale]]}>
        {children}
      </CloudscapeI18nProvider>
    </I18nExtrasContext.Provider>
  );
}
