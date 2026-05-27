import LineChart from '@cloudscape-design/components/line-chart';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import Grid from '@cloudscape-design/components/grid';
import Container from '@cloudscape-design/components/container';
import { useI18n } from '../i18n/useI18n';
import type { DailyUsageEntry } from '../types';

interface DailyUsageChartProps {
  data: DailyUsageEntry[];
  loading: boolean;
}

export function computeYDomain(values: number[]): [number, number] {
  return [0, Math.max(...values, 1)];
}

export function computeXDomain(data: DailyUsageEntry[]): [Date, Date] | undefined {
  if (data.length === 0) return undefined;
  return [new Date(data[0].date), new Date(data[data.length - 1].date)];
}

export default function DailyUsageChart({ data, loading }: DailyUsageChartProps) {
  const { t } = useI18n();
  const xDomain = computeXDomain(data);

  const hasOverage = data.some((e) => e.overageCredits > 0);

  const creditsSeries = [
    {
      title: t('dailyUsage.series.credits'),
      type: 'line' as const,
      data: data.map((e) => ({ x: new Date(e.date), y: e.credits })),
      color: '#2ea597',
    },
    ...(hasOverage
      ? [
          {
            title: t('dailyUsage.series.overage'),
            type: 'line' as const,
            data: data.map((e) => ({ x: new Date(e.date), y: e.overageCredits })),
            color: '#ff6b6b',
          },
        ]
      : []),
  ];
  const creditsValues = data.flatMap((e) => [e.credits, e.overageCredits]);
  const creditsYDomain = computeYDomain(creditsValues);

  const interactionsSeries = [
    {
      title: t('dailyUsage.series.interactions'),
      type: 'line' as const,
      data: data.map((e) => ({ x: new Date(e.date), y: e.interactions })),
      color: '#ec7211',
    },
  ];
  const interactionsYDomain = computeYDomain(data.map((e) => e.interactions));

  const emptyState = (
    <Box textAlign="center" color="inherit">
      {t('common.empty.noDataForPeriod')}
    </Box>
  );

  const noMatch = (
    <Box textAlign="center" color="inherit">
      {t('common.empty.noMatch')}
    </Box>
  );

  return (
    <Container header={<Header variant="h2">{t('dailyUsage.title')}</Header>}>
      {loading ? (
        <Box textAlign="center" padding="l">{t('common.loading.chart')}</Box>
      ) : (
        <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
          <div>
            <Header variant="h3">{hasOverage ? t('dailyUsage.header.creditsAndOverage') : t('dailyUsage.header.credits')}</Header>
            <LineChart
              series={creditsSeries}
              xDomain={xDomain}
              yDomain={creditsYDomain}
              xTitle={t('dailyUsage.axis.date')}
              yTitle={t('dailyUsage.axis.credits')}
              xScaleType="time"
              height={300}
              hideFilter
              hideLegend={!hasOverage}
              empty={emptyState}
              noMatch={noMatch}
            />
          </div>
          <div>
            <Header variant="h3">{t('dailyUsage.header.interactions')}</Header>
            <LineChart
              series={interactionsSeries}
              xDomain={xDomain}
              yDomain={interactionsYDomain}
              xTitle={t('dailyUsage.axis.date')}
              yTitle={t('dailyUsage.axis.interactions')}
              xScaleType="time"
              height={300}
              hideFilter
              hideLegend
              empty={emptyState}
              noMatch={noMatch}
            />
          </div>
        </Grid>
      )}
    </Container>
  );
}
