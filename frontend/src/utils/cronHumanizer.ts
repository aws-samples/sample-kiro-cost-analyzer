/**
 * Convert an Amazon EventBridge schedule expression to a human-readable
 * string in the user's active locale.
 *
 * Supports `rate(...)` and `cron(...)` EventBridge Scheduler expressions.
 *
 * Examples (with `t` bound to the `pt-BR` catalog):
 * - `rate(1 day)`              → "Todos os dias"
 * - `rate(2 hours)`             → "A cada 2 horas"
 * - `rate(5 minutes)`           → "A cada 5 minutos"
 * - `cron(59 23 * * ? *)`       → "Todos os dias às 23:59"
 * - `cron(0 12 ? * MON-FRI *)`  → "De segunda a sexta às 12:00"
 * - `cron(0 8 1 * ? *)`         → "Todo dia 1 às 08:00"
 *
 * Unrecognized expressions are returned verbatim as a graceful fallback,
 * irrespective of locale (Requirement 6.4).
 *
 * The function is pure: it does not read i18n state directly, only the `t`
 * function passed in. Call sites obtain `t` from `useI18n()` and are
 * responsible for re-invoking the humanizer when the active locale changes.
 */

import type { TFunction } from 'i18next';

/**
 * Minimal `t` shape used internally. `TFunction` from `react-i18next` is
 * assignable to this shape at runtime (it accepts `(key, opts)` with an
 * object of variables), so both real and synthetic translators can flow
 * through `humanize` without casts at call sites.
 */
export type AnyT = (key: string, vars?: Record<string, string | number>) => string;

/**
 * Public parameter type for `humanize`. Accepts both the real
 * `TFunction` (so call sites pass `t` from `useI18n()` directly) and a
 * synthetic `(key, vars) => string` (so tests can construct a deterministic
 * `t` over a plain catalog without spinning up an i18next instance).
 */
export type HumanizerT = TFunction | AnyT;

/**
 * Internal delegator that narrows the union to `AnyT` at runtime. The two
 * callable shapes accept the same `(key, vars)` tuple; the cast avoids
 * leaking i18next's overload complexity into every call site of `humanize`.
 */
function tCall(t: HumanizerT, key: string, vars?: Record<string, string | number>): string {
  return (t as AnyT)(key, vars);
}

/**
 * EventBridge day-of-week abbreviations mapped to catalog keys. Each key
 * resolves to the day name in the active locale (e.g., `cron.days.MON` =>
 * "Monday" in en, "segunda" in pt-BR).
 */
const DAY_KEYS: Record<string, string> = {
  SUN: 'cron.days.SUN',
  MON: 'cron.days.MON',
  TUE: 'cron.days.TUE',
  WED: 'cron.days.WED',
  THU: 'cron.days.THU',
  FRI: 'cron.days.FRI',
  SAT: 'cron.days.SAT',
};

export function humanize(expression: string, t: HumanizerT): string {
  const rateResult = parseRate(expression, t);
  if (rateResult) return rateResult;

  const cronResult = parseCron(expression, t);
  if (cronResult) return cronResult;

  return expression;
}

function parseRate(expression: string, t: HumanizerT): string | null {
  const match = expression.match(/^rate\((\d+)\s+(minute|minutes|hour|hours|day|days)\)$/);
  if (!match) return null;

  const value = parseInt(match[1], 10);
  const unit = match[2];

  if (unit === 'day' || unit === 'days') {
    return value === 1 ? tCall(t, 'cron.rate.daily') : tCall(t, 'cron.rate.days', { n: value });
  }

  if (unit === 'hour' || unit === 'hours') {
    return value === 1 ? tCall(t, 'cron.rate.hourly') : tCall(t, 'cron.rate.hours', { n: value });
  }

  if (unit === 'minute' || unit === 'minutes') {
    return value === 1 ? tCall(t, 'cron.rate.minute') : tCall(t, 'cron.rate.minutes', { n: value });
  }

  return null;
}

function parseCron(expression: string, t: HumanizerT): string | null {
  const match = expression.match(/^cron\((.+)\)$/);
  if (!match) return null;

  const parts = match[1].trim().split(/\s+/);
  if (parts.length !== 6) return null;

  const [minute, hour, dayOfMonth, month, dayOfWeek, year] = parts;

  // Minute and hour must be numeric; month and year must be wildcards.
  if (!/^\d+$/.test(minute) || !/^\d+$/.test(hour)) return null;
  if (month !== '*' || year !== '*') return null;

  const time = formatTime(minute, hour);

  // Pattern: cron(M H * * ? *) → "Every day at HH:MM"
  if (dayOfMonth === '*' && dayOfWeek === '?') {
    return tCall(t, 'cron.cron.daily', { time });
  }

  // Pattern: cron(M H ? * DOW *) → days of week with time
  if (dayOfMonth === '?' && dayOfWeek !== '*') {
    return renderDaysOfWeek(dayOfWeek, time, t);
  }

  // Pattern: cron(M H D * ? *) → specific day of month with time
  if (dayOfWeek === '?' && /^\d+$/.test(dayOfMonth)) {
    return tCall(t, 'cron.cron.dayOfMonth', { day: dayOfMonth, time });
  }

  return null;
}

/**
 * Formats minute and hour as an `HH:MM` string, zero-padded.
 */
function formatTime(minute: string, hour: string): string {
  return `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`;
}

/**
 * Renders day-of-week tokens (single, range, or list) into a
 * localized schedule description.
 *
 * - Range `MON-FRI` uses the `cron.cron.daysRange` template.
 * - List `MON,WED,FRI` is joined via `cron.days.separator` and
 *   `cron.days.lastSeparator`, then plugged into `cron.cron.daysList`.
 * - A single token is rendered via `cron.cron.daysList` with the day
 *   capitalized so pt-BR byte-parity is preserved.
 */
function renderDaysOfWeek(dow: string, time: string, t: HumanizerT): string | null {
  // Range: MON-FRI
  const rangeMatch = dow.match(/^([A-Z]{3})-([A-Z]{3})$/);
  if (rangeMatch) {
    const startKey = DAY_KEYS[rangeMatch[1]];
    const endKey = DAY_KEYS[rangeMatch[2]];
    if (!startKey || !endKey) return null;
    return tCall(t, 'cron.cron.daysRange', {
      start: tCall(t, startKey),
      end: tCall(t, endKey),
      time,
    });
  }

  // List: MON,WED,FRI
  if (dow.includes(',')) {
    const keys = dow.split(',').map((d) => DAY_KEYS[d.trim()]);
    if (keys.some((k) => !k)) return null;
    const names = keys.map((k) => tCall(t, k));
    let joined: string;
    if (names.length === 1) {
      joined = capitalize(names[0]);
    } else {
      const last = names.pop()!;
      joined = capitalize(
        `${names.join(tCall(t, 'cron.days.separator'))}${tCall(t, 'cron.days.lastSeparator')}${last}`,
      );
    }
    return tCall(t, 'cron.cron.daysList', { days: joined, time });
  }

  // Single day: MON
  const key = DAY_KEYS[dow];
  if (!key) return null;
  return tCall(t, 'cron.cron.daysList', { days: capitalize(tCall(t, key)), time });
}

/**
 * Capitalizes the first character of a string, leaving the rest unchanged.
 * Used for pt-BR, where day names are stored lowercase in the catalog and
 * capitalized at the start of a sentence. For locales whose day names are
 * already title-cased (en), this is a no-op.
 */
function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}
