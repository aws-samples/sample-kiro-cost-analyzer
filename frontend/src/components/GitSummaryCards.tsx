import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import { useI18n } from '../i18n/useI18n';
import type { GitActivitySummary } from '../types';

interface GitSummaryCardsProps {
  summary: GitActivitySummary | undefined;
  loading: boolean;
}

export default function GitSummaryCards({ summary, loading }: GitSummaryCardsProps) {
  const { t, formatNumber } = useI18n();

  if (loading) {
    return (
      <Box textAlign="center" padding="l">
        <Spinner /> {t('git.summary.loading')}
      </Box>
    );
  }

  const items = [
    { label: t('git.summary.totalCommits'), value: summary?.totalCommits != null ? formatNumber(summary.totalCommits) : '—' },
    { label: t('git.summary.totalPRsMerged'), value: summary?.totalPRsMerged != null ? formatNumber(summary.totalPRsMerged) : '—' },
    { label: t('git.summary.totalReviews'), value: summary?.totalReviews != null ? formatNumber(summary.totalReviews) : '—' },
    { label: t('git.summary.avgLinesPerCommit'), value: summary?.avgLinesPerCommit != null ? formatNumber(summary.avgLinesPerCommit, { maximumFractionDigits: 1 }) : '—' },
    { label: t('git.summary.totalPRsOpened'), value: summary?.totalPRsOpened != null ? formatNumber(summary.totalPRsOpened) : '—' },
    { label: t('git.summary.avgMergeTimeHours'), value: summary?.avgMergeTimeHours != null ? formatNumber(summary.avgMergeTimeHours, { maximumFractionDigits: 1 }) : '—' },
  ];

  return (
    <div>
      <Header variant="h2">{t('git.summary.header')}</Header>
      <ColumnLayout columns={6} variant="text-grid">
        {items.map((item) => (
          <div key={item.label}>
            <Box variant="awsui-key-label">{item.label}</Box>
            <Box variant="h1" textAlign="center">{item.value}</Box>
          </div>
        ))}
      </ColumnLayout>
    </div>
  );
}
