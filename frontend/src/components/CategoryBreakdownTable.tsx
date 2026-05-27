import Table from '@cloudscape-design/components/table';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import { useI18n } from '../i18n/useI18n';
import type { ProductivityCategoryBreakdown } from '../types';

interface CategoryBreakdownTableProps {
  categories: ProductivityCategoryBreakdown[];
  loading: boolean;
}

export default function CategoryBreakdownTable({ categories, loading }: CategoryBreakdownTableProps) {
  const { t, formatNumber } = useI18n();

  return (
    <Table
      loading={loading}
      loadingText={t('productivity.categoryBreakdown.loading')}
      header={
        <Header
          variant="h2"
          description={t('productivity.categoryBreakdown.description')}
          counter={`(${categories.length})`}
        >
          {t('productivity.categoryBreakdown.title')}
        </Header>
      }
      empty={
        <Box textAlign="center" color="inherit">
          <b>{t('productivity.categoryBreakdown.empty.title')}</b>
          <Box padding={{ bottom: 's' }} variant="p" color="inherit">
            {t('productivity.categoryBreakdown.empty.description')}
          </Box>
        </Box>
      }
      columnDefinitions={[
        {
          id: 'category',
          header: t('productivity.categoryBreakdown.header.category'),
          cell: (item) => item.category || 'N/A',
          width: 220,
          sortingField: 'category',
        },
        {
          id: 'count',
          header: t('productivity.categoryBreakdown.header.count'),
          cell: (item) => formatNumber(item.count),
          width: 120,
          sortingField: 'count',
        },
        {
          id: 'percentage',
          header: t('productivity.categoryBreakdown.header.percentage'),
          cell: (item) => (
            <ProgressBar
              value={item.percentage}
              additionalInfo={`${item.percentage.toFixed(1)}%`}
            />
          ),
          width: 200,
        },
        {
          id: 'avgPromptLength',
          header: t('productivity.categoryBreakdown.header.avgPromptLength'),
          cell: (item) => formatNumber(item.avgPromptLength),
          width: 160,
        },
        {
          id: 'avgResponseLength',
          header: t('productivity.categoryBreakdown.header.avgResponseLength'),
          cell: (item) => formatNumber(item.avgResponseLength),
          width: 170,
        },
      ]}
      items={categories}
      sortingDisabled={false}
      trackBy="category"
    />
  );
}
