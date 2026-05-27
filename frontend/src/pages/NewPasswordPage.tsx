import { useState } from 'react';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Header from '@cloudscape-design/components/header';
import Input from '@cloudscape-design/components/input';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Alert from '@cloudscape-design/components/alert';
import { useAuth } from '../auth/useAuth';
import { useI18n } from '../i18n/useI18n';

export default function NewPasswordPage() {
  const { completeNewPassword, newPasswordEmail } = useAuth();
  const { t } = useI18n();

  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    setError(null);

    if (newPassword !== confirmPassword) {
      setError(t('auth.error.passwordMismatch'));
      return;
    }

    setLoading(true);
    try {
      await completeNewPassword(newPassword);
    } catch (err: unknown) {
      const errorName = (err as { name?: string })?.name ?? '';
      const errorMessage = (err as { message?: string })?.message ?? '';
      switch (errorName) {
        case 'InvalidPasswordException':
          setError(errorMessage);
          break;
        case 'LimitExceededException':
          setError(t('common.error.limitExceeded'));
          break;
        default:
          setError(errorMessage || t('newPassword.error.generic'));
          break;
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box padding={{ top: 'xxxl' }}>
      <div style={{ maxWidth: 400, margin: '0 auto' }}>
        <Container header={<Header variant="h1">{t('newPassword.title')}</Header>}>
          <Form
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="primary" loading={loading} onClick={handleSubmit}>
                  {t('newPassword.submit')}
                </Button>
              </SpaceBetween>
            }
          >
            <SpaceBetween size="l">
              {error && <Alert type="error">{error}</Alert>}

              <Alert type="info">
                {t('newPassword.firstAccess', { email: newPasswordEmail ?? '' })}
              </Alert>

              <FormField label={t('newPassword.newPassword')}>
                <Input
                  type="password"
                  value={newPassword}
                  onChange={({ detail }) => {
                    setNewPassword(detail.value);
                    setError(null);
                  }}
                  placeholder={t('newPassword.newPasswordPlaceholder')}
                />
              </FormField>

              <FormField label={t('newPassword.confirmPassword')}>
                <Input
                  type="password"
                  value={confirmPassword}
                  onChange={({ detail }) => {
                    setConfirmPassword(detail.value);
                    setError(null);
                  }}
                  placeholder={t('newPassword.confirmPasswordPlaceholder')}
                />
              </FormField>
            </SpaceBetween>
          </Form>
        </Container>
      </div>
    </Box>
  );
}
