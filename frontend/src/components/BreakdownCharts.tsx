import PieChart from '@cloudscape-design/components/pie-chart';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import Grid from '@cloudscape-design/components/grid';
import { useI18n } from '../i18n/useI18n';
import type { TierBreakdown, ClientTypeBreakdown } from '../types';

interface BreakdownChartsProps {
  tierBreakdown: TierBreakdown[];
  clientTypeBreakdown: ClientTypeBreakdown[];
  loading: boolean;
}

export default function BreakdownCharts({
  tierBreakdown,
  clientTypeBreakdown,
  loading,
}: BreakdownChartsProps) {
  const { t, formatNumber } = useI18n();

  const fmtCredits = (n: number) =>
    formatNumber(n, { minimumFractionDigits: 2 });

  const tierData = tierBreakdown.map((tb) => ({
    title: tb.subscriptionTier || 'N/A',
    value: tb.totalCredits,
  }));

  const clientData = clientTypeBreakdown.map((c) => ({
    title: c.clientType || 'N/A',
    value: c.totalCredits,
  }));

  const emptyContent = (
    <Box textAlign="center" color="inherit">
      {t('common.empty.noData')}
    </Box>
  );

  return (
    <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
      <div>
        <Header variant="h2">{t('breakdowns.tier.title')}</Header>
        {loading ? (
          <Box textAlign="center" padding="l">{t('common.loading')}</Box>
        ) : tierData.length === 0 ? (
          <Box textAlign="center" padding="l" color="text-status-inactive">
            {t('common.empty.noDataAvailable')}
          </Box>
        ) : (
          <PieChart
            data={tierData}
            detailPopoverContent={(datum) => [
              { key: t('breakdowns.popover.credits'), value: fmtCredits(datum.value) },
            ]}
            segmentDescription={(datum) =>
              t('breakdowns.segment.credits', { count: fmtCredits(datum.value) })
            }
            size="medium"
            empty={emptyContent}
            noMatch={emptyContent}
          />
        )}
      </div>
      <div>
        <Header variant="h2">{t('breakdowns.clientType.title')}</Header>
        {loading ? (
          <Box textAlign="center" padding="l">{t('common.loading')}</Box>
        ) : clientData.length === 0 ? (
          <Box textAlign="center" padding="l" color="text-status-inactive">
            {t('common.empty.noDataAvailable')}
          </Box>
        ) : (
          <PieChart
            data={clientData}
            detailPopoverContent={(datum) => [
              { key: t('breakdowns.popover.credits'), value: fmtCredits(datum.value) },
            ]}
            segmentDescription={(datum) =>
              t('breakdowns.segment.credits', { count: fmtCredits(datum.value) })
            }
            size="medium"
            empty={emptyContent}
            noMatch={emptyContent}
          />
        )}
      </div>
    </Grid>
  );
}
