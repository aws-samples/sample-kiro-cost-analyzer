import { get, post, patch, del } from './client';
import type {
  GitRepository,
  GitUserMapping,
  GitMappingCreated,
  GitActivityResponse,
  CorrelationResponse,
  CorrelationAnalysis,
} from '../types';

// --- Repositories ---

export function createGitRepo(body: {
  name: string;
  url: string;
  provider: string;
  accessToken: string;
}): Promise<GitRepository> {
  return post<GitRepository>('/api/git/repos', body);
}

export function listGitRepos(): Promise<{ repositories: GitRepository[] }> {
  return get<{ repositories: GitRepository[] }>('/api/git/repos');
}

/** Partial update body for a repository. Omit accessToken to keep the current token. */
export interface GitRepoPatch {
  name?: string;
  url?: string;
  provider?: string;
  accessToken?: string;
}

export function updateGitRepo(repoId: string, body: GitRepoPatch): Promise<GitRepository> {
  return patch<GitRepository>(`/api/git/repos/${repoId}`, body);
}

export function deleteGitRepo(repoId: string): Promise<{ status: string }> {
  return del<{ status: string }>(`/api/git/repos/${repoId}`);
}

export function triggerGitSync(repoId: string): Promise<{ status: string; message: string }> {
  return post<{ status: string; message: string }>(`/api/git/repos/${repoId}/sync`);
}

// --- User Mappings ---

export function createGitMapping(body: {
  userId: string;
  provider: string;
  gitUsername: string;
}): Promise<GitMappingCreated> {
  return post<GitMappingCreated>('/api/git/mappings', body);
}

export function listGitMappings(userId: string): Promise<{ mappings: GitUserMapping[] }> {
  return get<{ mappings: GitUserMapping[] }>(`/api/git/mappings/${userId}`);
}

/** Paginated cross-user mapping listing. Omit lastKey for the first page. */
export function listAllGitMappings(params?: { limit?: string; lastKey?: string }):
  Promise<{ mappings: GitUserMapping[]; lastKey?: string }> {
  return get<{ mappings: GitUserMapping[]; lastKey?: string }>('/api/git/mappings', params);
}

export function deleteGitMapping(
  userId: string,
  provider: string,
): Promise<{ status: string }> {
  return del<{ status: string }>(`/api/git/mappings/${userId}/${provider}`);
}

// --- Activity & Correlation ---

export function getGitActivity(
  userId: string,
  params?: Record<string, string>,
): Promise<GitActivityResponse> {
  return get<GitActivityResponse>(`/api/git/activity/${userId}`, params);
}

export function getGitCorrelation(
  userId: string,
  params?: Record<string, string>,
): Promise<CorrelationResponse> {
  return get<CorrelationResponse>(`/api/git/correlation/${userId}`, params);
}

// --- Agent-based Correlation Analysis ---

export function getAgentCorrelation(
  userId: string,
  params?: Record<string, string>,
): Promise<CorrelationAnalysis> {
  return get<CorrelationAnalysis>(`/api/productivity/${userId}/correlation`, params);
}

const POLL_INTERVAL_MS = 5000;
const MAX_POLL_ATTEMPTS = 60;

/**
 * Fetch correlation analysis with automatic polling for async results.
 *
 * If the backend returns status "processing", polls every 5s until the
 * result is ready or max attempts are exhausted.
 *
 * @param userId - Target user identifier.
 * @param params - Optional query params (startDate, endDate, forceRefresh).
 * @param onProcessing - Optional callback invoked when status is "processing".
 * @returns The final CorrelationAnalysis result.
 * @throws Error if max poll attempts exceeded.
 */
export async function getAgentCorrelationWithPolling(
  userId: string,
  params?: Record<string, string>,
  onProcessing?: () => void,
): Promise<CorrelationAnalysis> {
  const result = await getAgentCorrelation(userId, params);

  if (result.status !== 'processing') {
    return result;
  }

  onProcessing?.();

  // Poll WITHOUT forceRefresh — we want to hit the cache once the worker finishes
  const pollParams = { ...params };
  delete pollParams.forceRefresh;

  // Poll until result is ready
  for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));

    const pollResult = await getAgentCorrelation(userId, pollParams);

    if (pollResult.status !== 'processing') {
      return pollResult;
    }
  }

  throw new Error('POLL_TIMEOUT');
}

// --- Activity Detail (Kiro-Git correlation per commit/PR) ---

export interface ScoredPrompt {
  requestId: string;
  timestamp: string;
  prompt: string;
  response: string;
  category: string;
  modelId: string;
  triggerType: string;
  similarityScore: number;
  correlationLevel: string;
}

export interface ActivityCorrelation {
  hasCorrelation: boolean;
  maxSimilarity: number;
  avgSimilarity: number;
  totalNearbyPrompts: number;
  correlatedPrompts: number;
  assessment: string;
}

export interface ActivityDetail {
  activityId: string;
  activityType: 'commit' | 'pr';
  description: string;
  timestamp: string;
  repository: string;
  metadata: Record<string, unknown>;
  nearbyPrompts: ScoredPrompt[];
  correlation: ActivityCorrelation;
}

export interface ActivityDetailResponse {
  userId: string;
  date: string;
  activities: ActivityDetail[];
  summary: {
    totalActivities: number;
    totalCommits: number;
    totalPRs: number;
    totalPromptsInWindow: number;
    activitiesWithCorrelation: number;
    correlationRate: number;
  };
}

export function getGitActivityDetail(
  userId: string,
  date: string,
): Promise<ActivityDetailResponse> {
  return get<ActivityDetailResponse>(`/api/git/activity/${userId}/detail`, { date });
}
