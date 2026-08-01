import type { CorrelationStatusSlug } from '../types';
import type { TranslationKey } from '../locales/keys';

// ── Slug -> translation key map ─────────────────────────────────────────────
// Built at module scope so React does not rebuild it on every render.
export const slugToTranslationKey: Record<CorrelationStatusSlug, TranslationKey> = {
  GIT_MAPPING_MISSING: 'productivity.correlation.status.gitMappingMissing',
  GITHUB_TOKEN_MISSING: 'productivity.correlation.status.githubTokenMissing',
  GITHUB_AUTH_FAILED: 'productivity.correlation.status.githubAuthFailed',
  GITHUB_RATE_LIMIT: 'productivity.correlation.status.githubRateLimit',
  GITLAB_TOKEN_MISSING: 'productivity.correlation.status.gitlabTokenMissing',
  GITLAB_AUTH_FAILED: 'productivity.correlation.status.gitlabAuthFailed',
  GITLAB_RATE_LIMIT: 'productivity.correlation.status.gitlabRateLimit',
  INSUFFICIENT_DATA: 'productivity.correlation.status.insufficientData',
  AGENT_TIMEOUT: 'productivity.correlation.status.agentTimeout',
  AGENT_ERROR: 'productivity.correlation.status.agentError',
};

// ── Slug -> Cloudscape Alert severity map ──────────────────────────────────
// Severity follows the design's "Frontend-Level Errors" table:
//   info    — informational / user can act
//   warning — actionable, blocks analysis until the user fixes it
//   error   — the analysis operation actually failed
export const slugToAlertType: Record<CorrelationStatusSlug, 'info' | 'warning' | 'error'> = {
  GIT_MAPPING_MISSING: 'info',
  GITHUB_TOKEN_MISSING: 'warning',
  GITHUB_AUTH_FAILED: 'warning',
  GITHUB_RATE_LIMIT: 'info',
  GITLAB_TOKEN_MISSING: 'warning',
  GITLAB_AUTH_FAILED: 'warning',
  GITLAB_RATE_LIMIT: 'info',
  INSUFFICIENT_DATA: 'info',
  AGENT_TIMEOUT: 'error',
  AGENT_ERROR: 'error',
};

// Slugs where retrying makes sense without the user first changing settings.
// For GIT_MAPPING_MISSING / GITHUB_TOKEN_MISSING / GITHUB_AUTH_FAILED /
// GITLAB_TOKEN_MISSING / GITLAB_AUTH_FAILED the user must update Settings
// first, so no refresh action is offered.
export const RETRYABLE_SLUGS: ReadonlySet<CorrelationStatusSlug> = new Set<CorrelationStatusSlug>([
  'GITHUB_RATE_LIMIT',
  'GITLAB_RATE_LIMIT',
  'INSUFFICIENT_DATA',
  'AGENT_TIMEOUT',
  'AGENT_ERROR',
]);

export function isStatusSlug(s: string | undefined): s is CorrelationStatusSlug {
  return s !== undefined && s !== 'ready' && s !== 'processing' && s in slugToTranslationKey;
}
