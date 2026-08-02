import { useEffect, useState, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { type DateRangePickerProps } from '@cloudscape-design/components/date-range-picker';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import Toggle from '@cloudscape-design/components/toggle';
import Button from '@cloudscape-design/components/button';
import ButtonDropdown from '@cloudscape-design/components/button-dropdown';
import Alert from '@cloudscape-design/components/alert';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Link from '@cloudscape-design/components/link';
import Tabs from '@cloudscape-design/components/tabs';
import SummaryCards from '../components/SummaryCards';
import UsageTable from '../components/UsageTable';
import AccountSummaryCards from '../components/AccountSummaryCards';
import TimelineChart from '../components/TimelineChart';
import BreakdownCharts from '../components/BreakdownCharts';
import EngagementSegmentationWidget from '../components/EngagementSegmentationWidget';
import EngagementFunnelWidget from '../components/EngagementFunnelWidget';
import SkeletonLoader from '../components/SkeletonLoader';
import RecommendationsTab from '../components/RecommendationsTab';
import LocalizedDateRangePicker, { DEFAULT_DATE_RANGE } from '../components/LocalizedDateRangePicker';
import { useLastUpdated } from '../hooks/useLastUpdated';
import { useI18n } from '../i18n/useI18n';
import { get, ApiError } from '../api/client';
import type { UsageResponse, AccountUsageResponse, AppConfig } from '../types';
import type { TFunction } from 'i18next';

export interface EtlStatusDisplay {
  type: 'success' | 'error' | 'info' | 'stopped';
  text: string;
}

export function mapEtlStatus(status: string | null | undefined, t: TFunction): EtlStatusDisplay {
  switch (status) {
    case 'success':
      return { type: 'success', text: t('dashboard.etl.success') };
    case 'error':
    case 'failed':
      return { type: 'error', text: t('dashboard.etl.error') };
    case 'running':
    case 'in_progress':
      return { type: 'info', text: t('dashboard.etl.running') };
    default:
      return { type: 'stopped', text: t('dashboard.etl.noExecution') };
  }
}

type TabId = 'overview' | 'users' | 'recommendations';

function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getDateParams(dateRange: DateRangePickerProps.Value | null): Record<string, string> {
  const params: Record<string, string> = {};
  if (!dateRange) return params;
  if (dateRange.type === 'absolute') {
    params.startDate = dateRange.startDate;
    params.endDate = dateRange.endDate;
  } else if (dateRange.type === 'relative') {
    const now = new Date();
    const end = toDateStr(now);
    const start = new Date(now);
    const amount = dateRange.amount;
    switch (dateRange.unit) {
      case 'day': start.setDate(start.getDate() - amount); break;
      case 'week': start.setDate(start.getDate() - amount * 7); break;
      case 'month': start.setMonth(start.getMonth() - amount); break;
      case 'year': start.setFullYear(start.getFullYear() - amount); break;
    }
    params.startDate = toDateStr(start);
    params.endDate = end;
  }
  return params;
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTab = (searchParams.get('tab') as TabId) ?? 'overview';
  const setActiveTab = useCallback((id: TabId) => {
    setSearchParams((prev) => { prev.set('tab', id); return prev; }, { replace: true });
  }, [setSearchParams]);

  const TIER_OPTIONS: SelectProps.Option[] = [
    { value: '', label: t('dashboard.filter.allTiers') },
    { value: 'PRO', label: 'PRO' },
    { value: 'PRO_PLUS', label: 'PRO_PLUS' },
    { value: 'POWER', label: 'POWER' },
  ];

  const CLIENT_TYPE_OPTIONS: SelectProps.Option[] = [
    { value: '', label: t('dashboard.filter.allClientTypes') },
    { value: 'KIRO_IDE', label: 'KIRO_IDE' },
    { value: 'KIRO_CLI', label: 'KIRO_CLI' },
    { value: 'PLUGIN', label: 'PLUGIN' },
  ];

  const GRANULARITY_OPTIONS: SelectProps.Option[] = [
    { value: 'day', label: t('account.granularity.day') },
    { value: 'week', label: t('account.granularity.week') },
    { value: 'month', label: t('account.granularity.month') },
  ];

  // ── Shared state ─────────────────────────────────────────────────────────
  const [dateRange, setDateRange] = useState<DateRangePickerProps.Value | null>(DEFAULT_DATE_RANGE);
  const { formattedTime, markUpdated } = useLastUpdated();
  const [etlStatusDisplay, setEtlStatusDisplay] = useState<EtlStatusDisplay | null>(null);

  // ── Overview tab state ────────────────────────────────────────────────────
  const [granularity, setGranularity] = useState<SelectProps.Option>(GRANULARITY_OPTIONS[0]);
  const [accountData, setAccountData] = useState<AccountUsageResponse | undefined>();
  const [accountLoading, setAccountLoading] = useState(false);
  const [accountError, setAccountError] = useState<string | null>(null);
  const [accountServerError, setAccountServerError] = useState(false);

  // ── Users tab state ───────────────────────────────────────────────────────
  const [tier, setTier] = useState<SelectProps.Option>(TIER_OPTIONS[0]);
  const [clientType, setClientType] = useState<SelectProps.Option>(CLIENT_TYPE_OPTIONS[0]);
  const [overageOnly, setOverageOnly] = useState(false);
  const [usersData, setUsersData] = useState<UsageResponse | undefined>();
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [usersServerError, setUsersServerError] = useState(false);

  // ── Fetch: account overview ───────────────────────────────────────────────
  const fetchAccount = useCallback(async () => {
    setAccountLoading(true);
    setAccountError(null);
    setAccountServerError(false);
    try {
      const params = { ...getDateParams(dateRange), ...(granularity.value ? { granularity: granularity.value } : {}) };
      const resp = await get<AccountUsageResponse>('/api/usage/account', params);
      setAccountData(resp);
      markUpdated();
    } catch (err) {
      if (err instanceof ApiError && err.isServerError) {
        setAccountServerError(true);
        setAccountError(err.message);
      } else {
        setAccountError(err instanceof Error ? err.message : t('common.error.loadData'));
      }
    } finally {
      setAccountLoading(false);
    }
  }, [dateRange, granularity, markUpdated, t]);

  // ── Fetch: users ──────────────────────────────────────────────────────────
  const fetchUsers = useCallback(async () => {
    setUsersLoading(true);
    setUsersError(null);
    setUsersServerError(false);
    try {
      const params = { ...getDateParams(dateRange) } as Record<string, string>;
      if (tier.value) params.subscriptionTier = tier.value;
      if (clientType.value) params.clientType = clientType.value;
      if (overageOnly) params.overageOnly = 'true';
      const resp = await get<UsageResponse>('/api/usage', params);
      setUsersData(resp);
      markUpdated();
    } catch (err) {
      if (err instanceof ApiError && err.isServerError) {
        setUsersServerError(true);
        setUsersError(err.message);
      } else {
        setUsersError(err instanceof Error ? err.message : t('common.error.loadData'));
      }
    } finally {
      setUsersLoading(false);
    }
  }, [dateRange, tier, clientType, overageOnly, markUpdated, t]);

  // ── Initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    fetchAccount();
    fetchUsers();

    get<AppConfig>('/api/config')
      .then((resp) => setEtlStatusDisplay(mapEtlStatus(resp.etlStatus?.status, t)))
      .catch(() => {});
  }, [fetchAccount, fetchUsers, t]);

  // ── Export ────────────────────────────────────────────────────────────────
  const handleExport = async (format: string) => {
    try {
      const params = { ...getDateParams(dateRange), format } as Record<string, string>;
      if (tier.value) params.subscriptionTier = tier.value;
      if (clientType.value) params.clientType = clientType.value;
      if (overageOnly) params.overageOnly = 'true';

      const resp = await get<string | object>('/api/usage/export', params);
      const content = format === 'csv' ? (resp as string) : JSON.stringify(resp, null, 2);
      const blob = new Blob([content], {
        type: format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `usage-export.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setUsersError(t('dashboard.export.error'));
    }
  };

  // ── Tab content ───────────────────────────────────────────────────────────
  const overviewTabContent = (
    <SpaceBetween size="l">
      {accountError && (
        <Alert type="error" dismissible onDismiss={() => setAccountError(null)}
          action={accountServerError ? <Button onClick={fetchAccount}>{t('common.retry')}</Button> : undefined}>
          {accountError}
        </Alert>
      )}

      {accountLoading && !accountData ? (
        <SpaceBetween size="l">
          <SkeletonLoader variant="cards" count={4} columns={4} />
          <SkeletonLoader variant="chart" height={300} />
          <SkeletonLoader variant="chart" height={300} />
        </SpaceBetween>
      ) : (
        <SpaceBetween size="l">
          <AccountSummaryCards totals={accountData?.totals} loading={accountLoading} />

          <SpaceBetween size="s" direction="horizontal" alignItems="end">
            <div style={{ minWidth: 150 }}>
              <Select
                selectedOption={granularity}
                onChange={({ detail }) => setGranularity(detail.selectedOption)}
                options={GRANULARITY_OPTIONS}
                placeholder={t('account.granularity.placeholder')}
              />
            </div>
            <Button iconName="refresh" onClick={fetchAccount} loading={accountLoading}>
              {t('common.refresh')}
            </Button>
          </SpaceBetween>

          <TimelineChart timeline={accountData?.timeline ?? []} loading={accountLoading} />
          <BreakdownCharts
            tierBreakdown={accountData?.breakdownByTier ?? []}
            clientTypeBreakdown={accountData?.breakdownByClientType ?? []}
            loading={accountLoading}
          />
          <EngagementSegmentationWidget dateParams={getDateParams(dateRange)} />
          <EngagementFunnelWidget dateParams={getDateParams(dateRange)} />
        </SpaceBetween>
      )}
    </SpaceBetween>
  );

  const usersTabContent = (
    <SpaceBetween size="l">
      {usersError && (
        <Alert type="error" dismissible onDismiss={() => setUsersError(null)}
          action={usersServerError ? <Button onClick={fetchUsers}>{t('common.retry')}</Button> : undefined}>
          {usersError}
        </Alert>
      )}

      {usersLoading && !usersData ? (
        <SpaceBetween size="l">
          <SkeletonLoader variant="cards" count={4} columns={4} />
          <SkeletonLoader variant="table" count={5} />
        </SpaceBetween>
      ) : (
        <SpaceBetween size="l">
          <SummaryCards summary={usersData?.summary} loading={usersLoading} />

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
            <div style={{ minWidth: 160 }}>
              <Select
                selectedOption={tier}
                onChange={({ detail }) => setTier(detail.selectedOption)}
                options={TIER_OPTIONS}
                placeholder={t('dashboard.filter.subscriptionTier')}
              />
            </div>
            <div style={{ minWidth: 160 }}>
              <Select
                selectedOption={clientType}
                onChange={({ detail }) => setClientType(detail.selectedOption)}
                options={CLIENT_TYPE_OPTIONS}
                placeholder={t('dashboard.filter.clientType')}
              />
            </div>
            <Toggle checked={overageOnly} onChange={({ detail }) => setOverageOnly(detail.checked)}>
              {t('dashboard.filter.overageOnly')}
            </Toggle>
            <SpaceBetween size="xs" direction="horizontal">
              <Button iconName="refresh" onClick={fetchUsers} loading={usersLoading}>
                {t('common.refresh')}
              </Button>
              <ButtonDropdown
                items={[
                  { id: 'csv', text: t('dashboard.export.csv') },
                  { id: 'json', text: t('dashboard.export.json') },
                ]}
                onItemClick={({ detail }) => handleExport(detail.id)}
              >
                {t('dashboard.export.button')}
              </ButtonDropdown>
            </SpaceBetween>
          </div>

          <UsageTable users={usersData?.users ?? []} loading={usersLoading} />
        </SpaceBetween>
      )}
    </SpaceBetween>
  );

  return (
    <SpaceBetween size="l">
      <Header
        variant="h1"
        description={formattedTime ? t('common.lastUpdated', { time: formattedTime }) : undefined}
        actions={
          <SpaceBetween size="s" direction="horizontal" alignItems="center">
            {etlStatusDisplay && (
              <Link href="/admin" onFollow={(e) => { e.preventDefault(); navigate('/admin'); }}>
                <StatusIndicator type={etlStatusDisplay.type}>
                  {etlStatusDisplay.text}
                </StatusIndicator>
              </Link>
            )}
            <div style={{ minWidth: 280 }}>
              <LocalizedDateRangePicker
                value={dateRange}
                onChange={(value) => setDateRange(value)}
              />
            </div>
          </SpaceBetween>
        }
      >
        {t('nav.dashboard')}
      </Header>

      <Tabs
        activeTabId={activeTab}
        onChange={({ detail }) => setActiveTab(detail.activeTabId as TabId)}
        tabs={[
          {
            id: 'overview',
            label: t('dashboard.tab.overview'),
            content: overviewTabContent,
          },
          {
            id: 'users',
            label: t('dashboard.tab.users'),
            content: usersTabContent,
          },
          {
            id: 'recommendations',
            label: t('recommendations.tab.title'),
            content: <RecommendationsTab dateParams={getDateParams(dateRange)} />,
          },
        ]}
      />
    </SpaceBetween>
  );
}
