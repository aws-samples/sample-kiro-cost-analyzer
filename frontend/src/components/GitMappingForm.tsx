import { useState } from 'react';
import FormField from '@cloudscape-design/components/form-field';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Alert from '@cloudscape-design/components/alert';
import { useI18n } from '../i18n/useI18n';

interface GitMappingFormProps {
  userOptions: SelectProps.Option[];
  onSubmit: (data: { userId: string; provider: string; gitUsername: string }) => Promise<void>;
}

export default function GitMappingForm({ userOptions, onSubmit }: GitMappingFormProps) {
  const { t } = useI18n();

  const PROVIDER_OPTIONS: SelectProps.Option[] = [
    { value: 'github', label: t('git.provider.github') },
  ];

  const [selectedUser, setSelectedUser] = useState<SelectProps.Option | null>(null);
  const [provider, setProvider] = useState<SelectProps.Option | null>(null);
  const [gitUsername, setGitUsername] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [userError, setUserError] = useState('');
  const [providerError, setProviderError] = useState('');
  const [usernameError, setUsernameError] = useState('');

  function validate(): boolean {
    let valid = true;
    if (!selectedUser?.value) { setUserError(t('gitMappingForm.field.user.error')); valid = false; } else { setUserError(''); }
    if (!provider?.value) { setProviderError(t('gitMappingForm.field.provider.error')); valid = false; } else { setProviderError(''); }
    if (!gitUsername.trim()) { setUsernameError(t('gitMappingForm.field.gitUsername.error')); valid = false; } else { setUsernameError(''); }
    return valid;
  }

  async function handleSubmit() {
    if (!validate()) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await onSubmit({ userId: selectedUser!.value!, provider: provider!.value!, gitUsername: gitUsername.trim() });
      setSelectedUser(null);
      setProvider(null);
      setGitUsername('');
      setSuccess(t('gitMappingForm.success'));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('gitMappingForm.error.generic'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <SpaceBetween size="s">
      {error && <Alert type="error" dismissible onDismiss={() => setError(null)}>{error}</Alert>}
      {success && <Alert type="success" dismissible onDismiss={() => setSuccess(null)}>{success}</Alert>}
      <SpaceBetween size="s" direction="horizontal" alignItems="end">
        <FormField label={t('gitMappingForm.field.user.label')} errorText={userError}>
          <div style={{ minWidth: 220 }}>
            <Select
              selectedOption={selectedUser}
              onChange={({ detail }) => setSelectedUser(detail.selectedOption)}
              options={userOptions}
              placeholder={t('gitMappingForm.field.user.placeholder')}
              filteringType="auto"
            />
          </div>
        </FormField>
        <FormField label={t('gitMappingForm.field.provider.label')} errorText={providerError}>
          <div style={{ minWidth: 160 }}>
            <Select
              selectedOption={provider}
              onChange={({ detail }) => setProvider(detail.selectedOption)}
              options={PROVIDER_OPTIONS}
              placeholder={t('gitMappingForm.field.provider.placeholder')}
            />
          </div>
        </FormField>
        <FormField label={t('gitMappingForm.field.gitUsername.label')} errorText={usernameError}>
          <Input
            value={gitUsername}
            onChange={({ detail }) => setGitUsername(detail.value)}
            placeholder={t('gitMappingForm.field.gitUsername.placeholder')}
          />
        </FormField>
        <Button variant="primary" onClick={handleSubmit} loading={saving}>
          {t('gitMappingForm.submit')}
        </Button>
      </SpaceBetween>
    </SpaceBetween>
  );
}
