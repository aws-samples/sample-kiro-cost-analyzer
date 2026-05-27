import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import Box from '@cloudscape-design/components/box';
import { useI18n } from '../i18n/useI18n';
import SkeletonLoader from './SkeletonLoader';
import type { AccountTotals } from '../types';

interface AccountSummaryCardsProps {
  totals: AccountTotals | undefined;
  loading: boolean;
}

export default function AccountSummaryCards({ totals, loading }: AccountSummaryCardsProps) {
  const { t, formatNumber } = useI18n();

  const fmt = (n: number) =>
    formatNumber(n, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const fmtInt = (n: number) => formatNumber(n);

  if (loading) {
    return <SkeletonLoader variant="cards" count={4} columns={4} />;
  }

  return (
    <Container header={<Header>{t('account.summary.title')}</Header>}>
      <KeyValuePairs
        columns={4}
        items={[
          {
            label: t('account.summary.totalCredits'),
            value: <Box variant="awsui-value-large">{totals ? fmt(totals.totalCredits) : '—'}</Box>,
          },
          {
            label: t('account.summary.totalOverage'),
            value: <Box variant="awsui-value-large">{totals ? fmt(totals.totalOverageCredits) : '—'}</Box>,
          },
          {
            label: t('account.summary.totalMessages'),
            value: <Box variant="awsui-value-large">{totals ? fmtInt(totals.totalMessages) : '—'}</Box>,
          },
          {
            label: t('account.summary.totalConversations'),
            value: <Box variant="awsui-value-large">{totals ? fmtInt(totals.totalConversations) : '—'}</Box>,
          },
        ]}
      />
    </Container>
  );
}
