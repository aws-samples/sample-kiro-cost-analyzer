export interface UserUsage {
  userId: string;
  displayName: string;
  userName: string;
  subscriptionTier: string;
  totalCredits: number;
  overageCredits: number;
  totalMessages: number;
  totalConversations: number;
  averageDailyCredits: number;
  lastActiveDate?: string | null;
  daysSinceLastActive?: number | null;
  /** True when the user has been removed from Identity Center.
   *  Surfaced only by the historical Users tab; actionable views
   *  (Recommendations, Inactive subscribers) filter these out. */
  tombstoned?: boolean;
}

export interface UsageSummary {
  totalUsers: number;
  totalCredits: number;
  totalOverageCredits: number;
  averageCreditsPerUser: number;
}

export interface UsageResponse {
  summary: UsageSummary;
  users: UserUsage[];
  period: { startDate?: string; endDate?: string };
}

export interface AccountTotals {
  totalCredits: number;
  totalOverageCredits: number;
  totalMessages: number;
  totalConversations: number;
}

export interface TimelineEntry {
  period: string;
  totalCredits: number;
  totalOverageCredits: number;
  totalMessages: number;
  totalConversations: number;
}

export interface TierBreakdown {
  subscriptionTier: string;
  totalCredits: number;
  totalOverageCredits: number;
  totalMessages: number;
}

export interface ClientTypeBreakdown {
  clientType: string;
  totalCredits: number;
  totalOverageCredits: number;
  totalMessages: number;
}

export interface AccountUsageResponse {
  totals: AccountTotals;
  timeline: TimelineEntry[];
  breakdownByTier: TierBreakdown[];
  breakdownByClientType: ClientTypeBreakdown[];
  period: { startDate?: string; endDate?: string; granularity: string };
}

export interface EtlStatus {
  lastExecution: string | null;
  status: string;
  filesProcessed: number;
  recordsWritten: number;
  errors: string[];
}

export interface EtlSchedule {
  expression: string | null;
  enabled: boolean;
  humanReadable: string;
  error?: boolean;
}

export interface AppConfig {
  bucketName: string;
  sourcePrefix: string;
  promptsPrefix: string;
  identityStoreId: string;
  sourceBucketRoleArn?: string;
  identityStoreRoleArn?: string;
  etlStatus: EtlStatus;
  promptHistoryEnabled: boolean;
}

export interface CognitoUser {
  username: string;
  email: string;
  status: string;
  enabled: boolean;
  createdAt: string;
}

export interface DailyUsageEntry {
  date: string;
  credits: number;
  interactions: number;
  costPerInteraction: number | null;
  messages: number;
  overageCredits: number;
}

export interface ModelDistribution {
  modelId: string;
  count: number;
  percentage: number;
}

export interface CategoryDistribution {
  category: string;
  count: number;
  percentage: number;
}

export interface TriggerDistribution {
  triggerType: string;
  count: number;
  percentage: number;
}

export interface UserDetailSummary {
  totalCredits: number;
  totalOverageCredits: number;
  totalInteractions: number;
  averageCostPerInteraction: number;
  totalMessages: number;
}

export interface UserDetailResponse {
  userId: string;
  displayName: string;
  userName: string;
  subscriptionTier: string;
  summary: UserDetailSummary;
  dailyUsage: DailyUsageEntry[];
  modelDistribution: ModelDistribution[];
  triggerDistribution: TriggerDistribution[];
  categoryDistribution: CategoryDistribution[];
  period: { startDate?: string; endDate?: string };
}

export interface ActivityTimelineEntry {
  date: string;
  interactions: number;
  messages: number;
  conversations: number;
}

export interface HourlyDistribution {
  hour: number;
  count: number;
}

export interface ProductivityCategoryBreakdown {
  category: string;
  count: number;
  percentage: number;
  avgPromptLength: number;
  avgResponseLength: number;
}

export interface ProductivitySummary {
  totalDaysActive: number;
  totalInteractions: number;
  totalPrompts: number;
  avgDailyInteractions: number;
  topCategory: string;
  peakHour: number | null;
}

export interface ProductivityResponse {
  userId: string;
  displayName: string;
  summary: ProductivitySummary;
  activityTimeline: ActivityTimelineEntry[];
  hourlyDistribution: HourlyDistribution[];
  modelUsage: ModelDistribution[];
  categoryBreakdown: ProductivityCategoryBreakdown[];
}


// --- Prompt History Types ---

export interface PromptMetadata {
  requestId: string;
  timestamp: string;
  category: string;
  promptPreview: string;
  modelId: string;
  triggerType: string;
  promptLength: number;
  responseLength: number;
}

export interface PromptsListResponse {
  items: PromptMetadata[];
  nextToken: string | null;
}

export interface PromptDetail {
  requestId: string;
  timestamp: string;
  category: string;
  modelId: string;
  prompt: string;
  response: string;
  promptLength: number;
  responseLength: number;
  contentInS3: boolean;
}

// --- Git Integration Types ---

export interface GitRepository {
  repoId: string;
  name: string;
  url: string;
  provider: 'github' | 'gitlab' | 'bitbucket' | 'codecommit';
  tokenConfigured: boolean;
  status: 'ACTIVE' | 'SYNC_OK' | 'SYNC_ERROR' | 'SYNCING';
  lastSyncAt: string | null;
  createdAt: string;
}

export interface GitUserMapping {
  userId: string;
  provider: string;
  gitUsername: string;
  gitEmail?: string;
  createdAt: string;
}

