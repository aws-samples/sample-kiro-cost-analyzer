import { useEffect, useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import { useI18n } from '../i18n/useI18n';
import { useAuth } from '../auth/useAuth';
import { get } from '../api/client';
import type { UsageResponse } from '../types';

export default function ProductivityPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [users, setUsers] = useState<{ value: string; label: string }[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);

  const isAdmin = user?.groups?.includes('Admins') ?? false;

  useEffect(() => {
    // Non-admins: redirect directly to their own productivity tab
    if (!isAdmin && user?.sub) {
      // Fetch the Kiro userId (Identity Center) mapped to this Cognito user
      get<{ kiroUserId: string | null }>('/api/me')
        .then((me) => {
          const targetUserId = me.kiroUserId || user.sub;
          navigate(`/user/${targetUserId}?tab=productivity`, { replace: true });
        })
        .catch(() => {
          navigate(`/user/${user.sub}?tab=productivity`, { replace: true });
        });
      return;
    }

    async function loadUsers() {
      setUsersLoading(true);
      try {
        const resp = await get<UsageResponse>('/api/usage', { limit: '50' });
        setUsers(resp.users.map((u) => ({
          value: u.userId,
          label: u.displayName || u.userName || u.userId,
        })));
      } catch {
        // silently fail
      } finally {
        setUsersLoading(false);
      }
    }
    loadUsers();
  }, [isAdmin, user, navigate]);

  const handleUserChange = useCallback((opt: SelectProps.Option | null) => {
    if (opt?.value) {
      navigate(`/user/${opt.value}?tab=productivity`);
    }
  }, [navigate]);

  const userOptions = useMemo<SelectProps.Options>(() => users, [users]);

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description={t('productivity.header.description')}
        >
          {t('productivity.header.title')}
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Box>
          <Select
            selectedOption={null}
            onChange={({ detail }) => handleUserChange(detail.selectedOption?.value ? detail.selectedOption : null)}
            options={userOptions}
            placeholder={t('productivity.user.placeholder')}
            filteringType="auto"
            loadingText={t('productivity.user.loading')}
            statusType={usersLoading ? 'loading' : 'finished'}
          />
        </Box>

        <Box textAlign="center" padding="xxl" color="text-status-inactive">
          <Box variant="h2">{t('productivity.empty.title')}</Box>
          <Box variant="p" padding={{ top: 's' }}>
            {t('productivity.empty.description')}
          </Box>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
