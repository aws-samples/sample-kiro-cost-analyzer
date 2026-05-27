import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import { useI18n } from '../i18n/useI18n';
import type { UserDetailSummary } from '../types';

interface UserSummaryCardsProps {
  summary: UserDetailSummary | undefined;
  loading: boolean;
}

export default function UserSummaryCards({ summary, loading }: UserSummaryCardsProps) {
  const { t, formatNumber } = useI18n();

  const fmt = (n: number) =>
    formatNumber(n, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const fmtInt = (n: number) => formatNumber(n);

  if (loading) {
    return (
      <Container header={<Header variant="h2">{t('userDetail.summary.title')}</Header>}>
        <Box textAlign="center" padding="l">{t('userDetail.summary.loading')}</Box>
      </Container>
    );
  }

  const hasOverage = summary ? summary.totalOverageCredits > 0 : false;

  return (
    <Container header={<Header variant="h2">{t('userDetail.summary.title')}</Header>}>
      <ColumnLayout columns={hasOverage ? 5 : 4} variant="text-grid">
        <div>
          <Box variant="awsui-key-label">{t('userDetail.summary.totalCredits')}</Box>
          <Box variant="h1" textAlign="center">
            {summary ? fmt(summary.totalCredits) : '—'}
          </Box>
        </div>
        {hasOverage && (
          <div>
            <Box variant="awsui-key-label">{t('userDetail.summary.overageCredits')}</Box>
            <Box variant="h1" textAlign="center" color="text-status-warning">
              {summary ? fmt(summary.totalOverageCredits) : '—'}
            </Box>
          </div>
        )}
        <div>
          <Box variant="awsui-key-label">{t('userDetail.summary.totalInteractions')}</Box>
          <Box variant="h1" textAlign="center">
            {summary ? fmtInt(summary.totalInteractions) : '—'}
          </Box>
        </div>
        <div>
          <Box variant="awsui-key-label">{t('userDetail.summary.averageCostPerInteraction')}</Box>
          <Box variant="h1" textAlign="center">
            {summary ? fmt(summary.averageCostPerInteraction) : '—'}
          </Box>
        </div>
        <div>
          <Box variant="awsui-key-label">{t('userDetail.summary.totalMessages')}</Box>
          <Box variant="h1" textAlign="center">
            {summary ? fmtInt(summary.totalMessages) : '—'}
          </Box>
        </div>
      </ColumnLayout>
    </Container>
  );
}
