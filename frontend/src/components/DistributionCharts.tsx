import { useMemo, useState } from 'react';
import PieChart from '@cloudscape-design/components/pie-chart';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import Grid from '@cloudscape-design/components/grid';
import Toggle from '@cloudscape-design/components/toggle';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Multiselect from '@cloudscape-design/components/multiselect';
import type { MultiselectProps } from '@cloudscape-design/components/multiselect';
import { useI18n } from '../i18n/useI18n';
import type { ModelDistribution, TriggerDistribution, CategoryDistribution } from '../types';

const SYSTEM_CATEGORIES = new Set(['Empty', 'NOT_CATEGORIZED', 'Classification Error']);

interface DistributionChartsProps {
  modelDistribution: ModelDistribution[];
  triggerDistribution: TriggerDistribution[];
  categoryDistribution: CategoryDistribution[];
  loading: boolean;
}

/**
 * Hook that manages a filterable multiselect for PieChart segments.
 * Returns the filtered data and the Multiselect element to render.
 */
function useSegmentFilter<T extends { title: string; value: number }>(
  data: T[],
  placeholder: string,
  filteringPlaceholder: string,
) {
  const allOptions: MultiselectProps.Option[] = useMemo(
    () => data.map((d) => ({ label: d.title, value: d.title })),
    [data],
  );

  const [selectedOptions, setSelectedOptions] = useState<MultiselectProps.Option[]>([]);

  // When nothing is explicitly selected, show all segments
  const isAllSelected = selectedOptions.length === 0 || selectedOptions.length === data.length;

  const filteredData = useMemo(() => {
    if (isAllSelected) return data;
    const selected = new Set(selectedOptions.map((o) => o.value));
    return data.filter((d) => selected.has(d.title));
  }, [data, selectedOptions, isAllSelected]);

  const handleChange = (detail: MultiselectProps.MultiselectChangeDetail) => {
    setSelectedOptions(detail.selectedOptions as MultiselectProps.Option[]);
  };

  const filterElement = (
    <Multiselect
      selectedOptions={isAllSelected ? allOptions : selectedOptions}
      onChange={({ detail }) => handleChange(detail)}
      options={allOptions}
      placeholder={placeholder}
      filteringType="auto"
      filteringPlaceholder={filteringPlaceholder}
      hideTokens
      expandToViewport
    />
  );

  return { filteredData, filterElement };
}

