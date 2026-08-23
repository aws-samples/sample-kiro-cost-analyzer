import { useEffect, useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import { useI18n } from '../i18n/useI18n';
import { buildProviderOptions } from '../constants/gitProviders';
import { validateGitToken } from '../api/gitApi';
import GitTokenValidationModal from './GitTokenValidationModal';
import type { GitRepository, GitTokenValidation } from '../types';

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
  /**
   * When set, the form opens in edit mode prefilled with this repository.
   * In edit mode the token field is optional — a blank token means "keep
   * the current token" (the page omits accessToken from the PATCH body).
   */
  editTarget?: GitRepository | null;
}

export default function GitRepoForm({ visible, onDismiss, onSubmit, editTarget }: GitRepoFormProps) {
  const { t } = useI18n();

  const PROVIDER_OPTIONS: SelectProps.Option[] = buildProviderOptions(t);
  const isEdit = editTarget != null;

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

  // Permission validation is deliberately separate from submit: validating
  // never saves, and saving never silently validates.
  const [validating, setValidating] = useState(false);
  const [validationOk, setValidationOk] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<GitTokenValidation | null>(null);

  const canValidate =
    url.trim().length > 0 && !!provider?.value && accessToken.trim().length > 0;

  function resetValidation() {
    setValidating(false);
    setValidationOk(false);
    setValidationError(null);
    setValidationResult(null);
  }

  async function handleValidate() {
    if (!canValidate || validating) return;
    setValidating(true);
    setValidationOk(false);
    setValidationError(null);
    setValidationResult(null);
    try {
      const result = await validateGitToken({
        url: url.trim(),
        provider: provider!.value!,
        accessToken: accessToken.trim(),
      });
      if (result.overall === 'ok') {
        setValidationOk(true);
      } else {
        setValidationResult(result);
      }
    } catch (err) {
      setValidationError(
        err instanceof Error ? err.message : t('gitTokenValidation.error.generic'),
      );
    } finally {
      setValidating(false);
    }
  }

  // Prefill in edit mode; token is always collected fresh (never echoed).
  useEffect(() => {
    if (visible && editTarget) {
      setName(editTarget.name);
      setUrl(editTarget.url);
      setProvider(PROVIDER_OPTIONS.find((o) => o.value === editTarget.provider) ?? null);
      setAccessToken('');
      setError(null);
      setNameError(''); setUrlError(''); setProviderError(''); setTokenError('');
      resetValidation();
    }
    // PROVIDER_OPTIONS is rebuilt per render from t(); keying the effect on
    // the target identity + visibility is sufficient for prefill.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, editTarget]);

  function resetForm() {
    setName(''); setUrl(''); setProvider(null); setAccessToken(''); setError(null);
    setNameError(''); setUrlError(''); setProviderError(''); setTokenError('');
    resetValidation();
  }

  function validate(): boolean {
    let valid = true;
    if (!name.trim()) { setNameError(t('gitRepoForm.field.name.error')); valid = false; } else { setNameError(''); }
    if (!url.trim()) { setUrlError(t('gitRepoForm.field.url.error.required')); valid = false; }
    else if (!isValidUrl(url.trim())) { setUrlError(t('gitRepoForm.field.url.error.invalid')); valid = false; }
    else { setUrlError(''); }
    if (!provider?.value) { setProviderError(t('gitRepoForm.field.provider.error')); valid = false; } else { setProviderError(''); }
    // Token is required only when creating; in edit mode blank = keep current.
    if (!isEdit && !accessToken.trim()) { setTokenError(t('gitRepoForm.field.token.error')); valid = false; } else { setTokenError(''); }
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
      setError(err instanceof Error ? err.message : t(isEdit ? 'gitRepoForm.error.update' : 'gitRepoForm.error.generic'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      visible={visible}
      onDismiss={() => { resetForm(); onDismiss(); }}
      header={t(isEdit ? 'gitRepoForm.editTitle' : 'gitRepoForm.title')}
      footer={
        <Box float="right">
          <SpaceBetween size="xs" direction="horizontal">
            <Button variant="link" onClick={() => { resetForm(); onDismiss(); }}>{t('common.cancel')}</Button>
            <Button variant="primary" onClick={handleSubmit} loading={saving}>{t(isEdit ? 'gitRepoForm.submitEdit' : 'gitRepoForm.submit')}</Button>
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
          description={t(isEdit ? 'gitRepoForm.field.token.editDescription' : 'gitRepoForm.field.token.description')}
        >
          <Input value={accessToken} onChange={({ detail }) => { setAccessToken(detail.value); resetValidation(); }} type="password" />
        </FormField>
        <SpaceBetween size="xs">
          <Button
            variant="normal"
            onClick={handleValidate}
            loading={validating}
            disabled={!canValidate}
          >
            {t('gitTokenValidation.button.validate')}
          </Button>
          {validationOk && (
            <StatusIndicator type="success">
              {t('gitTokenValidation.summary.ok')}
            </StatusIndicator>
          )}
          {validationError && <Alert type="error">{validationError}</Alert>}
        </SpaceBetween>
      </SpaceBetween>
      <GitTokenValidationModal
        result={validationResult}
        onDismiss={() => setValidationResult(null)}
      />
    </Modal>
  );
}
