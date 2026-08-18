import { useState, useEffect, useCallback } from 'react';
import Table from '@cloudscape-design/components/table';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Alert from '@cloudscape-design/components/alert';
import Button from '@cloudscape-design/components/button';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Link from '@cloudscape-design/components/link';
import { useNavigate } from 'react-router';
import { get, ApiError } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import SkeletonLoader from './SkeletonLoader';
import InactiveSubscribersTable from './InactiveSubscribersTable';
import type { TierRecommendation, TierRecommendationsResponse } from '../types';

type FilterValue = 'all' | 'upgrade' | 'downgrade';

interface RecommendationsTabProps {
  dateParams?: Record<string, string>;
}

export default function RecommendationsTab({ dateParams }: RecommendationsTabProps) {
  const { t, formatNumber } = useI18n();
  const navigate = useNavigate();

  const [data, setData] = useState<TierRecommendationsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pricingNotConfigured, setPricingNotConfigured] = useState(false);
  const [filter, setFilter] = useState<SelectProps.Option>({ value: 'all', label: t('recommendations.filter.all') });

  const filterOptions: SelectProps.Option[] = [
    { value: 'all', label: t('recommendations.filter.all') },
    { value: 'upgrade', label: t('recommendations.filter.upgrade') },
    { value: 'downgrade', label: t('recommendations.filter.downgrade') },
  ];

  const formatCurrency = useCallback(
    (value: number) => formatNumber(value, { style: 'currency', currency: 'USD' }),
    [formatNumber],
  );

  const fetchRecommendations = useCallback(async () => {
    setLoading(true);
    setError(null);
    setPricingNotConfigured(false);
    try {
      const resp = await get<TierRecommendationsResponse>('/api/recommendations/tier-optimization', dateParams);
      setData(resp);
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setPricingNotConfigured(true);
      } else {
        setError(err instanceof Error ? err.message : t('recommendations.error.title'));
      }
    } finally {
      setLoading(false);
    }
  }, [t, dateParams]);

  useEffect(() => {
    fetchRecommendations();
  }, [fetchRecommendations]);

  const filteredRecommendations: TierRecommendation[] = data?.recommendations
    ? (filter.value as FilterValue) === 'all'
      ? data.recommendations
      : data.recommendations.filter((r) => r.recommendationType === filter.value)
    : [];

  // Loading state
  if (loading) {
    return (
      <SpaceBetween size="l">
        <SkeletonLoader variant="cards" count={3} columns={3} />
        <SkeletonLoader variant="table" count={5} />
      </SpaceBetween>
    );
  }

  // Pricing not configured state
  if (pricingNotConfigured) {
    return (
      <Alert type="info" header={t('recommendations.setup.title')}>
        {t('recommendations.setup.description')}{' '}
        <Link
          href="/settings"
          onFollow={(e) => {
            e.preventDefault();
            navigate('/settings');
          }}
        >
          {t('recommendations.setup.link')}
        </Link>
      </Alert>
    );
  }

  // Error state
  if (error) {
    return (
      <Alert
        type="error"
        header={t('recommendations.error.title')}
        action={<Button onClick={fetchRecommendations}>{t('recommendations.error.retry')}</Button>}
      >
        {error}
      </Alert>
    );
  }

  // Empty state — only when BOTH lists are empty. Inactive subscribers
  // is a lifetime view, so it can be populated even when the windowed
  // upgrade/downgrade list has no rows (e.g., the dataset has dormant
  // subscribers but no one inside the date picker has overage).
  const hasRecommendations = !!(data?.recommendations && data.recommendations.length > 0);
  const hasInactive = !!(data?.inactiveSubscribers && data.inactiveSubscribers.length > 0);
  if (data && !hasRecommendations && !hasInactive) {
    return (
      <Box textAlign="center" color="inherit" padding={{ vertical: 'xl' }}>
        <b>{t('recommendations.empty')}</b>
      </Box>
    );
  }

  return (
    <SpaceBetween size="l">
      {/* Summary card + recommendations table — only when there are
          upgrade/downgrade rows. The lifetime "Inactive subscribers"
          block below renders independently. */}
      {hasRecommendations && (
        <>
          <Container
            header={
              <Header
                variant="h2"
                description={
                  data?.period
                    ? t('recommendations.summary.period', {
                        start: data.period.startDate,
                        end: data.period.endDate,
                        days: data.period.daysWindow,
                      })
                    : undefined
                }
              >
                {t('recommendations.summary.title')}
              </Header>
            }
          >
            <ColumnLayout columns={3} variant="text-grid">
              <div>
                <Box variant="awsui-key-label">{t('recommendations.summary.totalSavings')}</Box>
                <Box variant="awsui-value-large">{formatCurrency(data?.summary.totalProjectedAnnualSavings ?? 0)}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">{t('recommendations.summary.upgrades')}</Box>
                <Box variant="awsui-value-large">{data?.summary.upgradeCount ?? 0}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">{t('recommendations.summary.downgrades')}</Box>
                <Box variant="awsui-value-large">{data?.summary.downgradeCount ?? 0}</Box>
              </div>
            </ColumnLayout>
          </Container>

          <Table
            header={
          <Header
            counter={`(${filteredRecommendations.length})`}
            actions={
              <Select
                selectedOption={filter}
                onChange={({ detail }) => setFilter(detail.selectedOption)}
                options={filterOptions}
              />
            }
          >
            {t('recommendations.tab.title')}
          </Header>
        }
        empty={
          <Box textAlign="center" color="inherit">
            <b>{t('recommendations.empty')}</b>
          </Box>
        }
        columnDefinitions={[
          {
            id: 'user',
            header: t('recommendations.table.header.user'),
            cell: (item) => item.displayName || t('common.unidentifiedUser', { id: item.userId.slice(0, 8) }),
          },
          {
            id: 'currentTier',
            header: t('recommendations.table.header.currentTier'),
            cell: (item) => item.currentTier,
          },
          {
            id: 'projectedUsage',
            header: t('recommendations.table.header.projectedUsage'),
            cell: (item) => formatNumber(item.projectedMonthlyUsage, { maximumFractionDigits: 0 }),
          },
          {
            id: 'recommendedTier',
            header: t('recommendations.table.header.recommendedTier'),
            cell: (item) => item.recommendedTier,
          },
          {
            id: 'annualSavings',
            header: t('recommendations.table.header.annualSavings'),
            cell: (item) => formatCurrency(item.annualSavings),
          },
          {
            id: 'type',
            header: t('recommendations.table.header.type'),
            cell: (item) => (
              <Badge color={item.recommendationType === 'upgrade' ? 'blue' : 'grey'}>
                {item.recommendationType === 'upgrade'
                  ? t('recommendations.type.upgrade')
                  : t('recommendations.type.downgrade')}
              </Badge>
            ),
          },
        ]}
        items={filteredRecommendations}
      />
        </>
      )}

      {/* Inactive subscribers — lifetime view, independent of date picker. */}
      {data?.inactiveSubscribers && data.inactiveSummary && (
        <InactiveSubscribersTable
          subscribers={data.inactiveSubscribers}
          summary={data.inactiveSummary}
        />
      )}
    </SpaceBetween>
  );
}
