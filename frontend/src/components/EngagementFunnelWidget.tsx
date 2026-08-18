import { useEffect, useState, useCallback } from 'react';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Popover from '@cloudscape-design/components/popover';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { useI18n } from '../i18n/useI18n';
import { get, ApiError } from '../api/client';
import type { EngagementResponse } from '../types';
import D3FunnelChart from './charts/D3FunnelChart';
import SkeletonLoader from './SkeletonLoader';

interface EngagementFunnelWidgetProps {
  dateParams: Record<string, string>;
}

const FUNNEL_COLORS = [
  '#5f6b7a', // allUsers - gray (neutral, represents everyone)
  '#1b9e77', // sentMessages - teal (same as "active" in pie)
  '#1b9e77', // activeUsers - teal (active category)
  '#0972d3', // powerUsers - blue (power category)
];

export default function EngagementFunnelWidget({ dateParams }: EngagementFunnelWidgetProps) {
  const { t, formatNumber } = useI18n();
  const [data, setData] = useState<EngagementResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await get<EngagementResponse>('/api/usage/engagement', dateParams);
      setData(response);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(t('engagement.error'));
      }
    } finally {
      setLoading(false);
    }
  }, [dateParams, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fmtPercent = (value: number) =>
    formatNumber(value, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  const funnelChartData = data?.funnel?.map((stage) => ({
    label: t(`engagement.funnel.stage.${stage.name}` as any),
    value: stage.count,
    percentage: stage.conversionRate,
  })) ?? [];

  if (loading) {
    return (
      <Container header={<Header variant="h2">{t('engagement.funnel.title')}</Header>}>
        <SkeletonLoader variant="chart" height={300} />
      </Container>
    );
  }

  if (error) {
    return (
      <Container header={<Header variant="h2">{t('engagement.funnel.title')}</Header>}>
        <Alert
          type="error"
          action={<Button onClick={fetchData}>{t('engagement.error.retry')}</Button>}
        >
          {error}
        </Alert>
      </Container>
    );
  }

  return (
    <Container header={<Header variant="h2">{t('engagement.funnel.title')}</Header>}>
      {data?.derivedMetrics?.churnRiskRate != null && (
        <Box margin={{ bottom: 'l' }}>
          <Box variant="awsui-key-label">
            <Popover
              header={t('engagement.metrics.churnRiskRate')}
              content={
                <SpaceBetween size="xs">
                  <Box variant="p">{t('engagement.metrics.churnRiskRate.popover.formula')}</Box>
                  {data.derivedMetrics.idleCount != null &&
                    data.derivedMetrics.dormantCount != null &&
                    data.derivedMetrics.totalUsers != null && (
                      <Box variant="p">
                        {t('engagement.metrics.churnRiskRate.popover.counts', {
                          idle: data.derivedMetrics.idleCount,
                          dormant: data.derivedMetrics.dormantCount,
                          total: data.derivedMetrics.totalUsers,
                        })}
                      </Box>
                    )}
                  <Box variant="p" color="text-body-secondary">
                    {t('engagement.metrics.churnRiskRate.popover.threshold')}
                  </Box>
                </SpaceBetween>
              }
            >
              {t('engagement.metrics.churnRiskRate')}
            </Popover>
          </Box>
          <Box
            variant="awsui-value-large"
            color={data.derivedMetrics.churnRiskRate > 50 ? 'text-status-error' : undefined}
          >
            {fmtPercent(data.derivedMetrics.churnRiskRate)}%
          </Box>
          <Box color="text-body-secondary" fontSize="body-s">
            {t('engagement.metrics.churnRiskRate.description')}
          </Box>
        </Box>
      )}
      {funnelChartData.length === 0 ? (
        <Box textAlign="center" padding="l" color="text-status-inactive">
          {t('common.empty.noData')}
        </Box>
      ) : (
        <D3FunnelChart
          data={funnelChartData}
          colors={FUNNEL_COLORS}
          showConversionRates={true}
        />
      )}
    </Container>
  );
}
