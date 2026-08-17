import MixedLineBarChart from '@cloudscape-design/components/mixed-line-bar-chart';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import { useI18n } from '../i18n/useI18n';
import type { ComparativeTimelineEntry } from '../types';

interface ComparativeTimelineChartProps {
  timeline: ComparativeTimelineEntry[];
  loading: boolean;
}

export default function ComparativeTimelineChart({ timeline, loading }: ComparativeTimelineChartProps) {
  const { t, formatDate } = useI18n();

  const title = t('git.comparativeTimeline.title');

  if (loading) {
    return (
      <Container header={<Header variant="h2">{title}</Header>}>
        <Box textAlign="center" padding="l">{t('common.loading.chart')}</Box>
      </Container>
    );
  }

  if (timeline.length === 0) {
    return (
      <Container header={<Header variant="h2">{title}</Header>}>
        <Box textAlign="center" padding="l" color="text-status-inactive">
          {t('git.comparativeTimeline.empty')}
        </Box>
      </Container>
    );
  }

  const series: any[] = [
    {
      title: t('git.comparativeTimeline.series.commits'),
      type: 'bar',
      data: timeline.map((e) => ({ x: e.date, y: e.gitCommits })),
      color: '#0972d3',
    },
    {
      title: t('git.comparativeTimeline.series.pullRequests'),
      type: 'bar',
      data: timeline.map((e) => ({ x: e.date, y: e.gitPRs })),
      color: '#44b9d6',
    },
    {
      title: t('git.comparativeTimeline.series.kiroPrompts'),
      type: 'line',
      data: timeline.map((e) => ({ x: e.date, y: e.kiroPrompts })),
      color: '#e07941',
    },
    {
      title: t('git.comparativeTimeline.series.impactIndex'),
      type: 'line',
      data: timeline.map((e) => ({ x: e.date, y: e.dailyImpactIndex })),
      color: '#037f0c',
    },
  ];

  const gitMax = Math.max(...timeline.map((e) => e.gitCommits + e.gitPRs), 1);
  const kiroMax = Math.max(...timeline.map((e) => e.kiroPrompts), 1);
  const yMax = Math.max(gitMax, kiroMax, 100);

  return (
    <Container header={<Header variant="h2">{title}</Header>}>
      <MixedLineBarChart
        series={series}
        xDomain={timeline.map((e) => e.date)}
        yDomain={[0, yMax]}
        xTitle={t('productivity.activityTimeline.xAxis')}
        yTitle={t('productivity.activityTimeline.yAxis')}
        stackedBars
        height={350}
        xScaleType="categorical"
        xTickFormatter={(date) =>
          formatDate(date, { month: 'short', day: 'numeric', timeZone: 'UTC' })
        }
        empty={<Box textAlign="center" color="inherit">{t('common.empty.noData')}</Box>}
        noMatch={<Box textAlign="center" color="inherit">{t('common.empty.noMatch')}</Box>}
        hideFilter={false}
        legendTitle={t('git.comparativeTimeline.legendTitle')}
        i18nStrings={{
          filterLabel: t('git.comparativeTimeline.i18n.filterLabel'),
          filterPlaceholder: t('git.comparativeTimeline.i18n.filterPlaceholder'),
          filterSelectedAriaLabel: t('git.comparativeTimeline.i18n.filterSelectedAriaLabel'),
          legendAriaLabel: t('git.comparativeTimeline.i18n.legendAriaLabel'),
          chartAriaRoleDescription: t('git.comparativeTimeline.i18n.chartAriaRoleDescription'),
        }}
      />
    </Container>
  );
}
