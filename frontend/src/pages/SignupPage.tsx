import { useState } from 'react';
import { useNavigate } from 'react-router';
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

export default function SignupPage() {
  const { signup, confirmSignup } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<'signup' | 'confirm'>('signup');

  const handleSignup = async () => {
    setError(null);

    if (password !== confirmPassword) {
      setError(t('auth.error.passwordMismatch'));
      return;
    }

    setLoading(true);
    try {
      await signup(email, password);
      setStep('confirm');
    } catch (err: unknown) {
      const errorName = (err as { name?: string })?.name ?? '';
      const errorMessage = (err as { message?: string })?.message ?? '';
      switch (errorName) {
        case 'UsernameExistsException':
          setError(t('signup.error.emailExists'));
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

  const handleConfirm = async () => {
    setError(null);
    setLoading(true);
    try {
      await confirmSignup(email, verificationCode);
      navigate('/login', { state: { success: t('signup.success') } });
    } catch (err: unknown) {
      const errorName = (err as { name?: string })?.name ?? '';
      switch (errorName) {
        case 'CodeMismatchException':
          setError(t('auth.error.invalidCode'));
          break;
        case 'ExpiredCodeException':
          setError(t('auth.error.expiredCode'));
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
        {step === 'signup' ? (
          <Container header={<Header variant="h1">{t('signup.title')}</Header>}>
            <Form
              actions={
                <SpaceBetween direction="horizontal" size="xs">
                  <Button variant="primary" loading={loading} onClick={handleSignup}>
                    {t('signup.submit')}
                  </Button>
                </SpaceBetween>
              }
            >
              <SpaceBetween size="l">
                {error && <Alert type="error">{error}</Alert>}

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

                <FormField label={t('login.password')}>
                  <Input
                    type="password"
                    value={password}
                    onChange={({ detail }) => {
                      setPassword(detail.value);
                      setError(null);
                    }}
                    placeholder={t('login.passwordPlaceholder')}
                  />
                </FormField>

                <FormField label={t('signup.confirmPassword')}>
                  <Input
                    type="password"
                    value={confirmPassword}
                    onChange={({ detail }) => {
                      setConfirmPassword(detail.value);
                      setError(null);
                    }}
                    placeholder={t('signup.confirmPasswordPlaceholder')}
                  />
                </FormField>

                <Box textAlign="center">
                  <Link onFollow={() => navigate('/login')}>{t('auth.backToLogin')}</Link>
                </Box>
              </SpaceBetween>
            </Form>
          </Container>
        ) : (
          <Container header={<Header variant="h1">{t('signup.verify.title')}</Header>}>
            <Form
              actions={
                <SpaceBetween direction="horizontal" size="xs">
                  <Button variant="primary" loading={loading} onClick={handleConfirm}>
                    {t('common.confirm')}
                  </Button>
                </SpaceBetween>
              }
            >
              <SpaceBetween size="l">
                {error && <Alert type="error">{error}</Alert>}

                <Alert type="info">
                  {t('signup.verify.codeSent', { email })}
                </Alert>

                <FormField label={t('resetPassword.code')}>
                  <Input
                    value={verificationCode}
                    onChange={({ detail }) => {
                      setVerificationCode(detail.value);
                      setError(null);
                    }}
                    placeholder={t('signup.verify.codePlaceholder')}
                  />
                </FormField>

                <Box textAlign="center">
                  <Link onFollow={() => navigate('/login')}>{t('auth.backToLogin')}</Link>
                </Box>
              </SpaceBetween>
            </Form>
          </Container>
        )}
      </div>
    </Box>
  );
}
