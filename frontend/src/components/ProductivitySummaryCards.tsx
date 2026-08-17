import Cards from '@cloudscape-design/components/cards';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import { useI18n } from '../i18n/useI18n';
import { formatCardValue } from '../utils/formatCardValue';
import type { ProductivitySummary } from '../types';

interface ProductivitySummaryCardsProps {
  summary: ProductivitySummary | undefined;
  loading: boolean;
}

/** Prevents mid-number line wraps inside the KPI grid (issue #20). */
const nowrap = (content: string) => <span style={{ whiteSpace: 'nowrap' }}>{content}</span>;

function formatHour(hour: number | null | undefined): string {
  if (hour === null || hour === undefined) return '—';
  return `${hour.toString().padStart(2, '0')}:00`;
}

export default function ProductivitySummaryCards({ summary, loading }: ProductivitySummaryCardsProps) {
  const { t, formatNumber } = useI18n();

  const fmtInt = (n: number) => nowrap(formatCardValue(n, formatNumber, { fractionDigits: 0 }));
  const fmtAvg = (n: number) => nowrap(formatCardValue(n, formatNumber, { fractionDigits: 1 }));

  const items = [
    { title: t('productivity.summary.totalDaysActive'), value: summary?.totalDaysActive != null ? fmtInt(summary.totalDaysActive) : '—' },
    { title: t('productivity.summary.totalInteractions'), value: summary?.totalInteractions != null ? fmtInt(summary.totalInteractions) : '—' },
    { title: t('productivity.summary.totalPrompts'), value: summary?.totalPrompts != null ? fmtInt(summary.totalPrompts) : '—' },
    { title: t('productivity.summary.avgDailyInteractions'), value: summary?.avgDailyInteractions != null ? fmtAvg(summary.avgDailyInteractions) : '—' },
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
