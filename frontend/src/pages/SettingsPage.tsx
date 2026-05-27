import { useEffect, useState, useCallback } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Tabs, { type TabsProps } from '@cloudscape-design/components/tabs';
import { get, put, post } from '../api/client';
import SkeletonLoader from '../components/SkeletonLoader';
import PricingSettingsPanel from '../components/PricingSettingsPanel';
import EngagementSettingsPanel from '../components/EngagementSettingsPanel';
import PromptHistoryToggle from '../components/PromptHistoryToggle';
import { useAuth } from '../auth/useAuth';
import { useI18n } from '../i18n/useI18n';
import { humanize } from '../utils/cronHumanizer';
import type { AppConfig, EtlStatus, EtlSchedule } from '../types';

function etlStatusType(status: string): 'success' | 'error' | 'warning' | 'info' | 'stopped' {
  switch (status) {
    case 'success':
      return 'success';
    case 'error':
    case 'failed':
      return 'error';
    case 'running':
    case 'in_progress':
      return 'info';
    default:
      return 'stopped';
  }
}

export default function SettingsPage() {
  const { t, formatDateTime } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.groups?.includes('Admins') ?? false;

  const formatDateTimeValue = (value: string | null): string => {
    if (!value) return '—';
    try {
      return formatDateTime(new Date(value));
    } catch {
      return value;
    }
  };

  const [bucketName, setBucketName] = useState('');
  const [sourcePrefix, setSourcePrefix] = useState('');
  const [promptsPrefix, setPromptsPrefix] = useState('');
  const [identityStoreId, setIdentityStoreId] = useState('');
  const [etlStatus, setEtlStatus] = useState<EtlStatus | null>(null);
  const [schedule, setSchedule] = useState<EtlSchedule | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savingPrompts, setSavingPrompts] = useState(false);
  const [savingIdentity, setSavingIdentity] = useState(false);
  const [sourceBucketRoleArn, setSourceBucketRoleArn] = useState('');
  const [identityStoreRoleArn, setIdentityStoreRoleArn] = useState<string>('');
  const [savingRoleArn, setSavingRoleArn] = useState(false);
  const [savingIdentityStoreRoleArn, setSavingIdentityStoreRoleArn] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [resp, scheduleResp] = await Promise.all([
        get<AppConfig>('/api/config'),
        get<EtlSchedule>('/api/config/schedule').catch((): EtlSchedule => ({
          expression: null,
          enabled: false,
          humanReadable: '',
          error: true,
        })),
      ]);
      setBucketName(resp.bucketName ?? '');
      setSourcePrefix(resp.sourcePrefix ?? '');
      setPromptsPrefix(resp.promptsPrefix ?? '');
      setIdentityStoreId(resp.identityStoreId ?? '');
      setSourceBucketRoleArn(resp.sourceBucketRoleArn ?? '');
      setIdentityStoreRoleArn(resp.identityStoreRoleArn ?? '');
      setEtlStatus(resp.etlStatus ?? null);
      setSchedule(scheduleResp);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('settings.error.loadConfig');
      if (msg.includes('5')) {
        setError(t('common.error.serverError'));
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleSave = async () => {
    if (!bucketName.trim()) {
      setError(t('settings.error.bucketNameRequired'));
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const resp = await put<{ status: string; message: string }>('/api/config/bucket', {
        bucketName: bucketName.trim(),
        sourcePrefix: sourcePrefix.trim(),
      });
      if (resp.status === 'error') {
        setError(resp.message);
      } else {
        setSuccess(resp.message || t('settings.success.saved'));
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('settings.error.save');
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleTriggerEtl = async () => {
    setTriggering(true);
    setTriggerMsg(null);
    setError(null);
    try {
      const resp = await post<{ status: string; executionId?: string; message?: string }>('/api/etl/trigger');
      if (resp.status === 'error') {
        setError(resp.message ?? t('settings.error.triggerEtl'));
      } else {
        setTriggerMsg(t('settings.success.etlTriggered'));
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('settings.error.triggerEtl');
      setError(msg);
    } finally {
      setTriggering(false);
    }
  };

  const handleSavePromptsPrefix = async () => {
    setSavingPrompts(true);
    setError(null);
    setSuccess(null);
    try {
      const resp = await put<{ status: string; message: string }>('/api/config/prompts-prefix', {
        promptsPrefix: promptsPrefix.trim(),
      });
      if (resp.status === 'error') {
        setError(resp.message);
      } else {
        setSuccess(resp.message || t('settings.success.promptsPrefixSaved'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.error.savePromptsPrefix'));
    } finally {
      setSavingPrompts(false);
    }
  };

  const handleSaveIdentityStoreId = async () => {
    setSavingIdentity(true);
    setError(null);
    setSuccess(null);
    try {
      const resp = await put<{ status: string; message: string }>('/api/config/identity-store-id', {
        identityStoreId: identityStoreId.trim(),
      });
      if (resp.status === 'error') {
        setError(resp.message);
      } else {
        setSuccess(resp.message || t('settings.success.identityStoreIdSaved'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.error.saveIdentityStoreId'));
    } finally {
      setSavingIdentity(false);
    }
  };

  const handleSaveSourceBucketRoleArn = async () => {
    setSavingRoleArn(true);
    setError(null);
    setSuccess(null);
    try {
      const resp = await put<{ status: string; message: string }>('/api/config/source-bucket-role-arn', {
        sourceBucketRoleArn: sourceBucketRoleArn.trim(),
      });
      if (resp.status === 'error') {
        setError(resp.message);
      } else {
        setSuccess(resp.message || t('settings.success.sourceBucketRoleArnSaved'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.error.saveSourceBucketRoleArn'));
    } finally {
      setSavingRoleArn(false);
    }
  };

  // i18n keys `settings.identityStoreRoleArn.status.success` / `...status.error`
  // are used as the user-facing status messages; empty input is allowed and
  // disables cross-account Identity Store mode on the backend.
  const handleSaveIdentityStoreRoleArn = async () => {
    setSavingIdentityStoreRoleArn(true);
    setError(null);
    setSuccess(null);
    try {
      const resp = await put<{ status: string; message: string }>('/api/config/identity-store-role-arn', {
        identityStoreRoleArn: identityStoreRoleArn.trim(),
      });
      if (resp.status === 'error') {
        setError(resp.message || t('settings.identityStoreRoleArn.status.error'));
      } else {
        setSuccess(resp.message || t('settings.identityStoreRoleArn.status.success'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.identityStoreRoleArn.status.error'));
    } finally {
      setSavingIdentityStoreRoleArn(false);
    }
  };

  const etlContent = (
    <Container
      header={
        <Header
          variant="h2"
          actions={
            <Button onClick={handleTriggerEtl} loading={triggering} iconName="caret-right-filled">
              {t('settings.etl.trigger')}
            </Button>
          }
        >
          {t('settings.etl.title')}
        </Header>
      }
    >
      {!etlStatus || (!etlStatus.lastExecution && !etlStatus.status) ? (
        <Box color="text-status-inactive" textAlign="center" padding="l">
          {t('settings.etl.noExecution')}
        </Box>
      ) : (
        <ColumnLayout columns={2} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">{t('settings.etl.lastExecution')}</Box>
            <div>{formatDateTimeValue(etlStatus.lastExecution)}</div>
          </div>
          <div>
            <Box variant="awsui-key-label">{t('settings.etl.status')}</Box>
            <StatusIndicator type={etlStatusType(etlStatus.status)}>
              {etlStatus.status || t('settings.etl.statusUnknown')}
            </StatusIndicator>
          </div>
          <div>
            <Box variant="awsui-key-label">{t('settings.etl.filesProcessed')}</Box>
            <div>{etlStatus.filesProcessed ?? 0}</div>
          </div>
          <div>
            <Box variant="awsui-key-label">{t('settings.etl.recordsWritten')}</Box>
            <div>{etlStatus.recordsWritten ?? 0}</div>
          </div>
          <div>
            <Box variant="awsui-key-label">{t('settings.etl.schedule')}</Box>
            {schedule?.error ? (
              <StatusIndicator type="warning">{t('settings.etl.schedule.unavailable')}</StatusIndicator>
            ) : !schedule?.enabled ? (
              <StatusIndicator type="stopped">{t('settings.etl.schedule.disabled')}</StatusIndicator>
            ) : (
              <div>{humanize(schedule.expression ?? '', t)}</div>
            )}
          </div>
        </ColumnLayout>
      )}
    </Container>
  );

  const dataContent = (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">{t('settings.bucket.title')}</Header>}>
        <Form
          actions={
            <Button variant="primary" onClick={handleSave} loading={saving}>
              {t('settings.bucket.submit')}
            </Button>
          }
        >
          <SpaceBetween size="m">
            <FormField label={t('settings.bucket.nameField.label')} description={t('settings.bucket.nameField.description')}>
              <Input
                value={bucketName}
                onChange={({ detail }) => setBucketName(detail.value)}
                placeholder={t('settings.bucket.nameField.placeholder')}
                disabled={loading}
              />
            </FormField>
            <FormField label={t('settings.bucket.sourcePrefixField.label')} description={t('settings.bucket.sourcePrefixField.description')}>
              <Input
                value={sourcePrefix}
                onChange={({ detail }) => setSourcePrefix(detail.value)}
                placeholder={t('settings.bucket.sourcePrefixField.placeholder')}
                disabled={loading}
              />
            </FormField>
          </SpaceBetween>
        </Form>
      </Container>

      <Container header={<Header variant="h2">{t('settings.prompts.title')}</Header>}>
        <Form
          actions={
            <Button variant="primary" onClick={handleSavePromptsPrefix} loading={savingPrompts}>
              {t('settings.prompts.submit')}
            </Button>
          }
        >
          <FormField label={t('settings.prompts.prefixField.label')} description={t('settings.prompts.prefixField.description')}>
            <Input
              value={promptsPrefix}
              onChange={({ detail }) => setPromptsPrefix(detail.value)}
              placeholder={t('settings.prompts.prefixField.placeholder')}
              disabled={loading}
            />
          </FormField>
        </Form>
      </Container>

      <Container header={<Header variant="h2">{t('settings.crossAccount.title')}</Header>}>
        <Form
          actions={
            <Button variant="primary" onClick={handleSaveSourceBucketRoleArn} loading={savingRoleArn}>
              {t('settings.crossAccount.submit')}
            </Button>
          }
        >
          <FormField label={t('settings.crossAccount.roleArn.label')} description={t('settings.crossAccount.roleArn.description')}>
            <Input
              value={sourceBucketRoleArn}
              onChange={({ detail }) => setSourceBucketRoleArn(detail.value)}
              placeholder={t('settings.crossAccount.roleArn.placeholder')}
              disabled={loading}
            />
          </FormField>
        </Form>
      </Container>
    </SpaceBetween>
  );

  const identityCenterContent = (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">{t('settings.identityStore.title')}</Header>}>
        <Form
          actions={
            <Button variant="primary" onClick={handleSaveIdentityStoreId} loading={savingIdentity}>
              {t('settings.identityStore.submit')}
            </Button>
          }
        >
          <FormField label={t('settings.identityStore.label')} description={t('settings.identityStore.description')}>
            <Input
              value={identityStoreId}
              onChange={({ detail }) => setIdentityStoreId(detail.value)}
              placeholder={t('settings.identityStore.placeholder')}
              disabled={loading}
            />
          </FormField>
        </Form>
      </Container>

      <Container header={<Header variant="h2">{t('settings.identityStoreRoleArn.title')}</Header>}>
        <Form
          actions={
            <Button variant="primary" onClick={handleSaveIdentityStoreRoleArn} loading={savingIdentityStoreRoleArn}>
              {t('settings.identityStoreRoleArn.save')}
            </Button>
          }
        >
          <FormField
            label={t('settings.identityStoreRoleArn.label')}
            description={t('settings.identityStoreRoleArn.description')}
          >
            <Input
              value={identityStoreRoleArn}
              onChange={({ detail }) => setIdentityStoreRoleArn(detail.value)}
              placeholder={t('settings.identityStoreRoleArn.placeholder')}
              disabled={loading}
            />
          </FormField>
        </Form>
      </Container>
    </SpaceBetween>
  );

  const configTabs: TabsProps.Tab[] = [
    { id: 'etl', label: t('settings.tabs.etl'), content: etlContent },
    { id: 'data', label: t('settings.tabs.data'), content: dataContent },
    { id: 'identity', label: t('settings.tabs.identity'), content: identityCenterContent },
    { id: 'engagement', label: t('settings.tabs.engagement'), content: <EngagementSettingsPanel /> },
    ...(isAdmin
      ? [{ id: 'pricing', label: t('settings.tabs.pricing'), content: <PricingSettingsPanel /> }]
      : []),
    ...(isAdmin
      ? [{ id: 'prompts', label: t('settings.tabs.prompts'), content: <PromptHistoryToggle /> }]
      : []),
  ];

  return (
    <SpaceBetween size="l">
      {error && (
        <Alert type="error" dismissible onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}
      {success && (
        <Alert type="success" dismissible onDismiss={() => setSuccess(null)}>
          {success}
        </Alert>
      )}
      {triggerMsg && (
        <Alert type="info" dismissible onDismiss={() => setTriggerMsg(null)}>
          {triggerMsg}
        </Alert>
      )}

      {loading && !etlStatus ? (
        <SpaceBetween size="l">
          <SkeletonLoader variant="container" />
          <SkeletonLoader variant="container" />
          <SkeletonLoader variant="container" />
        </SpaceBetween>
      ) : (
        <Tabs tabs={configTabs} />
      )}
    </SpaceBetween>
  );
}
