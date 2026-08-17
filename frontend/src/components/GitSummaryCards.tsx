import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import { useI18n } from '../i18n/useI18n';
import { formatCardValue } from '../utils/formatCardValue';
import type { GitActivitySummary } from '../types';

interface GitSummaryCardsProps {
  summary: GitActivitySummary | undefined;
  loading: boolean;
}

/** Prevents mid-number line wraps inside the KPI grid (issue #20). */
const nowrap = (content: string) => <span style={{ whiteSpace: 'nowrap' }}>{content}</span>;

export default function GitSummaryCards({ summary, loading }: GitSummaryCardsProps) {
  const { t, formatNumber } = useI18n();

  const fmtInt = (n: number) => nowrap(formatCardValue(n, formatNumber, { fractionDigits: 0 }));
  const fmtAvg = (n: number) => nowrap(formatCardValue(n, formatNumber, { fractionDigits: 1 }));

  if (loading) {
    return (
      <Box textAlign="center" padding="l">
        <Spinner /> {t('git.summary.loading')}
      </Box>
    );
  }

  const items = [
    { label: t('git.summary.totalCommits'), value: summary?.totalCommits != null ? fmtInt(summary.totalCommits) : '—' },
    { label: t('git.summary.totalPRsMerged'), value: summary?.totalPRsMerged != null ? fmtInt(summary.totalPRsMerged) : '—' },
    { label: t('git.summary.totalReviews'), value: summary?.totalReviews != null ? fmtInt(summary.totalReviews) : '—' },
    { label: t('git.summary.avgLinesPerCommit'), value: summary?.avgLinesPerCommit != null ? fmtAvg(summary.avgLinesPerCommit) : '—' },
    { label: t('git.summary.totalPRsOpened'), value: summary?.totalPRsOpened != null ? fmtInt(summary.totalPRsOpened) : '—' },
    { label: t('git.summary.avgMergeTimeHours'), value: summary?.avgMergeTimeHours != null ? fmtAvg(summary.avgMergeTimeHours) : '—' },
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
