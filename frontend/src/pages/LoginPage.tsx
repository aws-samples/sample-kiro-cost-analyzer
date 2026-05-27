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
import logo from '../assets/logo.png';

export default function LoginPage() {
  const { login } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
    } catch (err: unknown) {
      const errorName = (err as { name?: string })?.name ?? '';
      switch (errorName) {
        case 'NotAuthorizedException':
        case 'UserNotFoundException':
          setError(t('login.error.invalidCredentials'));
          break;
        case 'UserNotConfirmedException':
          setError(t('login.error.notConfirmed'));
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
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--color-background-layout-main)' }}>
      <div style={{ maxWidth: 480, width: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <img
            src={logo}
            alt={t('brand.logoAlt')}
            style={{ maxWidth: '100%', height: 'auto', transform: 'scale(1.5)', transformOrigin: 'center', marginBottom: 24 }}
            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
          />
          <Box variant="h1" textAlign="center">{t('brand.productName')}</Box>
          <Box variant="p" color="text-body-secondary" textAlign="center">
            {t('login.tagline')}
          </Box>
        </div>
        <Container header={<Header variant="h1">{t('login.title')}</Header>}>
          <Form
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="primary" loading={loading} onClick={handleSubmit}>
                  {t('login.submit')}
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

              <SpaceBetween size="xs">
                <Box textAlign="center">
                  <Link onFollow={() => navigate('/forgot-password')}>{t('login.forgotPassword')}</Link>
                </Box>
              </SpaceBetween>
            </SpaceBetween>
          </Form>
        </Container>
      </div>
    </div>
  );
}
