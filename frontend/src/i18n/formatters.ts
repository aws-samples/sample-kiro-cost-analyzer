/**
 * Locale-aware formatters.
 *
 * Every user-facing number, date, or time must go through one of these
 * helpers so the output follows the active locale. They are thin adapters
 * over `Intl.NumberFormat` and `Intl.DateTimeFormat`, bound to the locale at
 * construction time by `createFormatters`.
 *
 * Default option objects are documented in the spec; callers may override any
 * subset of them per call. The factory is stateless — memoization happens in
 * `I18nProvider` (one `Formatters` object per active locale).
 */

import type { SupportedLocale } from './types';

export interface Formatters {
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatDate: (value: Date | number | string, options?: Intl.DateTimeFormatOptions) => string;
  formatTime: (value: Date | number | string, options?: Intl.DateTimeFormatOptions) => string;
  formatDateTime: (value: Date | number | string, options?: Intl.DateTimeFormatOptions) => string;
}

/** Default date options: numeric year, 2-digit month, 2-digit day. */
const DEFAULT_DATE: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
};

/** Default time options: 2-digit hour, 2-digit minute. */
const DEFAULT_TIME: Intl.DateTimeFormatOptions = {
  hour: '2-digit',
  minute: '2-digit',
};

/** Default date-time options: union of date + time defaults. */
const DEFAULT_DATETIME: Intl.DateTimeFormatOptions = {
  ...DEFAULT_DATE,
  ...DEFAULT_TIME,
};

/**
 * Coerces a `Date | number | string` into a `Date`. No validation is
 * performed here — invalid inputs flow into `Intl.DateTimeFormat.format()`,
 * where `safeFormat` catches the resulting `RangeError` and returns the
 * stable `"Invalid Date"` sentinel. This matches the browser's native
 * behavior on modern engines, giving callers a consistent fallback across
 * environments (jsdom / Node / production).
 */
function toDate(value: Date | number | string): Date {
  if (value instanceof Date) return value;
  if (typeof value === 'number') return new Date(value);
  return new Date(value);
}

/**
 * Invokes `Intl.DateTimeFormat.format` and returns `"Invalid Date"` when the
 * underlying engine rejects the input instead of throwing. Browsers return
 * the sentinel natively; Node/V8 throws `RangeError: Invalid time value`.
 * Normalizing here keeps the formatter contract uniform across runtimes.
 */
function safeFormat(fmt: Intl.DateTimeFormat, d: Date): string {
  try {
    return fmt.format(d);
  } catch {
    return 'Invalid Date';
  }
}

/**
 * Creates a `Formatters` object bound to the given locale. The returned
 * object has no shared state between calls and is safe to memoize.
 */
export function createFormatters(locale: SupportedLocale): Formatters {
  return {
    formatNumber: (value, options) => new Intl.NumberFormat(locale, options).format(value),
    formatDate: (value, options) =>
      safeFormat(new Intl.DateTimeFormat(locale, options ?? DEFAULT_DATE), toDate(value)),
    formatTime: (value, options) =>
      safeFormat(new Intl.DateTimeFormat(locale, options ?? DEFAULT_TIME), toDate(value)),
    formatDateTime: (value, options) =>
      safeFormat(new Intl.DateTimeFormat(locale, options ?? DEFAULT_DATETIME), toDate(value)),
  };
}
