import { useState, useEffect, useCallback } from 'react';
import Toggle from '@cloudscape-design/components/toggle';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Flashbar, { type FlashbarProps } from '@cloudscape-design/components/flashbar';
import Box from '@cloudscape-design/components/box';
import { get, put, ApiError } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import SkeletonLoader from './SkeletonLoader';
import type { AppConfig } from '../types';

export default function PromptHistoryToggle() {
  const { t } = useI18n();

  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [flashItems, setFlashItems] = useState<FlashbarProps.MessageDefinition[]>([]);

  const fetchState = useCallback(async () => {
    setLoading(true);
    try {
      const config = await get<AppConfig>('/api/config');
      setEnabled(config.promptHistoryEnabled ?? false);
    } catch {
      setEnabled(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchState();
  }, [fetchState]);

  const handleToggle = async (checked: boolean) => {
    const previousValue = enabled;
    setEnabled(checked);
    setSaving(true);
    setFlashItems([]);

    try {
      await put<{ status: string; message: string; enabled: boolean }>(
        '/api/config/prompt-history-enabled',
        { enabled: checked }
      );
      setFlashItems([
        {
          type: 'success',
          content: t('settings.promptHistory.success'),
          dismissible: true,
          onDismiss: () => setFlashItems([]),
          id: 'prompt-history-save-success',
        },
      ]);
    } catch (err) {
      setEnabled(previousValue);
      const message = err instanceof ApiError ? err.message : t('settings.promptHistory.error');
      setFlashItems([
        {
          type: 'error',
          content: message,
          dismissible: true,
          onDismiss: () => setFlashItems([]),
          id: 'prompt-history-save-error',
        },
      ]);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Container header={<Header variant="h2">{t('settings.promptHistory.title')}</Header>}>
        <SkeletonLoader variant="container" />
      </Container>
    );
  }

  return (
    <Container
      header={
        <Header variant="h2" description={t('settings.promptHistory.description')}>
          {t('settings.promptHistory.title')}
        </Header>
      }
    >
      <SpaceBetween size="m">
        <Flashbar items={flashItems} />
        <Box padding={{ top: 's' }}>
          <Toggle
            onChange={({ detail }) => handleToggle(detail.checked)}
            checked={enabled}
            disabled={saving}
          >
            {t('settings.promptHistory.label')}
          </Toggle>
        </Box>
      </SpaceBetween>
    </Container>
  );
}
