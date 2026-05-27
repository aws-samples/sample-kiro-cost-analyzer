import Cards from '@cloudscape-design/components/cards';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import { useI18n } from '../i18n/useI18n';
import type { ProductivitySummary } from '../types';

interface ProductivitySummaryCardsProps {
  summary: ProductivitySummary | undefined;
  loading: boolean;
}

function formatHour(hour: number | null | undefined): string {
  if (hour === null || hour === undefined) return '—';
  return `${hour.toString().padStart(2, '0')}:00`;
}

export default function ProductivitySummaryCards({ summary, loading }: ProductivitySummaryCardsProps) {
  const { t, formatNumber } = useI18n();

  const items = [
    { title: t('productivity.summary.totalDaysActive'), value: summary?.totalDaysActive?.toString() ?? '—' },
    { title: t('productivity.summary.totalInteractions'), value: summary?.totalInteractions != null ? formatNumber(summary.totalInteractions) : '—' },
    { title: t('productivity.summary.totalPrompts'), value: summary?.totalPrompts != null ? formatNumber(summary.totalPrompts) : '—' },
    { title: t('productivity.summary.avgDailyInteractions'), value: summary?.avgDailyInteractions != null ? formatNumber(summary.avgDailyInteractions, { minimumFractionDigits: 1 }) : '—' },
    { title: t('productivity.summary.topCategory'), value: summary?.topCategory || '—' },
    { title: t('productivity.summary.peakHour'), value: formatHour(summary?.peakHour) },
  ];

  return (
    <Cards
      loading={loading}
      loadingText={t('productivity.summary.loading')}
      header={<Header>{t('productivity.summary.header')}</Header>}
      cardDefinition={{
        header: (item) => item.title,
        sections: [
          {
            id: 'value',
            content: (item) => <Box variant="h1" textAlign="center">{item.value}</Box>,
          },
        ],
      }}
      items={items}
      cardsPerRow={[{ cards: 1 }, { minWidth: 180, cards: 3 }, { minWidth: 300, cards: 6 }]}
    />
  );
}
