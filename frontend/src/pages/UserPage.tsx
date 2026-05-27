import { useEffect, useState, useCallback, useMemo } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Tabs, { type TabsProps } from '@cloudscape-design/components/tabs';
import { type DateRangePickerProps } from '@cloudscape-design/components/date-range-picker';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Table from '@cloudscape-design/components/table';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import SplitPanel from '@cloudscape-design/components/split-panel';
import UserSummaryCards from '../components/UserSummaryCards';
import DailyUsageChart from '../components/DailyUsageChart';
import DistributionCharts from '../components/DistributionCharts';
import SkeletonLoader from '../components/SkeletonLoader';
import ActivityTimelineChart from '../components/ActivityTimelineChart';
import LocalizedDateRangePicker, { DEFAULT_DATE_RANGE } from '../components/LocalizedDateRangePicker';
import PromptsTable from '../components/PromptsTable';
import PromptDetailPanel from '../components/PromptDetailPanel';
import { useLastUpdated } from '../hooks/useLastUpdated';
import { useSplitPanel } from '../hooks/useSplitPanel';
import { useAuth } from '../auth/useAuth';
import { useI18n } from '../i18n/useI18n';
import { get, ApiError } from '../api/client';
import { getAgentCorrelationWithPolling } from '../api/gitApi';
import type {
  UserDetailResponse,
  AppConfig,
  CorrelationAnalysis,
  CorrelationItem,
  CorrelationStatusSlug,
  ActivityTimelineEntry,
  CategoryDistribution,
} from '../types';
import type { TranslationKey } from '../locales/keys';

function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
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

function impactLevelLabel(level: string | null): string {
  switch (level) {
    case 'veryHigh': return 'Very High';
    case 'high': return 'High';
    case 'moderate': return 'Moderate';
    case 'low': return 'Low';
    default: return '—';
  }
}

// ── Slug -> translation key map ─────────────────────────────────────────────
// Built at module scope so React does not rebuild it on every render.
const slugToTranslationKey: Record<CorrelationStatusSlug, TranslationKey> = {
  GIT_MAPPING_MISSING: 'productivity.correlation.status.gitMappingMissing',
  GITHUB_TOKEN_MISSING: 'productivity.correlation.status.githubTokenMissing',
  GITHUB_AUTH_FAILED: 'productivity.correlation.status.githubAuthFailed',
  GITHUB_RATE_LIMIT: 'productivity.correlation.status.githubRateLimit',
  INSUFFICIENT_DATA: 'productivity.correlation.status.insufficientData',
  AGENT_TIMEOUT: 'productivity.correlation.status.agentTimeout',
  AGENT_ERROR: 'productivity.correlation.status.agentError',
};

// ── Slug -> Cloudscape Alert severity map ──────────────────────────────────
// Severity follows the design's "Frontend-Level Errors" table:
//   info    — informational / user can act
//   warning — actionable, blocks analysis until the user fixes it
//   error   — the analysis operation actually failed
const slugToAlertType: Record<CorrelationStatusSlug, 'info' | 'warning' | 'error'> = {
  GIT_MAPPING_MISSING: 'info',
  GITHUB_TOKEN_MISSING: 'warning',
  GITHUB_AUTH_FAILED: 'warning',
  GITHUB_RATE_LIMIT: 'info',
  INSUFFICIENT_DATA: 'info',
  AGENT_TIMEOUT: 'error',
  AGENT_ERROR: 'error',
};

// Slugs where retrying makes sense without the user first changing settings.
// For GIT_MAPPING_MISSING / GITHUB_TOKEN_MISSING / GITHUB_AUTH_FAILED the
// user must update Settings first, so no refresh action is offered.
const RETRYABLE_SLUGS: ReadonlySet<CorrelationStatusSlug> = new Set<CorrelationStatusSlug>([
  'GITHUB_RATE_LIMIT',
  'INSUFFICIENT_DATA',
  'AGENT_TIMEOUT',
  'AGENT_ERROR',
]);

