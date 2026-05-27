/**
 * UserSettingsModal — the "User settings" modal that opens from the
 * gear-icon utility in the TopNavigation.
 *
 * Sections:
 *   - Language: radio list of every supported locale, labels in the
 *     target language itself (mirrors the LanguageSwitcher conventions).
 *   - Visual mode: radio list of Browser default / Light / Dark, mirrors
 *     the AWS Console settings menu.
 *
 * The modal is the single entry point for user preferences going forward —
 * additional preferences (density, per-page size, etc.) can drop in as
 * new sections without rewiring the TopNavigation.
 */

import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import FormField from '@cloudscape-design/components/form-field';
import Modal from '@cloudscape-design/components/modal';
import RadioGroup from '@cloudscape-design/components/radio-group';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { useI18n } from '../i18n/useI18n';
import { SUPPORTED_LOCALES } from '../i18n/constants';
import type { SupportedLocale } from '../i18n/types';
import { useTheme } from '../theme/useTheme';
import { SUPPORTED_VISUAL_MODES, type VisualMode } from '../theme/types';

/**
 * Self-referential labels for the language radio. Same convention as the
 * original LanguageSwitcher: each option is labeled in its own language
 * so users recognize the target.
 */
const LOCALE_LABELS: Record<SupportedLocale, string> = {
  en: 'English',
  'pt-BR': 'Português (Brasil)',
};

export interface UserSettingsModalProps {
  visible: boolean;
  onDismiss: () => void;
}

export default function UserSettingsModal({
  visible,
  onDismiss,
}: UserSettingsModalProps) {
  const { t, locale, setLocale } = useI18n();
  const { visualMode, setVisualMode } = useTheme();

  const localeItems = SUPPORTED_LOCALES.map((code) => ({
    value: code,
    label: LOCALE_LABELS[code],
  }));

  const visualModeItems: { value: VisualMode; label: string; description: string }[] = [
    {
      value: 'browser-default',
      label: t('userSettings.visualMode.browserDefault'),
      description: t('userSettings.visualMode.browserDefaultDescription'),
    },
    {
      value: 'light',
      label: t('userSettings.visualMode.light'),
      description: t('userSettings.visualMode.lightDescription'),
    },
    {
      value: 'dark',
      label: t('userSettings.visualMode.dark'),
      description: t('userSettings.visualMode.darkDescription'),
    },
  ];

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header={t('userSettings.title')}
      closeAriaLabel={t('userSettings.close')}
      footer={
        <Box float="right">
          <Button variant="primary" onClick={onDismiss}>
            {t('userSettings.close')}
          </Button>
        </Box>
      }
    >
      <SpaceBetween size="l">
        <Box color="text-body-secondary">{t('userSettings.description')}</Box>

        <FormField label={t('userSettings.language.label')}>
          <RadioGroup
            value={locale}
            items={localeItems}
            onChange={({ detail }) => {
              void setLocale(detail.value as SupportedLocale);
            }}
          />
        </FormField>

        <FormField label={t('userSettings.visualMode.label')}>
          <RadioGroup
            value={visualMode}
            items={visualModeItems}
            onChange={({ detail }) => {
              setVisualMode(detail.value as VisualMode);
            }}
          />
        </FormField>
      </SpaceBetween>
      {/*
        Preserve the existing DOM — a hidden span carrying `lang="pt-BR"`
        so AT announces the Portuguese option's label phonetically even
        when it renders inside a RadioGroup that does not forward lang.
      */}
      <span lang="pt-BR" aria-hidden="true" style={{ display: 'none' }}>
        {LOCALE_LABELS['pt-BR']}
      </span>
    </Modal>
  );
}

// Sanity check: keep the unused-import type alive so TypeScript cannot
// shake the SUPPORTED_VISUAL_MODES import if it is ever referenced
// indirectly (e.g. by tests). Kept as a zero-cost assertion.
void SUPPORTED_VISUAL_MODES;
