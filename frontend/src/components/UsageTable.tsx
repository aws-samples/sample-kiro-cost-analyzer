import { useState, useEffect } from 'react';
import Table from '@cloudscape-design/components/table';
import Header from '@cloudscape-design/components/header';
import Pagination from '@cloudscape-design/components/pagination';
import TextFilter from '@cloudscape-design/components/text-filter';
import Box from '@cloudscape-design/components/box';
import Link from '@cloudscape-design/components/link';
import Badge from '@cloudscape-design/components/badge';
import Popover from '@cloudscape-design/components/popover';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { useNavigate } from 'react-router';
import { useI18n } from '../i18n/useI18n';
import { get } from '../api/client';
import TierBadge from './TierBadge';
import RecommendationModal from './RecommendationModal';
import type { UserUsage, TierRecommendation, TierRecommendationsResponse } from '../types';

interface UsageTableProps {
  users: UserUsage[];
  loading: boolean;
}

const PAGE_SIZE = 20;

type SortField = keyof UserUsage;

type FrequencyStatus = 'active' | 'recent' | 'inactive' | 'dormant';

interface FrequencyInfo {
  status: FrequencyStatus;
  color: 'green' | 'blue' | 'red' | 'grey';
}

export function getFrequencyStatus(daysSinceLastActive: number | null | undefined): FrequencyInfo | null {
  if (daysSinceLastActive == null) return null;
  if (daysSinceLastActive <= 3) return { status: 'active', color: 'green' };
  if (daysSinceLastActive <= 14) return { status: 'recent', color: 'blue' };
  if (daysSinceLastActive <= 29) return { status: 'inactive', color: 'red' };
  return { status: 'dormant', color: 'grey' };
}

