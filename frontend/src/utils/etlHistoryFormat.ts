import type { StatusIndicatorProps } from '@cloudscape-design/components/status-indicator';

/** Rendered in place of any value the backend reports as unknown. */
export const EM_DASH = '—';

/**
 * Render a duration in seconds as a compact, locale-neutral string.
 *
 * Unit symbols rather than words, so the result reads the same in every locale
 * and needs no catalog entry. Total function: any value that is not a finite,
 * non-negative number renders as an em dash.
 *
 * @param seconds Elapsed whole or fractional seconds, or null when unknown.
 * @returns A string such as `42s`, `5m 38s`, `1h 04m`, or an em dash.
 */
export function formatElapsed(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) {
    return EM_DASH;
  }

  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = whole % 60;

  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, '0')}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${String(secs).padStart(2, '0')}s`;
  }
  return `${secs}s`;
}

/**
 * Map a Step Functions execution status to a Cloudscape indicator type.
 *
 * The fallback keeps callers total against a status Step Functions might add in
 * the future.
 *
 * @param status Raw uppercase Step Functions execution status.
 */
export function executionStatusType(status: string): StatusIndicatorProps.Type {
  switch (status) {
    case 'SUCCEEDED':
      return 'success';
    case 'FAILED':
      return 'error';
    case 'RUNNING':
      return 'in-progress';
    case 'ABORTED':
      return 'stopped';
    case 'TIMED_OUT':
      return 'warning';
    default:
      return 'pending';
  }
}

/**
 * Translation keys for the execution statuses the pipeline can report.
 *
 * A status absent from this map renders its raw slug, which is the correct
 * degradation for a value the catalog does not yet know about.
 */
export const EXECUTION_STATUS_LABEL_KEYS = {
  SUCCEEDED: 'settings.etl.history.status.succeeded',
  FAILED: 'settings.etl.history.status.failed',
  RUNNING: 'settings.etl.history.status.running',
  ABORTED: 'settings.etl.history.status.aborted',
  TIMED_OUT: 'settings.etl.history.status.timedOut',
} as const;
