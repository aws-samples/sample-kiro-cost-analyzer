import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
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

export default function ForgotPasswordPage() {
  const { forgotPassword } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    setError(null);
    setLoading(true);
    try {
      await forgotPassword(email);
      navigate('/reset-password', { state: { email } });
    } catch (err: unknown) {
      const errorName = (err as { name?: string })?.name ?? '';
      switch (errorName) {
        case 'UserNotFoundException':
          // For security, still navigate to reset page to avoid account enumeration
          navigate('/reset-password', { state: { email } });
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
        <Container header={<Header variant="h1">{t('forgotPassword.title')}</Header>}>
          <Form
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="primary" loading={loading} onClick={handleSubmit}>
                  {t('forgotPassword.submit')}
                </Button>
              </SpaceBetween>
            }
          >
            <SpaceBetween size="l">
              {error && <Alert type="error">{error}</Alert>}

              <Box variant="p">
                {t('forgotPassword.description')}
              </Box>

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
