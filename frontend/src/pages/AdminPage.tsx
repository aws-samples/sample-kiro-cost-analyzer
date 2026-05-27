import { useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Tabs from '@cloudscape-design/components/tabs';
import Alert from '@cloudscape-design/components/alert';
import { useAuth } from '../auth/useAuth';
import { useI18n } from '../i18n/useI18n';
import UsersPage from './UsersPage';
import SettingsPage from './SettingsPage';
import GitSettingsPage from './GitSettingsPage';
const TAB_IDS = ['users', 'settings', 'git'] as const;
type TabId = typeof TAB_IDS[number];

function isValidTab(id: string): id is TabId {
  return (TAB_IDS as readonly string[]).includes(id);
}

export default function AdminPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const isAdmin = user?.groups?.includes('Admins') ?? false;

  // Derive active tab from ?tab= query param, default to 'users'
  const params = new URLSearchParams(location.search);
  const tabParam = params.get('tab') ?? '';
  const activeTab: TabId = isValidTab(tabParam) ? tabParam : 'settings';

  // Redirect to canonical URL if tab param is missing or invalid
  useEffect(() => {
    if (!isValidTab(tabParam)) {
      navigate('/admin?tab=settings', { replace: true });
    }
  }, [tabParam, navigate]);

  if (!isAdmin) {
    return (
      <ContentLayout header={<Header variant="h1">{t('admin.title')}</Header>}>
        <Alert type="error">{t('admin.restricted')}</Alert>
      </ContentLayout>
    );
  }

  function handleTabChange(tabId: string) {
    navigate(`/admin?tab=${tabId}`);
  }

  return (
    <ContentLayout header={<Header variant="h1">{t('admin.title')}</Header>}>
      <Tabs
        activeTabId={activeTab}
        onChange={({ detail }) => handleTabChange(detail.activeTabId)}
        tabs={[
          {
            id: 'settings',
            label: t('admin.tabs.settings'),
            content: <SettingsPage />,
          },
          {
            id: 'users',
            label: t('admin.tabs.users'),
            content: <UsersPage />,
          },
          {
            id: 'git',
            label: t('admin.tabs.git'),
            content: <GitSettingsPage />,
          },
        ]}
      />
    </ContentLayout>
  );
}
