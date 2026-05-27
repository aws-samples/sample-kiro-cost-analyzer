import { useEffect, useState, useCallback } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { type DateRangePickerProps } from '@cloudscape-design/components/date-range-picker';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import AccountSummaryCards from '../components/AccountSummaryCards';
import TimelineChart from '../components/TimelineChart';
import BreakdownCharts from '../components/BreakdownCharts';
import SkeletonLoader from '../components/SkeletonLoader';
import LocalizedDateRangePicker, { DEFAULT_DATE_RANGE } from '../components/LocalizedDateRangePicker';
import { useLastUpdated } from '../hooks/useLastUpdated';
import { useI18n } from '../i18n/useI18n';
import { get, ApiError } from '../api/client';
import type { AccountUsageResponse } from '../types';

function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export default function AccountUsagePage() {
  const { t } = useI18n();

  const GRANULARITY_OPTIONS: SelectProps.Option[] = [
    { value: 'day', label: t('account.granularity.day') },
    { value: 'week', label: t('account.granularity.week') },
    { value: 'month', label: t('account.granularity.month') },
  ];

  const [dateRange, setDateRange] = useState<DateRangePickerProps.Value | null>(DEFAULT_DATE_RANGE);
  const [granularity, setGranularity] = useState<SelectProps.Option>(GRANULARITY_OPTIONS[0]);
  const [data, setData] = useState<AccountUsageResponse | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isServerError, setIsServerError] = useState(false);
  const { formattedTime, markUpdated } = useLastUpdated();

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setIsServerError(false);
    try {
      const params: Record<string, string> = {};

      if (granularity.value) {
        params.granularity = granularity.value;
      }

      if (dateRange) {
        if (dateRange.type === 'absolute') {
          params.startDate = dateRange.startDate;
          params.endDate = dateRange.endDate;
        } else if (dateRange.type === 'relative') {
          const now = new Date();
          const end = toDateStr(now);
          const start = new Date(now);
          const amount = dateRange.amount;
          switch (dateRange.unit) {
            case 'day':
              start.setDate(start.getDate() - amount);
              break;
            case 'week':
              start.setDate(start.getDate() - amount * 7);
              break;
            case 'month':
              start.setMonth(start.getMonth() - amount);
              break;
            case 'year':
              start.setFullYear(start.getFullYear() - amount);
              break;
          }
          params.startDate = toDateStr(start);
          params.endDate = end;
        }
      }

      const resp = await get<AccountUsageResponse>('/api/usage/account', params);
      setData(resp);
      markUpdated();
    } catch (err) {
      if (err instanceof ApiError && err.isServerError) {
        setIsServerError(true);
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : t('common.error.loadData'));
      }
    } finally {
      setLoading(false);
    }
  }, [dateRange, granularity, markUpdated, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <SpaceBetween size="l">
      <Header variant="h1" description={formattedTime ? t('common.lastUpdated', { time: formattedTime }) : undefined}>{t('nav.accountUsage')}</Header>

      {error && (
        <Alert
          type="error"
          dismissible
          onDismiss={() => setError(null)}
          action={isServerError ? <Button onClick={fetchData}>{t('common.retry')}</Button> : undefined}
        >
          {error}
        </Alert>
      )}

      {loading && !data ? (
        <SpaceBetween size="l">
          <SkeletonLoader variant="cards" count={4} columns={4} />
          <SkeletonLoader variant="chart" height={300} />
          <SkeletonLoader variant="chart" height={300} />
        </SpaceBetween>
      ) : (
        <>
          <AccountSummaryCards totals={data?.totals} loading={loading} />

          <SpaceBetween size="s" direction="horizontal" alignItems="end">
            <div style={{ minWidth: 300 }}>
              <LocalizedDateRangePicker
                value={dateRange}
                onChange={(value) => setDateRange(value)}
              />
            </div>
            <div style={{ minWidth: 150 }}>
              <Select
                selectedOption={granularity}
                onChange={({ detail }) => setGranularity(detail.selectedOption)}
                options={GRANULARITY_OPTIONS}
                placeholder={t('account.granularity.placeholder')}
              />
            </div>
            <Button iconName="refresh" onClick={fetchData} loading={loading}>
              {t('common.refresh')}
            </Button>
          </SpaceBetween>

          <TimelineChart timeline={data?.timeline ?? []} loading={loading} />

          <BreakdownCharts
            tierBreakdown={data?.breakdownByTier ?? []}
            clientTypeBreakdown={data?.breakdownByClientType ?? []}
            loading={loading}
          />
        </>
      )}
    </SpaceBetween>
  );
}
