import LineChart from '@cloudscape-design/components/line-chart';
import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import { useI18n } from '../i18n/useI18n';
import type { TimelineEntry } from '../types';

interface TimelineChartProps {
  timeline: TimelineEntry[];
  loading: boolean;
}

export default function TimelineChart({ timeline, loading }: TimelineChartProps) {
  const { t, formatDate } = useI18n();

  const series = [
    {
      title: t('timeline.series.credits'),
      type: 'line' as const,
      data: timeline.map((e) => ({ x: new Date(e.period), y: e.totalCredits })),
    },
    {
      title: t('timeline.series.overage'),
      type: 'line' as const,
      data: timeline.map((e) => ({ x: new Date(e.period), y: e.totalOverageCredits })),
    },
  ];

  return (
    <Container header={<Header variant="h2">{t('timeline.title')}</Header>}>
      {loading ? (
        <Box textAlign="center" padding="l">{t('common.loading.chart')}</Box>
      ) : timeline.length === 0 ? (
        <Box textAlign="center" padding="l" color="text-status-inactive">
          {t('common.empty.noDataForPeriod')}
        </Box>
      ) : (
        <LineChart
          series={series}
          xDomain={
            timeline.length > 0
              ? [new Date(timeline[0].period), new Date(timeline[timeline.length - 1].period)]
              : undefined
          }
          yDomain={[0, Math.max(...timeline.map((e) => Math.max(e.totalCredits, e.totalOverageCredits)), 1)]}
          xTitle={t('timeline.axis.period')}
          yTitle={t('timeline.axis.value')}
          xScaleType="time"
          xTickFormatter={(date) =>
            formatDate(date, { month: 'short', day: 'numeric', timeZone: 'UTC' })
          }
          height={300}
          empty={
            <Box textAlign="center" color="inherit">
              {t('common.empty.noData')}
            </Box>
          }
          noMatch={
            <Box textAlign="center" color="inherit">
              {t('common.empty.noMatch')}
            </Box>
          }
        />
      )}
    </Container>
  );
}
