import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import Box from '@cloudscape-design/components/box';
import { useI18n } from '../i18n/useI18n';
import SkeletonLoader from './SkeletonLoader';
import type { UsageSummary } from '../types';

interface SummaryCardsProps {
  summary: UsageSummary | undefined;
  loading: boolean;
}

export default function SummaryCards({ summary, loading }: SummaryCardsProps) {
  const { t, formatNumber } = useI18n();

  const fmt = (n: number) =>
    formatNumber(n, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  if (loading) {
    return <SkeletonLoader variant="cards" count={4} columns={4} />;
  }

  return (
    <Container header={<Header>{t('dashboard.summary.title')}</Header>}>
      <KeyValuePairs
        columns={4}
        items={[
          {
            label: t('dashboard.summary.totalUsers'),
            value: <Box variant="awsui-value-large">{summary?.totalUsers?.toString() ?? '—'}</Box>,
          },
          {
            label: t('dashboard.summary.totalCredits'),
            value: <Box variant="awsui-value-large">{summary ? fmt(summary.totalCredits) : '—'}</Box>,
          },
          {
            label: t('dashboard.summary.totalOverage'),
            value: <Box variant="awsui-value-large">{summary ? fmt(summary.totalOverageCredits) : '—'}</Box>,
          },
          {
            label: t('dashboard.summary.averagePerUser'),
            value: <Box variant="awsui-value-large">{summary ? fmt(summary.averageCreditsPerUser) : '—'}</Box>,
          },
        ]}
      />
    </Container>
  );
}
