import { useState, useEffect, useCallback } from 'react';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import Button from '@cloudscape-design/components/button';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useI18n } from '../i18n/useI18n';
import { get, ApiError } from '../api/client';
import type { PromptDetail } from '../types';

interface PromptDetailPanelProps {
  requestId: string;
  userId: string;
  onClose: () => void;
}

export default function PromptDetailPanel({ requestId, userId, onClose }: PromptDetailPanelProps) {
  const { t, formatDateTime } = useI18n();

  const [detail, setDetail] = useState<PromptDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDetail = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await get<PromptDetail>(`/api/prompts/${requestId}`, { userId });

      if (import.meta.env.DEV) {
        console.log('PromptDetailPanel: fetched detail for', requestId);
      }

      setDetail(response);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : t('promptDetail.error');
      setError(message);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [requestId, userId, t]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  const handleClose = () => {
    setDetail(null);
    onClose();
  };

  if (loading) {
    return (
      <SpaceBetween size="l">
        <Header variant="h2">{t('promptDetail.header', { category: requestId })}</Header>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
          <Box variant="p" color="text-body-secondary" padding={{ top: 's' }}>
            {t('promptDetail.loading')}
          </Box>
        </Box>
      </SpaceBetween>
    );
  }

  if (error) {
    return (
      <SpaceBetween size="l">
        <Header
          variant="h2"
          actions={<Button onClick={handleClose}>{t('promptDetail.close')}</Button>}
        >
          {t('promptDetail.header', { category: requestId })}
        </Header>
        <Alert
          type="error"
          action={<Button onClick={fetchDetail}>{t('promptDetail.retry')}</Button>}
        >
          {error}
        </Alert>
      </SpaceBetween>
    );
  }

  if (!detail) {
    return null;
  }

  return (
    <SpaceBetween size="l">
      <Header
        variant="h2"
        actions={<Button onClick={handleClose}>{t('promptDetail.close')}</Button>}
      >
        {t('promptDetail.header', { category: detail.category })}
      </Header>

      <ColumnLayout columns={3} variant="text-grid">
        <div>
          <Box variant="awsui-key-label">{t('promptDetail.metadata.timestamp')}</Box>
          <div>{formatDateTime(new Date(detail.timestamp))}</div>
        </div>
        <div>
          <Box variant="awsui-key-label">{t('promptDetail.metadata.category')}</Box>
          <div>{detail.category}</div>
        </div>
        <div>
          <Box variant="awsui-key-label">{t('promptDetail.metadata.model')}</Box>
          <div>{detail.modelId}</div>
        </div>
      </ColumnLayout>

      <SpaceBetween size="m">
        <div>
          <Box variant="awsui-key-label" margin={{ bottom: 'xs' }}>
            {t('promptDetail.section.prompt')}
          </Box>
          <div
            style={{
              maxHeight: '300px',
              overflowY: 'auto',
              padding: '12px',
              backgroundColor: 'var(--color-background-container-content)',
              border: '1px solid var(--color-border-divider-default)',
              borderRadius: '8px',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {detail.prompt}
          </div>
        </div>

        <div>
          <Box variant="awsui-key-label" margin={{ bottom: 'xs' }}>
            {t('promptDetail.section.response')}
          </Box>
          <div
            style={{
              maxHeight: '300px',
              overflowY: 'auto',
              padding: '12px',
              backgroundColor: 'var(--color-background-container-content)',
              border: '1px solid var(--color-border-divider-default)',
              borderRadius: '8px',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {detail.response}
          </div>
        </div>
      </SpaceBetween>
    </SpaceBetween>
  );
}
