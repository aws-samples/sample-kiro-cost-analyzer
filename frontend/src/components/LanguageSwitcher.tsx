/**
 * LanguageSwitcher — Cloudscape `ButtonDropdown` that lets the user change
 * the active locale (Requirement 3.1, 3.2, 3.5, 14.1–14.5).
 *
 * Contract:
 * - Lists every locale in `SUPPORTED_LOCALES` exactly once.
 * - Option text is the target language's name written *in that language*
 *   (Requirement 14.3), e.g. `"English"` for `en`, `"Português (Brasil)"`
 *   for `pt-BR`. The pt-BR item also carries a `lang="pt-BR"` attribute so
 *   screen readers announce the label with the correct phonetics
 *   (Cloudscape's `ButtonDropdown.Item` propagates `lang` to the rendered
 *   item element).
 * - The currently active locale is marked with the `check` icon.
 * - `ariaLabel` is drawn from the active catalog
 *   (`common.languageSwitcher.ariaLabel`) → `"Language"` in en,
 *   `"Idioma"` in pt-BR (Requirement 14.2).
 * - Keyboard support (Tab, Enter/Space to open, Enter/Space to select) is
 *   inherited from Cloudscape's `ButtonDropdown` (Requirement 14.1, 14.4,
 *   14.5).
 * - Trigger label shows the active locale's own name so the user can see
 *   their current selection without opening the dropdown.
 */

import ButtonDropdown, {
  type ButtonDropdownProps,
} from '@cloudscape-design/components/button-dropdown';
import { useI18n } from '../i18n/useI18n';
import { SUPPORTED_LOCALES } from '../i18n/constants';
import type { SupportedLocale } from '../i18n/types';

/**
 * Maps each supported locale to its self-referential display label — the
 * language's own name in the language itself. This is intentionally not
 * translated: an en user sees `"Português (Brasil)"` (not `"Portuguese"`)
 * so they recognize the option they are switching to, and a pt-BR user
 * sees `"English"` (not `"Inglês"`) for the same reason (Requirement 14.3).
 */
const LOCALE_LABELS: Record<SupportedLocale, string> = {
  en: 'English',
  'pt-BR': 'Português (Brasil)',
};

export interface LanguageSwitcherProps {
  /** DOM id for the dropdown trigger (used by tests and aria wiring). */
  id?: string;
}

export default function LanguageSwitcher({
  id = 'language-switcher',
}: LanguageSwitcherProps) {
  const { locale, setLocale, t } = useI18n();

  const items: ButtonDropdownProps.Items = SUPPORTED_LOCALES.map((code) => {
    const item: ButtonDropdownProps.Item = {
      id: code,
      text: LOCALE_LABELS[code],
      // `lang` on each item lets AT announce the foreign label with the
      // correct phonetics. Safe default: the label is always a string
      // whose natural language matches `code`.
      lang: code,
    };
    if (code === locale) {
      item.iconName = 'check';
    }
    return item;
  });

  return (
    <ButtonDropdown
      id={id}
      items={items}
      onItemClick={({ detail }) => {
        // Fire and forget — `setLocale` persists synchronously and then
        // awaits the async catalog load. A pending promise here is fine;
        // the switcher does not need to block on catalog load.
        void setLocale(detail.id as SupportedLocale);
      }}
      ariaLabel={t('common.languageSwitcher.ariaLabel')}
      expandableGroups={false}
    >
      {LOCALE_LABELS[locale]}
    </ButtonDropdown>
  );
}
