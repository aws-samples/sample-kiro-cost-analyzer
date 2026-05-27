import { useEffect, useState, useCallback } from 'react';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Button from '@cloudscape-design/components/button';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Link from '@cloudscape-design/components/link';
import PieChart from '@cloudscape-design/components/pie-chart';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { useSearchParams } from 'react-router-dom';
import { useI18n } from '../i18n/useI18n';
import { get, ApiError } from '../api/client';
import type { EngagementResponse } from '../types';
import SkeletonLoader from './SkeletonLoader';

interface EngagementSegmentationWidgetProps {
  dateParams: Record<string, string>;
}

const CATEGORY_COLORS: Record<string, string> = {
  power: '#0972d3',  // blue
  active: '#1b9e77', // teal
  light: '#d4a017',  // amber
  idle: '#5f6b7a',   // gray
  dormant: '#8b0000', // dark red/maroon
};

export default function EngagementSegmentationWidget({ dateParams }: EngagementSegmentationWidgetProps) {
  const { t, formatNumber } = useI18n();
  const [, setSearchParams] = useSearchParams();
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

  const pieData = data?.segmentation?.map((seg) => ({
    title: t(`engagement.category.${seg.category}` as any),
    value: seg.count,
    color: CATEGORY_COLORS[seg.category] ?? '#5f6b7a',
  })) ?? [];

  if (loading) {
    return (
      <Container header={<Header variant="h2" actions={<Link onFollow={() => setSearchParams({ tab: 'users' })}>{t('engagement.header.viewUsers')}</Link>}>{t('engagement.header.title')}</Header>}>
        <SkeletonLoader variant="chart" height={300} />
      </Container>
    );
  }

  if (error) {
    return (
      <Container header={<Header variant="h2" actions={<Link onFollow={() => setSearchParams({ tab: 'users' })}>{t('engagement.header.viewUsers')}</Link>}>{t('engagement.header.title')}</Header>}>
        <Alert
          type="error"
          action={<Button onClick={fetchData}>{t('engagement.error.retry')}</Button>}
        >
          {error}
        </Alert>
      </Container>
    );
  }

  const emptyContent = (
    <Box textAlign="center" color="inherit">
      {t('common.empty.noData')}
    </Box>
  );

  return (
    <Container header={<Header variant="h2" actions={<Link onFollow={() => setSearchParams({ tab: 'users' })}>{t('engagement.header.viewUsers')}</Link>}>{t('engagement.header.title')}</Header>}>
      <SpaceBetween size="l">
        {data?.derivedMetrics && (
          <ColumnLayout columns={4} variant="text-grid">
            <Box>
              <Box variant="awsui-key-label">
                {t('engagement.metrics.powerUserPercentage')}
              </Box>
              <Box variant="awsui-value-large">
                {fmtPercent(data.derivedMetrics.powerUserPercentage)}%
              </Box>
              <Box color="text-body-secondary" fontSize="body-s">
                {t('engagement.metrics.powerUserPercentage.description')}
              </Box>
            </Box>
            <Box>
              <Box variant="awsui-key-label">
                {t('engagement.metrics.activationRate')}
              </Box>
              <Box variant="awsui-value-large">
                {fmtPercent(data.derivedMetrics.activationRate)}%
              </Box>
              <Box color="text-body-secondary" fontSize="body-s">
                {t('engagement.metrics.activationRate.description')}
              </Box>
            </Box>
            <Box>
              <Box variant="awsui-key-label">
                {t('engagement.metrics.idleRate')}
              </Box>
              <Box variant="awsui-value-large">
                {fmtPercent(data.derivedMetrics.idleRate)}%
              </Box>
              <Box color="text-body-secondary" fontSize="body-s">
                {t('engagement.metrics.idleRate.description')}
              </Box>
            </Box>
            <Box>
              <Box variant="awsui-key-label">
                {t('engagement.metrics.dormantRate')}
              </Box>
              <Box variant="awsui-value-large">
                {fmtPercent(data.derivedMetrics.dormantRate)}%
              </Box>
              <Box color="text-body-secondary" fontSize="body-s">
                {t('engagement.metrics.dormantRate.description')}
              </Box>
            </Box>
          </ColumnLayout>
        )}

        {pieData.length === 0 ? (
          <Box textAlign="center" padding="l" color="text-status-inactive">
            {t('common.empty.noData')}
          </Box>
        ) : (
          <PieChart
            data={pieData}
            detailPopoverContent={(datum) => [
              { key: t('engagement.category.count'), value: String(datum.value) },
            ]}
            segmentDescription={(datum) =>
              `${datum.value} ${t('engagement.category.users')}`
            }
            size="medium"
            empty={emptyContent}
            noMatch={emptyContent}
          />
        )}
      </SpaceBetween>
    </Container>
  );
}