export interface GitActivitySummary {
  totalCommits: number;
  totalPRsOpened: number;
  totalPRsMerged: number;
  totalReviews: number;
  avgLinesPerCommit: number;
  avgMergeTimeHours: number;
}

export interface GitTimelineEntry {
  date: string;
  commits: number;
  prsOpened: number;
  prsMerged: number;
  reviews: number;
}

export interface GitPullRequest {
  prId: string;
  title: string;
  repository: string;
  state: 'open' | 'merged' | 'closed';
  createdAt: string;
  mergedAt: string | null;
  commitsCount: number;
  reviewsCount: number;
}

export interface GitActivityResponse {
  userId: string;
  summary: GitActivitySummary;
  timeline: GitTimelineEntry[];
  recentPRs: GitPullRequest[];
  period: { startDate?: string; endDate?: string };
  hasMapping: boolean;
}

export interface CorrelationMetrics {
  promptsPerCommit: number;
  mergeRate: number;
  avgReviewTimeHours: number;
  relativeProductivity: number;
}

export interface ComparativeTimelineEntry {
  date: string;
  kiroPrompts: number;
  gitCommits: number;
  gitPRs: number;
  dailyImpactIndex: number;
}

export interface CorrelationResponse {
  userId: string;
  impactIndex: number | null;
  impactLevel: 'low' | 'moderate' | 'high' | 'veryHigh' | null;
  metrics: CorrelationMetrics | null;
  comparativeTimeline: ComparativeTimelineEntry[];
  period: { startDate?: string; endDate?: string };
  sufficientData: boolean;
  message: string | null;
}

// --- Agent Correlation Types (new) ---

export interface CorrelationItem {
  promptSummary: string;
  gitActivity: string;
  confidence: number;
  type: 'prompt_to_commit' | 'prompt_to_pr';
}

/**
 * Stable English status slugs returned by the backend on non-success branches.
 * The frontend maps each slug to a translation key under
 * `productivity.correlation.status.<slug>`.
 */
export type CorrelationStatusSlug =
  | 'GIT_MAPPING_MISSING'
  | 'GITHUB_TOKEN_MISSING'
  | 'GITHUB_AUTH_FAILED'
  | 'GITHUB_RATE_LIMIT'
  | 'INSUFFICIENT_DATA'
  | 'AGENT_TIMEOUT'
  | 'AGENT_ERROR';

/**
 * Bilingual insight payload emitted by the agent. Both keys are always
 * present; the two arrays have equal length and parallel ordering
 * (index `i` is the same insight in both languages).
 */
export interface BilingualInsights {
  en: string[];
  'pt-BR': string[];
}

export interface CorrelationAnalysis {
  userId: string;
  /**
   * On success the backend may emit `'ready'` or `'processing'` (transient
   * polling signal). On non-success branches the backend emits one of the
   * `CorrelationStatusSlug` values, which the frontend maps to a
   * translation key.
   */
  status?: CorrelationStatusSlug | 'ready' | 'processing';
  impactScore: number | null;
  impactLevel: 'low' | 'moderate' | 'high' | 'veryHigh' | null;
  correlations: CorrelationItem[];
  insights: BilingualInsights;
  period: { startDate?: string; endDate?: string };
  analyzedAt: string | null;
  cached: boolean;
}


// --- Engagement Segmentation Types ---

export interface EngagementSegmentation {
  category: string;
  count: number;
  percentage: number;
}

export interface FunnelStage {
  name: string;
  count: number;
  conversionRate: number;
}

export interface DerivedEngagementMetrics {
  powerUserPercentage: number;
  activationRate: number;
  idleRate: number;
  dormantRate: number;
  churnRiskRate: number;
}

export interface EngagementResponse {
  segmentation: EngagementSegmentation[];
  funnel: FunnelStage[];
  derivedMetrics: DerivedEngagementMetrics;
  period: { startDate?: string; endDate?: string };
}


// --- Tier Optimization Recommendation Types ---

export interface TierRecommendation {
  userId: string;
  displayName: string;
  currentTier: string;
  recommendedTier: string;
  recommendationType: 'upgrade' | 'downgrade';
  projectedMonthlyUsage: number;
  projectedOverageCost: number;
  annualSavings: number;
  currentMonthlyCost: number;
  recommendedMonthlyCost: number;
}

export interface RecommendationSummary {
  totalRecommendations: number;
  totalProjectedAnnualSavings: number;
  upgradeCount: number;
  downgradeCount: number;
}

export interface RecommendationPeriod {
  startDate: string;
  endDate: string;
  daysWindow: number;
}

export interface InactiveSubscriber {
  userId: string;
  displayName: string;
  currentTier: string;
  currentMonthlyCost: number;
  daysInactive: number | null;
  lastActiveDate: string | null;
  annualWastedCost: number;
}

export interface InactiveSummary {
  totalInactive: number;
  totalAnnualWastedCost: number;
  thresholdDays: number;
}

export interface TierRecommendationsResponse {
  recommendations: TierRecommendation[];
  summary: RecommendationSummary;
  period?: RecommendationPeriod;
  inactiveSubscribers?: InactiveSubscriber[];
  inactiveSummary?: InactiveSummary;
}

export interface TierPricingEntry {
  monthlyPrice: number;
  includedCredits: number;
}

export interface TierPricingConfig {
  tiers: Record<string, TierPricingEntry>;
  overagePricePerCredit: number;
}

export interface TierPricingResponse {
  config: TierPricingConfig | null;
  status: 'valid' | 'not_configured';
  message?: string;
}