export default function UsageTable({ users, loading }: UsageTableProps) {
  const navigate = useNavigate();
  const { t, formatNumber, formatDate } = useI18n();
  // Locale-aware decimal formatter — produces pt-BR decimals (vírgula) while
  // `DEFAULT_LOCALE` is pt-BR; flips to en decimals after Step 6. Kept local
  // to the component so it closes over `formatNumber`, which is memoized by
  // `I18nProvider` against the active locale.
  const fmt = (n: number) =>
    formatNumber(n, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const [sortField, setSortField] = useState<SortField>('totalCredits');
  const [sortAsc, setSortAsc] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [filterText, setFilterText] = useState('');
  const [recommendations, setRecommendations] = useState<Map<string, TierRecommendation>>(new Map());
  const [selectedRecommendation, setSelectedRecommendation] = useState<TierRecommendation | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [frequencyFilter, setFrequencyFilter] = useState<SelectProps.Option>({ value: 'all', label: t('users.frequency.filter.all') });

  useEffect(() => {
    get<TierRecommendationsResponse>('/api/recommendations/tier-optimization')
      .then((data) => {
        const map = new Map<string, TierRecommendation>();
        for (const rec of data.recommendations) {
          map.set(rec.userId, rec);
        }
        setRecommendations(map);
      })
      .catch(() => {
        // Gracefully hide badges when API returns error
      });
  }, []);

  const frequencyFilterOptions: SelectProps.Options = [
    { value: 'all', label: t('users.frequency.filter.all') },
    { value: 'active', label: t('users.frequency.active') },
    { value: 'recent', label: t('users.frequency.recent') },
    { value: 'inactive', label: t('users.frequency.inactive') },
    { value: 'dormant', label: t('users.frequency.dormant') },
  ];

  const textFiltered = filterText
    ? users.filter(
        (u) =>
          u.userId.toLowerCase().includes(filterText.toLowerCase()) ||
          u.subscriptionTier.toLowerCase().includes(filterText.toLowerCase()) ||
          (u.displayName ?? '').toLowerCase().includes(filterText.toLowerCase()),
      )
    : users;

  const filtered = frequencyFilter.value === 'all'
    ? textFiltered
    : textFiltered.filter((u) => {
        const freq = getFrequencyStatus(u.daysSinceLastActive);
        return freq?.status === frequencyFilter.value;
      });

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortField];
    const bv = b[sortField];
    if (typeof av === 'number' && typeof bv === 'number') {
      return sortAsc ? av - bv : bv - av;
    }
    return sortAsc
      ? String(av).localeCompare(String(bv))
      : String(bv).localeCompare(String(av));
  });

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const paged = sorted.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  return (
    <>
      <Table
        loading={loading}
        loadingText={t('usageTable.loading')}
        header={<Header counter={`(${filtered.length})`}>{t('usageTable.title')}</Header>}
        empty={
          <Box textAlign="center" color="inherit">
            <b>{t('usageTable.empty.title')}</b>
            <Box padding={{ bottom: 's' }} variant="p" color="inherit">
              {t('usageTable.empty.description')}
            </Box>
          </Box>
        }
        sortingColumn={{ sortingField: sortField }}
        sortingDescending={!sortAsc}
        onSortingChange={({ detail }) => {
          const field = detail.sortingColumn.sortingField as SortField;
          if (field === sortField) {
            setSortAsc(!detail.isDescending);
          } else {
            setSortField(field);
            setSortAsc(!detail.isDescending);
          }
          setCurrentPage(1);
        }}
        filter={
          <SpaceBetween size="xs" direction="horizontal">
            <TextFilter
              filteringText={filterText}
              filteringPlaceholder={t('usageTable.filter.placeholder')}
              onChange={({ detail }) => {
                setFilterText(detail.filteringText);
                setCurrentPage(1);
              }}
            />
            <div style={{ minWidth: 180 }}>
              <Select
                selectedOption={frequencyFilter}
                onChange={({ detail }) => {
                  setFrequencyFilter(detail.selectedOption);
                  setCurrentPage(1);
                }}
                options={frequencyFilterOptions}
                placeholder={t('users.frequency.filter.label')}
              />
            </div>
          </SpaceBetween>
        }
        pagination={
          <Pagination
            currentPageIndex={currentPage}
            pagesCount={totalPages || 1}
            onChange={({ detail }) => setCurrentPage(detail.currentPageIndex)}
          />
        }
      columnDefinitions={[
        {
          id: 'userId',
          header: t('usageTable.header.user'),
          cell: (item) => {
            const rec = recommendations.get(item.userId) ?? null;
            return (
              <>
                <Link
                  href={`/user/${item.userId}`}
                  onFollow={(e) => {
                    e.preventDefault();
                    navigate(`/user/${item.userId}`);
                  }}
                >
                  {item.displayName || item.userId}
                </Link> &nbsp;
                <TierBadge
                  recommendation={rec}
                  onClick={() => {
                    setSelectedRecommendation(rec);
                    setModalVisible(true);
                  }}
                />
                {item.tombstoned && (
                  <>
                    {' '}
                    <Popover
                      dismissButton={false}
                      position="top"
                      size="medium"
                      triggerType="custom"
                      header={t('users.tombstone.tooltip.header')}
                      content={t('users.tombstone.tooltip.body')}
                    >
                      <Badge color="grey">{t('users.tombstone.badge')}</Badge>
                    </Popover>
                  </>
                )}
                {item.displayName && (
                  <Box variant="small" color="text-body-secondary">{item.userId}</Box>
                )}
              </>
            );
          },
          sortingField: 'userId',
          width: 280,
        },
        {
          id: 'frequencyStatus',
          header: t('users.frequency.filter.label'),
          cell: (item) => {
            const freq = getFrequencyStatus(item.daysSinceLastActive);
            if (!freq) return '—';
            const colorMap: Record<string, string> = {
              green: 'color-text-status-success',
              blue: 'color-text-status-info',
              red: 'color-text-status-error',
              grey: 'color-text-status-inactive',
            };
            return (
              <Box color={colorMap[freq.color] as any}>
                {t(`users.frequency.${freq.status}`)}
              </Box>
            );
          },
          width: 130,
        },
        {
          id: 'subscriptionTier',
          header: t('usageTable.header.tier'),
          cell: (item) => item.subscriptionTier,
          sortingField: 'subscriptionTier',
          width: 120,
        },
        {
          id: 'totalCredits',
          header: t('usageTable.header.totalCredits'),
          cell: (item) => fmt(item.totalCredits),
          sortingField: 'totalCredits',
          width: 140,
        },
        {
          id: 'overageCredits',
          header: t('usageTable.header.overageCredits'),
          cell: (item) => fmt(item.overageCredits),
          sortingField: 'overageCredits',
          width: 150,
        },
        {
          id: 'totalMessages',
          header: t('usageTable.header.totalMessages'),
          cell: (item) => formatNumber(item.totalMessages),
          sortingField: 'totalMessages',
          width: 140,
        },
        {
          id: 'totalConversations',
          header: t('usageTable.header.totalConversations'),
          cell: (item) => formatNumber(item.totalConversations),
          sortingField: 'totalConversations',
          width: 140,
        },
        {
          id: 'averageDailyCredits',
          header: t('usageTable.header.averageDaily'),
          cell: (item) => fmt(item.averageDailyCredits),
          sortingField: 'averageDailyCredits',
          width: 130,
        },
        {
          id: 'lastActive',
          header: t('users.column.lastActive'),
          cell: (item) => item.lastActiveDate ? formatDate(item.lastActiveDate) : '—',
          sortingField: 'lastActiveDate',
          width: 130,
        },
        {
          id: 'daysAgo',
          header: t('users.column.daysAgo'),
          cell: (item) => item.daysSinceLastActive != null ? formatNumber(item.daysSinceLastActive) : '—',
          sortingField: 'daysSinceLastActive',
          width: 100,
        },
      ]}
      items={paged}
    />
      <RecommendationModal
        recommendation={selectedRecommendation}
        visible={modalVisible}
        onDismiss={() => {
          setModalVisible(false);
          setSelectedRecommendation(null);
        }}
      />
    </>
  );
}
