import LineChart from '@cloudscape-design/components/line-chart';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import { useI18n } from '../i18n/useI18n';
import type { ActivityTimelineEntry } from '../types';

interface ActivityTimelineChartProps {
  timeline: ActivityTimelineEntry[];
  loading: boolean;
}

export default function ActivityTimelineChart({ timeline, loading }: ActivityTimelineChartProps) {
  const { t, formatDate } = useI18n();

  const series = [
    {
      title: t('productivity.activityTimeline.series.interactions'),
      type: 'line' as const,
      data: timeline.map((e) => ({ x: new Date(e.date), y: e.interactions })),
    },
    {
      title: t('productivity.activityTimeline.series.messages'),
      type: 'line' as const,
      data: timeline.map((e) => ({ x: new Date(e.date), y: e.messages })),
    },
    {
      title: t('productivity.activityTimeline.series.conversations'),
      type: 'line' as const,
      data: timeline.map((e) => ({ x: new Date(e.date), y: e.conversations })),
    },
  ];

  const maxY = timeline.length > 0
    ? Math.max(...timeline.map((e) => Math.max(e.interactions, e.messages, e.conversations)), 1)
    : 1;

  return (
    <div>
      <Header variant="h2">{t('productivity.activityTimeline.title')}</Header>
      {loading ? (
        <Box textAlign="center" padding="l">{t('common.loading.chart')}</Box>
      ) : timeline.length === 0 ? (
        <Box textAlign="center" padding="l" color="text-status-inactive">
          {t('common.empty.noDataForPeriod')}
        </Box>
      ) : (
        <LineChart
          series={series}
          xDomain={[new Date(timeline[0].date), new Date(timeline[timeline.length - 1].date)]}
          yDomain={[0, maxY]}
          xTitle={t('productivity.activityTimeline.xAxis')}
          yTitle={t('productivity.activityTimeline.yAxis')}
          xScaleType="time"
          xTickFormatter={(date) =>
            formatDate(date, { month: 'short', day: 'numeric', timeZone: 'UTC' })
          }
          height={300}
          empty={<Box textAlign="center" color="inherit">{t('common.empty.noData')}</Box>}
          noMatch={<Box textAlign="center" color="inherit">{t('common.empty.noMatch')}</Box>}
        />
      )}
    </div>
  );
}
