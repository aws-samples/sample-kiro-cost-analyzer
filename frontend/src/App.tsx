import { useState } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import AppLayout from '@cloudscape-design/components/app-layout';
import SideNavigation, { type SideNavigationProps } from '@cloudscape-design/components/side-navigation';
import TopNavigation from '@cloudscape-design/components/top-navigation';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import { AuthProvider } from './auth/AuthProvider';
import { useAuth } from './auth/useAuth';
import { SplitPanelProvider, useSplitPanel } from './hooks/useSplitPanel';
import { useI18n } from './i18n/useI18n';
import { useUserSettingsMenu } from './components/UserSettingsMenu';
import DashboardPage from './pages/DashboardPage';
import UserPage from './pages/UserPage';
import LoginPage from './pages/LoginPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import NewPasswordPage from './pages/NewPasswordPage';
import ProductivityPage from './pages/ProductivityPage';
import AdminPage from './pages/AdminPage';

function AppContent() {
  const { isAuthenticated, loading, logout, user, newPasswordRequired } = useAuth();
  const { t } = useI18n();
  const isAdmin = user?.groups?.includes('Admins') ?? false;
  // Renders the gear-icon utility for the TopNavigation and the modal it
  // opens. The utility is spread into `utilities` below; the modal node
  // is rendered once as a sibling of the TopNavigation so it lives at
  // the top of the tree.
  const settingsMenu = useUserSettingsMenu();

  const overviewSection: SideNavigationProps.Item = {
    type: 'section',
    text: t('nav.section.overview'),
    items: [
      { type: 'link', text: t('nav.dashboard'), href: '/' },
    ],
  };

  const usersSection: SideNavigationProps.Item = {
    type: 'section',
    text: t('nav.section.users'),
    items: [
      { type: 'link', text: t('nav.productivity'), href: '/productivity' },
    ],
  };

  const adminSection: SideNavigationProps.Item = {
    type: 'section',
    text: t('nav.section.administration'),
    items: [
      { type: 'link', text: t('nav.section.administration'), href: '/admin' },
    ],
  };

  const navItems: SideNavigationProps.Item[] = isAdmin
    ? [overviewSection, usersSection, adminSection]
    : [overviewSection, usersSection];
  const navigate = useNavigate();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(true);
  const { splitPanelContent, splitPanelOpen, setSplitPanelOpen, closeSplitPanel } = useSplitPanel();

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (newPasswordRequired) {
    return <NewPasswordPage />;
  }

  if (!isAuthenticated) {
    // Render a minimal top bar carrying just the settings gear icon so
    // users on the login / password-reset flows can still pick a locale
    // and theme before authenticating (Requirement 3.1: switcher
    // reachable for every user).
    return (
      <>
        <div id="top-nav">
          <TopNavigation
            identity={{ title: t('brand.productName'), href: '/' }}
            utilities={[settingsMenu.utility]}
          />
        </div>
        {settingsMenu.modalNode}
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </>
    );
  }

  return (
    <>
      <div id="top-nav">
        <TopNavigation
          identity={{ title: t('brand.productName'), href: '/' }}
          utilities={[
            // Gear icon opens the user settings modal (language + visual mode).
            settingsMenu.utility,
            // User email dropdown with sign-out.
            {
              type: 'menu-dropdown',
              text: user?.email ?? '',
              iconName: 'user-profile',
              items: [{ id: 'signout', text: t('nav.signout') }],
              onItemClick: () => logout(),
            },
          ]}
        />
      </div>
      {settingsMenu.modalNode}
      <AppLayout
        navigation={
          <SideNavigation
            activeHref={location.pathname}
            items={navItems}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
        }
        navigationOpen={navOpen}
        onNavigationChange={({ detail }) => setNavOpen(detail.open)}
        toolsHide
        splitPanel={splitPanelContent ?? undefined}
        splitPanelOpen={splitPanelOpen}
        onSplitPanelToggle={({ detail }) => {
          if (!detail.open) {
            closeSplitPanel();
          } else {
            setSplitPanelOpen(true);
          }
        }}
        content={
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/account" element={<Navigate to="/?tab=overview" replace />} />
            <Route path="/user/:userId" element={<UserPage />} />
            <Route path="/productivity" element={<ProductivityPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        }
      />
    </>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <SplitPanelProvider>
        <AppContent />
      </SplitPanelProvider>
    </AuthProvider>
  );
}