function isStatusSlug(s: string | undefined): s is CorrelationStatusSlug {
  return s !== undefined && s !== 'ready' && s !== 'processing' && s in slugToTranslationKey;
}

export default function UserPage() {
  const { userId } = useParams<{ userId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { t, formatDateTime, formatNumber, locale } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.groups?.includes('Admins') ?? false;
  const { setSplitPanelContent, setSplitPanelOpen, closeSplitPanel } = useSplitPanel();

  const activeTab = searchParams.get('tab') || 'productivity';

  const [dateRange, setDateRange] = useState<DateRangePickerProps.Value | null>(DEFAULT_DATE_RANGE);

  // ── Prompt history feature flag state ────────────────────────────────────
  const [promptHistoryEnabled, setPromptHistoryEnabled] = useState(false);
  const [, setSelectedPromptId] = useState<string | null>(null);

  // ── Usage tab state ──────────────────────────────────────────────────────
  const [usageData, setUsageData] = useState<UserDetailResponse | undefined>();
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [isServerError, setIsServerError] = useState(false);
  const [usageLoaded, setUsageLoaded] = useState(false);

  // ── Productivity tab state ───────────────────────────────────────────────
  const [analysis, setAnalysis] = useState<CorrelationAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisPolling, setAnalysisPolling] = useState(false);
  const [productivityDetail, setProductivityDetail] = useState<UserDetailResponse | null>(null);
  const [productivityDetailLoading, setProductivityDetailLoading] = useState(false);
  const [productivityDetailError, setProductivityDetailError] = useState<string | null>(null);
  const [productivityLoaded, setProductivityLoaded] = useState(false);

  const { formattedTime, markUpdated } = useLastUpdated();

  // ── Fetch: prompt history feature flag ───────────────────────────────────
  useEffect(() => {
    if (!isAdmin) return;
    get<AppConfig>('/api/config')
      .then((config) => {
        setPromptHistoryEnabled(config.promptHistoryEnabled ?? false);
      })
      .catch(() => {
        setPromptHistoryEnabled(false);
      });
  }, [isAdmin]);

  // ── Prompt selection handler for SplitPanel ──────────────────────────────
  const handleSelectPrompt = useCallback((requestId: string) => {
    if (!userId) return;
    setSelectedPromptId(requestId);
    setSplitPanelContent(
      <SplitPanel header={t('promptDetail.header', { category: requestId })}>
        <PromptDetailPanel
          requestId={requestId}
          userId={userId}
          onClose={() => {
            setSelectedPromptId(null);
            closeSplitPanel();
          }}
        />
      </SplitPanel>
    );
    setSplitPanelOpen(true);
  }, [userId, t, setSplitPanelContent, setSplitPanelOpen, closeSplitPanel]);

  // ── Clean up SplitPanel on unmount ───────────────────────────────────────
  useEffect(() => {
    return () => {
      closeSplitPanel();
    };
  }, [closeSplitPanel]);

  // ── Fetch: usage details ─────────────────────────────────────────────────
  const fetchUsage = useCallback(async () => {
    if (!userId) return;
    setUsageLoading(true);
    setUsageError(null);
    setIsServerError(false);
    try {
      const resp = await get<UserDetailResponse>(`/api/usage/${userId}/details`, getDateParams(dateRange));
      setUsageData(resp);
      markUpdated();
    } catch (err) {
      if (err instanceof ApiError && err.isServerError) {
        setIsServerError(true);
        setUsageError(err.message);
      } else {
        setUsageError(err instanceof Error ? err.message : t('userDetail.error.load'));
      }
    } finally {
      setUsageLoading(false);
    }
  }, [userId, dateRange, markUpdated, t]);

  // ── Fetch: productivity detail ───────────────────────────────────────────
  const fetchProductivityDetail = useCallback(async () => {
    if (!userId) return;
    setProductivityDetailLoading(true);
    setProductivityDetailError(null);
    try {
      const resp = await get<UserDetailResponse>(`/api/usage/${userId}/details`, getDateParams(dateRange));
      setProductivityDetail(resp);
    } catch (err) {
      setProductivityDetailError(err instanceof Error ? err.message : t('productivity.error.load'));
    } finally {
      setProductivityDetailLoading(false);
    }
  }, [userId, dateRange, t]);

  const fetchAnalysis = useCallback(async (forceRefresh = false) => {
    if (!userId) return;
    setAnalysisLoading(true);
    setAnalysisPolling(false);
    setAnalysisError(null);
    try {
      const params: Record<string, string> = { ...getDateParams(dateRange) };
      if (forceRefresh) params.forceRefresh = 'true';
      const result = await getAgentCorrelationWithPolling(
        userId,
        params,
        () => setAnalysisPolling(true),
      );
      setAnalysis(result);
    } catch (err) {
      if (err instanceof Error && err.message === 'POLL_TIMEOUT') {
        setAnalysisError(t('productivity.correlation.pollTimeout'));
      } else {
        setAnalysisError(err instanceof Error ? err.message : t('productivity.error.load'));
      }
    } finally {
      setAnalysisLoading(false);
      setAnalysisPolling(false);
    }
  }, [userId, dateRange, t]);

  // ── Lazy-load: productivity tab ──────────────────────────────────────────
  useEffect(() => {
    if (activeTab === 'productivity' && !productivityLoaded && userId) {
      setProductivityLoaded(true);
      fetchProductivityDetail();
      fetchAnalysis();
    }
  }, [activeTab, productivityLoaded, userId, fetchProductivityDetail, fetchAnalysis]);

  // ── Lazy-load: usage tab ─────────────────────────────────────────────────
  useEffect(() => {
    if (activeTab === 'usage' && !usageLoaded && userId) {
      setUsageLoaded(true);
      fetchUsage();
    }
  }, [activeTab, usageLoaded, userId, fetchUsage]);

  // ── Reset loaded flags when date range changes ───────────────────────────
  useEffect(() => {
    setProductivityLoaded(false);
    setUsageLoaded(false);
  }, [dateRange]);

  // ── Re-fetch active tab when loaded flags reset ──────────────────────────
  useEffect(() => {
    if (activeTab === 'productivity' && !productivityLoaded && userId) {
      setProductivityLoaded(true);
      fetchProductivityDetail();
      fetchAnalysis();
    } else if (activeTab === 'usage' && !usageLoaded && userId) {
      setUsageLoaded(true);
      fetchUsage();
    }
  }, [activeTab, productivityLoaded, usageLoaded, userId, fetchProductivityDetail, fetchAnalysis, fetchUsage]);

  // ── Tab change handler ───────────────────────────────────────────────────
  const handleTabChange = useCallback((tabId: string) => {
    setSearchParams({ tab: tabId });
  }, [setSearchParams]);

  // ── Productivity tab computed values ─────────────────────────────────────
  const activityTimeline = useMemo<ActivityTimelineEntry[]>(() => {
    if (!productivityDetail?.dailyUsage) return [];
    return productivityDetail.dailyUsage.map((entry) => ({
      date: entry.date,
      interactions: entry.interactions,
      messages: entry.messages ?? 0,
      conversations: 0,
    }));
  }, [productivityDetail]);

  const summaryItems = useMemo(() => {
    if (!productivityDetail) return null;
    const { summary, dailyUsage } = productivityDetail;
    const totalInteractions = summary.totalInteractions;
    const totalPrompts = summary.totalMessages;
    const daysActive = dailyUsage.filter((d) => d.interactions > 0).length;
    const avgDaily = daysActive > 0 ? totalInteractions / daysActive : 0;
    return { totalInteractions, totalPrompts, daysActive, avgDaily };
  }, [productivityDetail]);

  // ── Header info ──────────────────────────────────────────────────────────
  const displayName = usageData?.displayName || productivityDetail?.displayName || '';
  const subscriptionTier = usageData?.subscriptionTier || productivityDetail?.subscriptionTier || '';
  const headerTitle = displayName || (userId ?? '');
  const headerDescription = [
    subscriptionTier ? t('userDetail.header.tier', { tier: subscriptionTier }) : '',
    t('userDetail.header.userId', { userId: userId ?? '' }),
    formattedTime ? t('common.lastUpdated', { time: formattedTime }) : '',
  ].filter(Boolean).join(' — ');

  const handleRefresh = useCallback(() => {
    if (activeTab === 'productivity') {
      fetchProductivityDetail();
      fetchAnalysis();
    } else {
      fetchUsage();
    }
  }, [activeTab, fetchProductivityDetail, fetchAnalysis, fetchUsage]);

  // ── Productivity tab content ─────────────────────────────────────────────
  const localizedInsights = analysis?.insights?.[locale] ?? analysis?.insights?.en ?? [];

  const productivityContent = (
    <SpaceBetween size="l">
      {productivityDetailError && (
        <Alert type="error" dismissible onDismiss={() => setProductivityDetailError(null)}>
          {productivityDetailError}
        </Alert>
      )}

      {analysisError && (
        <Alert type="error" dismissible onDismiss={() => setAnalysisError(null)}>
          {analysisError}
        </Alert>
      )}

      {/* Summary Cards */}
      {summaryItems && (
        <Container header={<Header variant="h2">{t('productivity.overview.summaryTitle')}</Header>}>
          <KeyValuePairs
            columns={4}
            items={[
              {
                label: t('productivity.overview.totalInteractions'),
                value: formatNumber(summaryItems.totalInteractions),
              },
              {
                label: t('productivity.overview.totalPrompts'),
                value: formatNumber(summaryItems.totalPrompts),
              },
              {
                label: t('productivity.overview.daysActive'),
                value: formatNumber(summaryItems.daysActive),
              },
              {
                label: t('productivity.overview.avgDailyInteractions'),
                value: formatNumber(summaryItems.avgDaily, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
              },
            ]}
          />
        </Container>
      )}

      {/* Activity Timeline Chart */}
      {(productivityDetailLoading || activityTimeline.length > 0) && (
        <Container>
          <ActivityTimelineChart timeline={activityTimeline} loading={productivityDetailLoading} />
        </Container>
      )}

      {/* Category Distribution Table */}
      {productivityDetail && (productivityDetail.categoryDistribution?.length ?? 0) > 0 && (
        <Table<CategoryDistribution>
          header={
            <Header variant="h2" description={t('productivity.categoryBreakdown.description')}>
              {t('productivity.categoryBreakdown.title')}
            </Header>
          }
          items={[...(productivityDetail.categoryDistribution || [])].sort((a, b) => b.percentage - a.percentage)}
          loading={productivityDetailLoading}
          loadingText={t('productivity.categoryBreakdown.loading')}
          sortingDisabled={false}
          columnDefinitions={[
            {
              id: 'category',
              header: t('productivity.categoryBreakdown.header.category'),
              cell: (item) => item.category,
              sortingField: 'category',
              width: 250,
            },
            {
              id: 'count',
              header: t('productivity.categoryBreakdown.header.count'),
              cell: (item) => formatNumber(item.count),
              sortingField: 'count',
              width: 120,
            },
            {
              id: 'percentage',
              header: t('productivity.categoryBreakdown.header.percentage'),
              cell: (item) => `${item.percentage.toFixed(1)}%`,
              sortingField: 'percentage',
              width: 120,
            },
          ]}
          empty={
            <Box textAlign="center" padding="l" color="text-status-inactive">
              {t('productivity.categoryBreakdown.empty.title')}
            </Box>
          }
        />
      )}

      {/* Impact Score + Refresh */}
      {analysisLoading && (
        <Container>
          <StatusIndicator type="loading">
            {analysisPolling
              ? t('productivity.correlation.polling')
              : t('productivity.correlation.analyzing')}
          </StatusIndicator>
        </Container>
      )}

      {analysis && !analysisLoading && (
        <SpaceBetween size="l">
          {isStatusSlug(analysis.status) && !analysis.impactScore && (
            <Alert
              type={slugToAlertType[analysis.status]}
              action={
                RETRYABLE_SLUGS.has(analysis.status) ? (
                  <Button iconName="refresh" onClick={() => fetchAnalysis(true)} loading={analysisLoading}>
                    {t('productivity.correlation.refresh')}
                  </Button>
                ) : undefined
              }
            >
              {t(slugToTranslationKey[analysis.status])}
            </Alert>
          )}

          {analysis.impactScore !== null && (
            <Container
              header={
                <Header
                  variant="h2"
                  description={t('productivity.correlation.generatedByAi')}
                  actions={
                    <SpaceBetween size="xs" direction="horizontal">
                      {analysis.cached && analysis.analyzedAt && (
                        <StatusIndicator type="info">
                          {t('productivity.correlation.cached')} — {formatDateTime(analysis.analyzedAt)}
                        </StatusIndicator>
                      )}
                      {!analysis.cached && analysis.analyzedAt && (
                        <StatusIndicator type="success">
                          {t('productivity.correlation.updated')} — {formatDateTime(analysis.analyzedAt)}
                        </StatusIndicator>
                      )}
                      <Button
                        iconName="refresh"
                        loading={analysisLoading}
                        onClick={() => fetchAnalysis(true)}
                      >
                        {t('productivity.correlation.refresh')}
                      </Button>
                    </SpaceBetween>
                  }
                >
                  {t('productivity.correlation.impactScore')}
                </Header>
              }
            >
              <SpaceBetween size="l">
                <SpaceBetween size="s">
                  <ProgressBar
                    value={analysis.impactScore}
                  />
                  <Box variant="p">
                    <Box variant="strong" display="inline">{impactLevelLabel(analysis.impactLevel)}</Box>
                    {' — '}
                    {t('productivity.correlation.period', {
                      startDate: analysis.period.startDate || '',
                      endDate: analysis.period.endDate || '',
                    })}
                  </Box>
                </SpaceBetween>

                {/* Insights — below impact score */}
                {localizedInsights.length > 0 && (
                  <SpaceBetween size="m">
                    <Header variant="h3">{t('productivity.correlation.insights.title')}</Header>
                    {localizedInsights.map((insight, idx) => {
                      const cleaned = insight.replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{200D}\u{20E3}\u{E0020}-\u{E007F}]/gu, '').trim();
                      const colonIdx = cleaned.indexOf(':');
                      const hasTitle = colonIdx > 0 && colonIdx < 60;
                      const title = hasTitle ? cleaned.slice(0, colonIdx).trim() : null;
                      const text = hasTitle ? cleaned.slice(colonIdx + 1).trim() : cleaned;

                      return (
                        <div key={idx}>
                          {title && <Box variant="h4">{title}</Box>}
                          <Box variant="p" color="text-body-secondary">{text}</Box>
                        </div>
                      );
                    })}
                  </SpaceBetween>
                )}
              </SpaceBetween>
            </Container>
          )}

          {/* Correlations Table */}
          {analysis.correlations.length > 0 && (
            <Table<CorrelationItem>
              header={<Header variant="h2">{t('productivity.correlation.correlations.title')}</Header>}
              items={analysis.correlations}
              wrapLines
              columnDefinitions={[
                {
                  id: 'prompt',
                  header: t('productivity.correlation.prompt'),
                  cell: (item) => item.promptSummary,
                },
                {
                  id: 'git',
                  header: t('productivity.correlation.gitActivity'),
                  cell: (item) => item.gitActivity,
                },
                {
                  id: 'confidence',
                  header: t('productivity.correlation.confidence'),
                  cell: (item) => `${Math.round(item.confidence * 100)}%`,
                  width: 100,
                },
                {
                  id: 'type',
                  header: t('productivity.correlation.type'),
                  cell: (item) => item.type === 'prompt_to_commit'
                    ? t('productivity.correlation.type.commit')
                    : t('productivity.correlation.type.pr'),
                  width: 100,
                },
              ]}
            />
          )}
        </SpaceBetween>
      )}

      {!productivityDetail && !productivityDetailLoading && !analysisLoading && !productivityDetailError && (
        <Box textAlign="center" padding="l" color="text-status-inactive">
          {t('common.loading')}
        </Box>
      )}
    </SpaceBetween>
  );

  // ── Usage tab content ────────────────────────────────────────────────────
  const usageContent = (
    <SpaceBetween size="l">
      {usageError && (
        <Alert type="error" dismissible onDismiss={() => setUsageError(null)}
          action={isServerError ? <Button onClick={fetchUsage}>{t('common.retry')}</Button> : undefined}>
          {usageError}
        </Alert>
      )}
      {usageLoading && !usageData ? (
        <SpaceBetween size="l">
          <SkeletonLoader variant="key-value" columns={4} />
          <SkeletonLoader variant="chart" height={300} />
          <SkeletonLoader variant="chart" height={300} />
          <SkeletonLoader variant="table" count={5} />
        </SpaceBetween>
      ) : usageData ? (
        <SpaceBetween size="l">
          <UserSummaryCards summary={usageData.summary} loading={usageLoading} />
          <DailyUsageChart data={usageData.dailyUsage} loading={usageLoading} />
          <DistributionCharts
            modelDistribution={usageData.modelDistribution}
            triggerDistribution={usageData.triggerDistribution}
            categoryDistribution={usageData.categoryDistribution ?? []}
            loading={usageLoading}
          />
          {promptHistoryEnabled && isAdmin && userId && (
            <PromptsTable
              userId={userId}
              dateRange={dateRange}
              onSelectPrompt={handleSelectPrompt}
            />
          )}
        </SpaceBetween>
      ) : !usageError ? (
        <Box textAlign="center" padding="l" color="text-status-inactive">
          {t('userDetail.empty')}
        </Box>
      ) : null}
    </SpaceBetween>
  );

  // ── Tabs definition ──────────────────────────────────────────────────────
  const tabs: TabsProps.Tab[] = [
    {
      id: 'productivity',
      label: t('userPage.tab.productivity'),
      content: productivityContent,
    },
    {
      id: 'usage',
      label: t('userPage.tab.usage'),
      content: usageContent,
    },
  ];

  return (
    <ContentLayout
      header={
        <SpaceBetween size="s">
          <BreadcrumbGroup
            items={[
              { text: t('nav.dashboard'), href: '/' },
              { text: t('userDetail.breadcrumb'), href: '#' },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              if (e.detail.href === '/') navigate('/');
            }}
          />
          <Header
            variant="h1"
            description={headerDescription}
            actions={
              <SpaceBetween size="s" direction="horizontal">
                <div style={{ minWidth: 280 }}>
                  <LocalizedDateRangePicker
                    value={dateRange}
                    onChange={(value) => setDateRange(value)}
                  />
                </div>
                <Button iconName="refresh" onClick={handleRefresh} loading={usageLoading || productivityDetailLoading}>
                  {t('common.refresh')}
                </Button>
                <Button iconName="arrow-left" onClick={() => navigate('/')}>
                  {t('common.back')}
                </Button>
              </SpaceBetween>
            }
          >
            {headerTitle}
          </Header>
        </SpaceBetween>
      }
    >
      <Tabs
        activeTabId={activeTab}
        onChange={({ detail }) => handleTabChange(detail.activeTabId)}
        tabs={tabs}
      />
    </ContentLayout>
  );
}
