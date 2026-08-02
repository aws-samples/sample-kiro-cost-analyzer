import Table from '@cloudscape-design/components/table';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import Link from '@cloudscape-design/components/link';
import Badge from '@cloudscape-design/components/badge';
import { useNavigate } from 'react-router';
import { useI18n } from '../i18n/useI18n';
import type { InactiveSubscriber, InactiveSummary } from '../types';

interface InactiveSubscribersTableProps {
  subscribers: InactiveSubscriber[];
  summary: InactiveSummary;
}

/**
 * Lifetime view of paid subscribers with no activity in ``thresholdDays``+
 * days. Distinct from the upgrade/downgrade table because the suggested
 * action is qualitatively different — there is no "recommended tier" to
 * switch to, only the question of whether to keep paying for an idle
 * seat. ``annualWastedCost`` frames the same dollar denomination so admins
 * can compare with the upgrade/downgrade savings above.
 */
export default function InactiveSubscribersTable({
  subscribers,
  summary,
}: InactiveSubscribersTableProps) {
  const { t, formatNumber, formatDate } = useI18n();
  const navigate = useNavigate();

  const formatCurrency = (value: number) =>
    formatNumber(value, { style: 'currency', currency: 'USD' });

  return (
    <Table
      header={
        <Header
          counter={`(${summary.totalInactive})`}
          description={t('recommendations.inactive.description', {
            days: summary.thresholdDays,
            wasted: formatCurrency(summary.totalAnnualWastedCost),
          })}
        >
          {t('recommendations.inactive.title')}
        </Header>
      }
      empty={
        <Box textAlign="center" color="text-status-inactive" padding="l">
          <b>{t('recommendations.inactive.empty.title')}</b>
          <Box padding={{ top: 's' }} variant="p">
            {t('recommendations.inactive.empty.description', { days: summary.thresholdDays })}
          </Box>
        </Box>
      }
      columnDefinitions={[
        {
          id: 'displayName',
          header: t('recommendations.table.header.user'),
          cell: (item) => (
            <Link
              href={`/user/${item.userId}`}
              onFollow={(e) => {
                e.preventDefault();
                navigate(`/user/${item.userId}`);
              }}
            >
              {item.displayName}
            </Link>
          ),
        },
        {
          id: 'currentTier',
          header: t('recommendations.table.header.currentTier'),
          cell: (item) => <Badge>{item.currentTier}</Badge>,
        },
        {
          id: 'lastActiveDate',
          header: t('recommendations.inactive.header.lastSeen'),
          cell: (item) =>
            item.lastActiveDate
              ? formatDate(new Date(item.lastActiveDate))
              : t('recommendations.inactive.neverSeen'),
        },
        {
          id: 'daysInactive',
          header: t('recommendations.inactive.header.daysInactive'),
          cell: (item) =>
            item.daysInactive !== null
              ? formatNumber(item.daysInactive)
              : t('recommendations.inactive.neverSeen'),
        },
        {
          id: 'annualWastedCost',
          header: t('recommendations.inactive.header.annualWastedCost'),
          cell: (item) => formatCurrency(item.annualWastedCost),
        },
      ]}
      items={subscribers}
    />
  );
}
