import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Header from '@cloudscape-design/components/header';
import Input from '@cloudscape-design/components/input';
import Link from '@cloudscape-design/components/link';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Alert from '@cloudscape-design/components/alert';
import { useAuth } from '../auth/useAuth';
import { useI18n } from '../i18n/useI18n';

export default function ResetPasswordPage() {
  const { resetPassword } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();

  const emailFromState = (location.state as { email?: string })?.email ?? '';

  const [email, setEmail] = useState(emailFromState);
  const [code, setCode] = useState('');
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
      await resetPassword(email, code, newPassword);
      navigate('/login', { state: { success: t('resetPassword.success') } });
    } catch (err: unknown) {
      const errorName = (err as { name?: string })?.name ?? '';
      const errorMessage = (err as { message?: string })?.message ?? '';
      switch (errorName) {
        case 'CodeMismatchException':
          setError(t('auth.error.invalidCode'));
          break;
        case 'ExpiredCodeException':
          setError(t('auth.error.expiredCode'));
          break;
        case 'InvalidPasswordException':
          setError(errorMessage);
          break;
        case 'LimitExceededException':
          setError(t('common.error.limitExceeded'));
          break;
        default:
          setError(t('common.error.connection'));
          break;
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box padding={{ top: 'xxxl' }}>
      <div style={{ maxWidth: 400, margin: '0 auto' }}>
        <Container header={<Header variant="h1">{t('resetPassword.title')}</Header>}>
          <Form
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="primary" loading={loading} onClick={handleSubmit}>
                  {t('resetPassword.submit')}
                </Button>
              </SpaceBetween>
            }
          >
            <SpaceBetween size="l">
              {error && <Alert type="error">{error}</Alert>}

              {!emailFromState && (
                <FormField label={t('login.email')}>
                  <Input
                    type="email"
                    value={email}
                    onChange={({ detail }) => {
                      setEmail(detail.value);
                      setError(null);
                    }}
                    placeholder={t('login.emailPlaceholder')}
                  />
                </FormField>
              )}

              <FormField label={t('resetPassword.code')}>
                <Input
                  value={code}
                  onChange={({ detail }) => {
                    setCode(detail.value);
                    setError(null);
                  }}
                  placeholder={t('resetPassword.codePlaceholder')}
                />
              </FormField>

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

              <Box textAlign="center">
                <Link onFollow={() => navigate('/login')}>{t('auth.backToLogin')}</Link>
              </Box>
            </SpaceBetween>
          </Form>
        </Container>
      </div>
    </Box>
  );
}