export default function DistributionCharts({
  modelDistribution,
  triggerDistribution,
  categoryDistribution,
  loading,
}: DistributionChartsProps) {
  const { t, formatNumber } = useI18n();
  const [showSystemPrompts, setShowSystemPrompts] = useState(false);

  const modelData = useMemo(
    () => modelDistribution.map((m) => ({
      title: m.modelId || 'N/A',
      value: m.count,
      percentage: m.percentage,
    })),
    [modelDistribution],
  );

  const triggerData = useMemo(
    () => triggerDistribution.map((ti) => ({
      title: ti.triggerType || 'N/A',
      value: ti.count,
      percentage: ti.percentage,
    })),
    [triggerDistribution],
  );

  const filteredCategoryDistribution = useMemo(() => {
    if (showSystemPrompts) return categoryDistribution;
    return categoryDistribution.filter((c) => !SYSTEM_CATEGORIES.has(c.category));
  }, [categoryDistribution, showSystemPrompts]);

  // Recalculate percentages after filtering
  const categoryData = useMemo(() => {
    const total = filteredCategoryDistribution.reduce((sum, c) => sum + c.count, 0);
    return filteredCategoryDistribution.map((c) => ({
      title: c.category || 'N/A',
      value: c.count,
      percentage: total > 0 ? Math.round((c.count / total) * 1000) / 10 : 0,
    }));
  }, [filteredCategoryDistribution]);

  const searchPlaceholder = t('common.filter.search');

  const { filteredData: visibleModelData, filterElement: modelFilter } =
    useSegmentFilter(modelData, t('distributions.filter.models'), searchPlaceholder);

  const { filteredData: visibleTriggerData, filterElement: triggerFilter } =
    useSegmentFilter(triggerData, t('distributions.filter.triggers'), searchPlaceholder);

  const { filteredData: visibleCategoryData, filterElement: categoryFilter } =
    useSegmentFilter(categoryData, t('distributions.filter.categories'), searchPlaceholder);

  const emptyContent = (
    <Box textAlign="center" color="inherit">
      {t('common.empty.noData')}
    </Box>
  );

  return (
    <SpaceBetween size="l">
      <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
        <div>
          <SpaceBetween size="xs">
            <Header variant="h2">{t('distributions.model.title')}</Header>
            {!loading && modelData.length > 0 && modelFilter}
          </SpaceBetween>
          {loading ? (
            <Box textAlign="center" padding="l">{t('common.loading')}</Box>
          ) : modelData.length === 0 ? (
            <Box textAlign="center" padding="l" color="text-status-inactive">
              {t('common.empty.noDataAvailable')}
            </Box>
          ) : (
            <PieChart
              data={visibleModelData}
              detailPopoverContent={(datum) => [
                { key: t('distributions.popover.count'), value: formatNumber(datum.value) },
                {
                  key: t('distributions.popover.percentage'),
                  value: `${(modelData.find((m) => m.title === datum.title)?.percentage ?? 0).toFixed(1)}%`,
                },
              ]}
              segmentDescription={(datum) =>
                t('distributions.segment.interactions', { count: formatNumber(datum.value) })
              }
              size="large"
              hideFilter
              empty={emptyContent}
              noMatch={emptyContent}
            />
          )}
        </div>
        <div>
          <SpaceBetween size="xs">
            <Header variant="h2">{t('distributions.trigger.title')}</Header>
            {!loading && triggerData.length > 0 && triggerFilter}
          </SpaceBetween>
          {loading ? (
            <Box textAlign="center" padding="l">{t('common.loading')}</Box>
          ) : triggerData.length === 0 ? (
            <Box textAlign="center" padding="l" color="text-status-inactive">
              {t('common.empty.noDataAvailable')}
            </Box>
          ) : (
            <PieChart
              data={visibleTriggerData}
              detailPopoverContent={(datum) => [
                { key: t('distributions.popover.count'), value: formatNumber(datum.value) },
                {
                  key: t('distributions.popover.percentage'),
                  value: `${(triggerData.find((ti) => ti.title === datum.title)?.percentage ?? 0).toFixed(1)}%`,
                },
              ]}
              segmentDescription={(datum) =>
                t('distributions.segment.interactions', { count: formatNumber(datum.value) })
              }
              size="large"
              hideFilter
              empty={emptyContent}
              noMatch={emptyContent}
            />
          )}
        </div>
      </Grid>
      <div>
        <SpaceBetween size="xs">
          <Header
            variant="h2"
            actions={
              <Toggle
                checked={showSystemPrompts}
                onChange={({ detail }) => setShowSystemPrompts(detail.checked)}
              >
                {t('distributions.category.systemToggle')}
              </Toggle>
            }
          >
            {t('distributions.category.title')}
          </Header>
          {!loading && categoryData.length > 0 && categoryFilter}
          {loading ? (
            <Box textAlign="center" padding="l">{t('common.loading')}</Box>
          ) : categoryData.length === 0 ? (
            <Box textAlign="center" padding="l" color="text-status-inactive">
              {t('common.empty.noDataAvailable')}
            </Box>
          ) : (
            <PieChart
              data={visibleCategoryData}
              detailPopoverContent={(datum) => [
                { key: t('distributions.popover.count'), value: formatNumber(datum.value) },
                {
                  key: t('distributions.popover.percentage'),
                  value: `${(visibleCategoryData.find((c) => c.title === datum.title)?.percentage ?? 0).toFixed(1)}%`,
                },
              ]}
              segmentDescription={(datum) =>
                t('distributions.segment.interactions', { count: formatNumber(datum.value) })
              }
              size="large"
              hideFilter
              empty={emptyContent}
              noMatch={emptyContent}
            />
          )}
        </SpaceBetween>
      </div>
    </SpaceBetween>
  );
}
