import { useState, useEffect, useCallback } from 'react';
import Table from '@cloudscape-design/components/table';
import Header from '@cloudscape-design/components/header';
import Pagination from '@cloudscape-design/components/pagination';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import { type DateRangePickerProps } from '@cloudscape-design/components/date-range-picker';
import { useI18n } from '../i18n/useI18n';
import { get, ApiError } from '../api/client';
import type { PromptMetadata, PromptsListResponse } from '../types';

const SYSTEM_CATEGORIES = ['Empty', 'NOT_CATEGORIZED', 'Classification Error'];
const PAGE_SIZES = [10, 20, 50];
const DEFAULT_PAGE_SIZE = 20;

interface PromptsTableProps {
  userId: string;
  dateRange: DateRangePickerProps.Value | null;
  onSelectPrompt?: (requestId: string) => void;
}

function toDateStr(d: Date): string {
  return d.toISOString().split('T')[0];
}

function getDateParams(dateRange: DateRangePickerProps.Value | null): Record<string, string> {
  const params: Record<string, string> = {};
  if (!dateRange) return params;
  if (dateRange.type === 'absolute') {
    params.startDate = dateRange.startDate;
    params.endDate = dateRange.endDate;
  } else if (dateRange.type === 'relative') {
    const now = new Date();
    const end = toDateStr(now);
    const start = new Date(now);
    const amount = dateRange.amount;
    switch (dateRange.unit) {
      case 'day': start.setDate(start.getDate() - amount); break;
      case 'week': start.setDate(start.getDate() - amount * 7); break;
      case 'month': start.setMonth(start.getMonth() - amount); break;
      case 'year': start.setFullYear(start.getFullYear() - amount); break;
    }
    params.startDate = toDateStr(start);
    params.endDate = end;
  }
  return params;
}

/**
 * Truncates a string to maxLen characters, appending ellipsis if truncated.
 */
export function truncatePreview(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '…';
}

export default function PromptsTable({ userId, dateRange, onSelectPrompt }: PromptsTableProps) {
  const { t, formatDateTime } = useI18n();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [currentPage, setCurrentPage] = useState(1);
  const [categoryFilter, setCategoryFilter] = useState<SelectProps.Option>({
    value: '__all__',
    label: t('prompts.filter.category'),
  });
  const [selectedItems, setSelectedItems] = useState<PromptMetadata[]>([]);

  // All pages of items fetched so far (for client-side pagination within fetched data)
  const [allItems, setAllItems] = useState<PromptMetadata[]>([]);

  const fetchPrompts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {
        userId,
        limit: '100',
        ...getDateParams(dateRange),
      };

      const response = await get<PromptsListResponse>('/api/prompts', params);

      if (import.meta.env.DEV) {
        console.log('PromptsTable: fetched prompts count', response.items.length);
      }

      setAllItems(response.items);
      setCurrentPage(1);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : t('prompts.error');
      setError(message);
      setAllItems([]);
    } finally {
      setLoading(false);
    }
  }, [userId, dateRange, t]);

  useEffect(() => {
    fetchPrompts();
  }, [fetchPrompts]);

  // Filter out system categories by default, then apply category filter
  const filteredItems = allItems.filter((item) => {
    // Exclude system categories by default
    if (SYSTEM_CATEGORIES.includes(item.category)) return false;
    // Apply category filter if set
    if (categoryFilter.value !== '__all__' && item.category !== categoryFilter.value) return false;
    return true;
  });

  // Compute available categories for the filter (excluding system categories)
  const availableCategories = Array.from(
    new Set(allItems.filter((i) => !SYSTEM_CATEGORIES.includes(i.category)).map((i) => i.category))
  ).sort();

  const categoryOptions: SelectProps.Options = [
    { value: '__all__', label: t('prompts.filter.category') },
    ...availableCategories.map((cat) => ({ value: cat, label: cat })),
  ];

  // Pagination
  const totalPages = Math.max(1, Math.ceil(filteredItems.length / pageSize));
  const pagedItems = filteredItems.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  const pageSizeOptions: SelectProps.Options = PAGE_SIZES.map((size) => ({
    value: String(size),
    label: t('prompts.pagination.pageSize', { count: size }),
  }));

  const handleSelectionChange = (detail: { selectedItems: PromptMetadata[] }) => {
    setSelectedItems(detail.selectedItems);
    if (detail.selectedItems.length > 0 && onSelectPrompt) {
      onSelectPrompt(detail.selectedItems[0].requestId);
    }
  };

  return (
    <SpaceBetween size="m">
      {error && (
        <Alert
          type="error"
          action={<Button onClick={fetchPrompts}>{t('prompts.retry')}</Button>}
        >
          {error}
        </Alert>
      )}
      <Table
        loading={loading}
        loadingText={t('prompts.title')}
        header={
          <Header counter={`(${filteredItems.length})`}>
            {t('prompts.title')}
          </Header>
        }
        empty={
          <Box textAlign="center" color="inherit">
            <b>{t('prompts.empty.title')}</b>
            <Box padding={{ bottom: 's' }} variant="p" color="inherit">
              {t('prompts.empty.description')}
            </Box>
          </Box>
        }
        selectionType="single"
        selectedItems={selectedItems}
        onSelectionChange={({ detail }) => handleSelectionChange(detail)}
        filter={
          <SpaceBetween size="xs" direction="horizontal">
            <div style={{ minWidth: 200 }}>
              <Select
                selectedOption={categoryFilter}
                onChange={({ detail }) => {
                  setCategoryFilter(detail.selectedOption);
                  setCurrentPage(1);
                }}
                options={categoryOptions}
                placeholder={t('prompts.filter.category')}
              />
            </div>
            <div style={{ minWidth: 150 }}>
              <Select
                selectedOption={{
                  value: String(pageSize),
                  label: t('prompts.pagination.pageSize', { count: pageSize }),
                }}
                onChange={({ detail }) => {
                  setPageSize(Number(detail.selectedOption.value));
                  setCurrentPage(1);
                }}
                options={pageSizeOptions}
              />
            </div>
          </SpaceBetween>
        }
        pagination={
          <Pagination
            currentPageIndex={currentPage}
            pagesCount={totalPages}
            onChange={({ detail }) => setCurrentPage(detail.currentPageIndex)}
          />
        }
        columnDefinitions={[
          {
            id: 'promptPreview',
            header: t('prompts.column.content'),
            cell: (item) => truncatePreview(item.promptPreview, 100),
            width: 400,
          },
          {
            id: 'dateTime',
            header: t('prompts.column.dateTime'),
            cell: (item) => formatDateTime(new Date(item.timestamp)),
            width: 180,
          },
          {
            id: 'category',
            header: t('prompts.column.category'),
            cell: (item) => item.category,
            width: 160,
          },
        ]}
        items={pagedItems}
      />
    </SpaceBetween>
  );
}
