import { useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import { useI18n } from '../i18n/useI18n';

function isValidUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
}

interface GitRepoFormProps {
  visible: boolean;
  onDismiss: () => void;
  onSubmit: (data: { name: string; url: string; provider: string; accessToken: string }) => Promise<void>;
}

export default function GitRepoForm({ visible, onDismiss, onSubmit }: GitRepoFormProps) {
  const { t } = useI18n();

  const PROVIDER_OPTIONS: SelectProps.Option[] = [
    { value: 'github', label: t('git.provider.github') },
  ];

  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [provider, setProvider] = useState<SelectProps.Option | null>(null);
  const [accessToken, setAccessToken] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [nameError, setNameError] = useState('');
  const [urlError, setUrlError] = useState('');
  const [providerError, setProviderError] = useState('');
  const [tokenError, setTokenError] = useState('');

  function resetForm() {
    setName(''); setUrl(''); setProvider(null); setAccessToken(''); setError(null);
    setNameError(''); setUrlError(''); setProviderError(''); setTokenError('');
  }

  function validate(): boolean {
    let valid = true;
    if (!name.trim()) { setNameError(t('gitRepoForm.field.name.error')); valid = false; } else { setNameError(''); }
    if (!url.trim()) { setUrlError(t('gitRepoForm.field.url.error.required')); valid = false; }
    else if (!isValidUrl(url.trim())) { setUrlError(t('gitRepoForm.field.url.error.invalid')); valid = false; }
    else { setUrlError(''); }
    if (!provider?.value) { setProviderError(t('gitRepoForm.field.provider.error')); valid = false; } else { setProviderError(''); }
    if (!accessToken.trim()) { setTokenError(t('gitRepoForm.field.token.error')); valid = false; } else { setTokenError(''); }
    return valid;
  }

  async function handleSubmit() {
    if (!validate()) return;
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ name: name.trim(), url: url.trim(), provider: provider!.value!, accessToken: accessToken.trim() });
      resetForm();
      onDismiss();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('gitRepoForm.error.generic'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      visible={visible}
      onDismiss={() => { resetForm(); onDismiss(); }}
      header={t('gitRepoForm.title')}
      footer={
        <Box float="right">
          <SpaceBetween size="xs" direction="horizontal">
            <Button variant="link" onClick={() => { resetForm(); onDismiss(); }}>{t('common.cancel')}</Button>
            <Button variant="primary" onClick={handleSubmit} loading={saving}>{t('gitRepoForm.submit')}</Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        {error && <Alert type="error">{error}</Alert>}
        <FormField label={t('gitRepoForm.field.name.label')} errorText={nameError}>
          <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder={t('gitRepoForm.field.name.placeholder')} />
        </FormField>
        <FormField label={t('gitRepoForm.field.url.label')} errorText={urlError}>
          <Input value={url} onChange={({ detail }) => setUrl(detail.value)} placeholder={t('gitRepoForm.field.url.placeholder')} />
        </FormField>
        <FormField label={t('gitRepoForm.field.provider.label')} errorText={providerError}>
          <Select
            selectedOption={provider}
            onChange={({ detail }) => setProvider(detail.selectedOption)}
            options={PROVIDER_OPTIONS}
            placeholder={t('gitRepoForm.field.provider.placeholder')}
          />
        </FormField>
        <FormField
          label={t('gitRepoForm.field.token.label')}
          errorText={tokenError}
          description={t('gitRepoForm.field.token.description')}
        >
          <Input value={accessToken} onChange={({ detail }) => setAccessToken(detail.value)} type="password" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}
