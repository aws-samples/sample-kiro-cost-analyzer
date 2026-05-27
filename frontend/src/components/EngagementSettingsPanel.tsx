import { useState, useEffect, useCallback } from 'react';
import { Trans } from 'react-i18next';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Alert from '@cloudscape-design/components/alert';
import { get, put } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import SkeletonLoader from './SkeletonLoader';

interface EngagementThresholdsResponse {
  thresholds: {
    power: { messages: number; daysActive: number };
    active: { messages: number; daysActive: number };
    dormantDaysThreshold: number;
  };
  status: string;
  message?: string;
}

export default function EngagementSettingsPanel() {
  const { t } = useI18n();

  const [powerMessages, setPowerMessages] = useState('');
  const [powerDays, setPowerDays] = useState('');
  const [activeMessages, setActiveMessages] = useState('');
  const [activeDays, setActiveDays] = useState('');
  const [dormantDays, setDormantDays] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchThresholds = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await get<EngagementThresholdsResponse>('/api/config/engagement-thresholds');
      const th = resp.thresholds;
      if (th) {
        setPowerMessages(String(th.power?.messages ?? 100));
        setPowerDays(String(th.power?.daysActive ?? 10));
        setActiveMessages(String(th.active?.messages ?? 20));
        setActiveDays(String(th.active?.daysActive ?? 3));
        setDormantDays(String(th.dormantDaysThreshold ?? 30));
      }
    } catch {
      setError(t('engagement.settings.error.save'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchThresholds();
  }, [fetchThresholds]);

  const validate = (): string | null => {
    const pm = Number(powerMessages);
    const pd = Number(powerDays);
    const am = Number(activeMessages);
    const ad = Number(activeDays);
    const dd = Number(dormantDays);

    if (!Number.isInteger(pm) || pm <= 0) {
      return 'Power messages must be a positive integer';
    }
    if (!Number.isInteger(pd) || pd <= 0) {
      return 'Power days active must be a positive integer';
    }
    if (!Number.isInteger(am) || am <= 0) {
      return 'Active messages must be a positive integer';
    }
    if (!Number.isInteger(ad) || ad <= 0) {
      return 'Active days active must be a positive integer';
    }
    if (!Number.isInteger(dd) || dd <= 0) {
      return 'Dormant days threshold must be a positive integer';
    }
    if (pm <= am) {
      return 'Power messages must be greater than active messages';
    }
    if (pd <= ad) {
      return 'Power days active must be greater than active days active';
    }
    return null;
  };

  const handleSave = async () => {
    setError(null);
    setSuccess(null);

    const validationError = validate();
    if (validationError) {
      setError(t('engagement.settings.error.validation', { message: validationError }));
      return;
    }

    setSaving(true);
    try {
      const body = {
        power: { messages: Number(powerMessages), daysActive: Number(powerDays) },
        active: { messages: Number(activeMessages), daysActive: Number(activeDays) },
        dormantDaysThreshold: Number(dormantDays),
      };
      const resp = await put<{ status: string; message?: string }>('/api/config/engagement-thresholds', body);
      if (resp.status === 'error') {
        setError(resp.message ?? t('engagement.settings.error.save'));
      } else {
        setSuccess(t('engagement.settings.success'));
      }
    } catch {
      setError(t('engagement.settings.error.save'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <SkeletonLoader variant="container" />;
  }

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

      <Container
        header={
          <Header variant="h2" description={t('engagement.settings.description')}>
            {t('engagement.settings.title')}
          </Header>
        }
      >
        <SpaceBetween size="l">
          <Alert type="info" header={t('engagement.settings.help.title')}>
            <SpaceBetween size="xs">
              <div><Trans i18nKey="engagement.settings.help.volume" values={{ powerMessages, powerDays, activeMessages, activeDays }} components={{ strong: <strong /> }} /></div>
              <div><Trans i18nKey="engagement.settings.help.frequency" components={{ strong: <strong /> }} /></div>
            </SpaceBetween>
          </Alert>

          <Form
            actions={
              <Button variant="primary" onClick={handleSave} loading={saving}>
                {t('engagement.settings.save')}
              </Button>
            }
          >
            <SpaceBetween size="m">
              <FormField label={t('engagement.settings.powerMessages')}>
                <Input
                  type="number"
                  value={powerMessages}
                  onChange={({ detail }) => setPowerMessages(detail.value)}
                />
              </FormField>
              <FormField label={t('engagement.settings.powerDays')}>
                <Input
                  type="number"
                  value={powerDays}
                  onChange={({ detail }) => setPowerDays(detail.value)}
                />
              </FormField>
              <FormField label={t('engagement.settings.activeMessages')}>
                <Input
                  type="number"
                  value={activeMessages}
                  onChange={({ detail }) => setActiveMessages(detail.value)}
                />
              </FormField>
              <FormField label={t('engagement.settings.activeDays')}>
                <Input
                  type="number"
                  value={activeDays}
                  onChange={({ detail }) => setActiveDays(detail.value)}
                />
              </FormField>
              <FormField
                label={t('engagement.settings.dormantDays')}
                description={t('engagement.settings.dormantDays.description')}
              >
                <Input
                  type="number"
                  value={dormantDays}
                  onChange={({ detail }) => setDormantDays(detail.value)}
                />
              </FormField>
            </SpaceBetween>
          </Form>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );
}
