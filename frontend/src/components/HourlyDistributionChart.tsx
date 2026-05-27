import BarChart from '@cloudscape-design/components/bar-chart';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import { useI18n } from '../i18n/useI18n';
import type { HourlyDistribution } from '../types';

interface HourlyDistributionChartProps {
  data: HourlyDistribution[];
  loading: boolean;
}

export default function HourlyDistributionChart({ data, loading }: HourlyDistributionChartProps) {
  const { t } = useI18n();

  const series = [
    {
      title: t('productivity.hourly.series'),
      type: 'bar' as const,
      data: data.map((d) => ({
        x: `${d.hour.toString().padStart(2, '0')}h`,
        y: d.count,
      })),
    },
  ];

  const maxY = data.length > 0 ? Math.max(...data.map((d) => d.count), 1) : 1;

  return (
    <div>
      <Header variant="h2">{t('productivity.hourly.title')}</Header>
      {loading ? (
        <Box textAlign="center" padding="l">{t('common.loading.chart')}</Box>
      ) : data.every((d) => d.count === 0) ? (
        <Box textAlign="center" padding="l" color="text-status-inactive">
          {t('common.empty.noDataAvailable')}
        </Box>
      ) : (
        <BarChart
          series={series}
          yDomain={[0, maxY]}
          xTitle={t('productivity.hourly.xAxis')}
          yTitle={t('productivity.hourly.yAxis')}
          height={250}
          empty={<Box textAlign="center" color="inherit">{t('common.empty.noData')}</Box>}
          noMatch={<Box textAlign="center" color="inherit">{t('common.empty.noMatch')}</Box>}
        />
      )}
    </div>
  );
}
