/**
 * Shared KPI/summary-card value formatting.
 *
 * Large values wrapped mid-number inside the 4-column KPI grids
 * (issue #20 / design critique F5). At or above COMPACT_THRESHOLD the
 * value switches to locale-aware compact notation (e.g. "10.3K" in en,
 * "10,3 mil" in pt-BR) so it always fits on one line; below the
 * threshold the standard notation with full precision is preserved.
 *
 * The caller provides `formatNumber` from `useI18n()`, keeping this a
 * pure, locale-agnostic function: all locale behavior lives in the
 * provided formatter.
 */

import type { Formatters } from '../i18n/formatters';

/** Absolute value at/above which compact notation is applied. */
export const COMPACT_THRESHOLD = 10_000;

export interface CardValueOptions {
  /** Fraction digits used below the threshold (default 2, e.g. credits). */
  fractionDigits?: number;
}

/**
 * Formats a KPI card value. At or above COMPACT_THRESHOLD (absolute),
 * uses compact notation with at most 1 fraction digit; below it, uses
 * standard notation with the configured fraction digits.
 */
export function formatCardValue(
  value: number,
  formatNumber: Formatters['formatNumber'],
  options?: CardValueOptions,
): string {
  const fractionDigits = options?.fractionDigits ?? 2;
  if (Math.abs(value) >= COMPACT_THRESHOLD) {
    return formatNumber(value, { notation: 'compact', maximumFractionDigits: 1 });
  }
  return formatNumber(value, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}
