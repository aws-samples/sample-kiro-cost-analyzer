import { useEffect, useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Table from '@cloudscape-design/components/table';
import Link from '@cloudscape-design/components/link';
import { useI18n } from '../i18n/useI18n';
import { useAuth } from '../auth/useAuth';
import { get } from '../api/client';
import type { UsageResponse, UserUsage } from '../types';

/** Number of users shown in the default activity ranking (issue #17). */
const RANKING_SIZE = 10;

export default function ProductivityPage() {
  const { t, formatNumber, formatDate } = useI18n();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [users, setUsers] = useState<UserUsage[]>([]);
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
        setUsers(resp.users);
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

  const userLabel = useCallback(
    (u: UserUsage) =>
      u.displayName || u.userName || t('common.unidentifiedUser', { id: u.userId.slice(0, 8) }),
    [t],
  );

  const userOptions = useMemo<SelectProps.Options>(
    () => users.map((u) => ({ value: u.userId, label: userLabel(u) })),
    [users, userLabel],
  );

  // Top users by total credits — reuses the data already fetched for the
  // selector, so the page shows an overview instead of an empty state
  // (issue #17 / design critique F2). No extra API call.
  const ranking = useMemo(
    () => [...users].sort((a, b) => b.totalCredits - a.totalCredits).slice(0, RANKING_SIZE),
    [users],
  );

  const fmt = (n: number) =>
    formatNumber(n, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

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

        <Table
          loading={usersLoading}
          loadingText={t('productivity.user.loading')}
          header={
            <Header
              variant="h2"
              counter={`(${ranking.length})`}
              description={t('productivity.ranking.description')}
            >
              {t('productivity.ranking.title')}
            </Header>
          }
          columnDefinitions={[
            {
              id: 'rank',
              header: t('productivity.ranking.header.rank'),
              cell: (item) => ranking.indexOf(item) + 1,
              width: 80,
            },
            {
              id: 'user',
              header: t('productivity.ranking.header.user'),
              cell: (item) => (
                <Link
                  href={`/user/${item.userId}?tab=productivity`}
                  onFollow={(e) => {
                    e.preventDefault();
                    navigate(`/user/${item.userId}?tab=productivity`);
                  }}
                >
                  {userLabel(item)}
                </Link>
              ),
            },
            {
              id: 'credits',
              header: t('productivity.ranking.header.credits'),
              cell: (item) => fmt(item.totalCredits),
              width: 140,
            },
            {
              id: 'messages',
              header: t('productivity.ranking.header.messages'),
              cell: (item) => formatNumber(item.totalMessages),
              width: 130,
            },
            {
              id: 'avgDaily',
              header: t('productivity.ranking.header.avgDaily'),
              cell: (item) => fmt(item.averageDailyCredits),
              width: 150,
            },
            {
              id: 'lastActive',
              header: t('productivity.ranking.header.lastActive'),
              cell: (item) => (item.lastActiveDate ? formatDate(item.lastActiveDate, { timeZone: 'UTC' }) : '—'),
              width: 140,
            },
          ]}
          items={ranking}
          trackBy="userId"
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              {t('productivity.ranking.empty')}
            </Box>
          }
        />
      </SpaceBetween>
    </ContentLayout>
  );
}
