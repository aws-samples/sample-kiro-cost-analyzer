/**
 * Property-based tests for `formatters.ts` (Tasks 2.11 + 2.12).
 *
 * These properties encode the core "locale coherence" invariant: every
 * helper in `Formatters` is a thin, deterministic wrapper over the
 * corresponding `Intl.*` constructor. The formatter's output MUST match a
 * freshly-constructed `Intl` formatter invoked with the same locale and
 * options for every input in the domain.
 *
 * Property 4 — number formatter locale coherence
 *   formatNumber(n, opts) == new Intl.NumberFormat(L, opts).format(n)
 *
 * Property 5 — date/time formatter locale coherence
 *   formatDate(t, opts)     == new Intl.DateTimeFormat(L, opts).format(t)
 *   formatTime(t, opts)     == new Intl.DateTimeFormat(L, opts).format(t)
 *   formatDateTime(t, opts) == new Intl.DateTimeFormat(L, opts).format(t)
 *
 * Validates Requirements 5.1, 5.3, 5.4, 5.5, 16.4, 16.5.
 */

import { describe, it } from 'vitest';
import fc from 'fast-check';
import { createFormatters } from './formatters';
import type { SupportedLocale } from './types';

const LOCALES: readonly SupportedLocale[] = ['en', 'pt-BR'];

describe('Property 4: number formatter locale coherence', () => {
  it('formatNumber(n, opts) equals Intl.NumberFormat(L, opts).format(n)', () => {
    const numberArb = fc.double({ noNaN: false, noDefaultInfinity: false });
    const localeArb = fc.constantFrom<SupportedLocale>(...LOCALES);
    const optsArb = fc.record(
      {
        minimumFractionDigits: fc.integer({ min: 0, max: 4 }),
        maximumFractionDigits: fc.integer({ min: 0, max: 4 }),
        style: fc.constantFrom<'decimal' | 'percent'>('decimal', 'percent'),
      },
      { requiredKeys: [] },
    );

    fc.assert(
      fc.property(numberArb, localeArb, optsArb, (n, L, rawOpts) => {
        // Clamp minimumFractionDigits <= maximumFractionDigits — Intl rejects
        // the inverse with a RangeError. This does not change the property:
        // the formatter and Intl see the same normalized options.
        const opts: Intl.NumberFormatOptions = { ...rawOpts };
        if (
          typeof opts.minimumFractionDigits === 'number' &&
          typeof opts.maximumFractionDigits === 'number' &&
          opts.minimumFractionDigits > opts.maximumFractionDigits
        ) {
          opts.maximumFractionDigits = opts.minimumFractionDigits;
        }

        const fmt = createFormatters(L);
        const actual = fmt.formatNumber(n, opts);
        const expected = new Intl.NumberFormat(L, opts).format(n);
        return actual === expected;
      }),
      { numRuns: 40 },
    );
  });
});

describe('Property 5: date/time formatter locale coherence', () => {
  // Invalid Date slips through `fc.date` (the underlying arbitrary emits
  // NaN-backed Date objects at its bounds). Filter them out — the coherence
  // property is stated for valid timestamps; the invalid-date path is
  // exercised by the example tests in formatters.test.ts.
  const dateArb = fc
    .date({ min: new Date('1970-01-01'), max: new Date('2100-12-31') })
    .filter((d) => !Number.isNaN(d.getTime()));
  const localeArb = fc.constantFrom<SupportedLocale>(...LOCALES);

  const DEFAULT_DATE: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  };
  const DEFAULT_TIME: Intl.DateTimeFormatOptions = {
    hour: '2-digit',
    minute: '2-digit',
  };
  const DEFAULT_DATETIME: Intl.DateTimeFormatOptions = {
    ...DEFAULT_DATE,
    ...DEFAULT_TIME,
  };

  it('formatDate matches Intl.DateTimeFormat for default options', () => {
    fc.assert(
      fc.property(dateArb, localeArb, (d, L) => {
        const fmt = createFormatters(L);
        const actual = fmt.formatDate(d);
        const expected = new Intl.DateTimeFormat(L, DEFAULT_DATE).format(d);
        return actual === expected;
      }),
      { numRuns: 40 },
    );
  });

  it('formatTime matches Intl.DateTimeFormat for default options', () => {
    fc.assert(
      fc.property(dateArb, localeArb, (d, L) => {
        const fmt = createFormatters(L);
        const actual = fmt.formatTime(d);
        const expected = new Intl.DateTimeFormat(L, DEFAULT_TIME).format(d);
        return actual === expected;
      }),
      { numRuns: 40 },
    );
  });

  it('formatDateTime matches Intl.DateTimeFormat for default options', () => {
    fc.assert(
      fc.property(dateArb, localeArb, (d, L) => {
        const fmt = createFormatters(L);
        const actual = fmt.formatDateTime(d);
        const expected = new Intl.DateTimeFormat(L, DEFAULT_DATETIME).format(d);
        return actual === expected;
      }),
      { numRuns: 40 },
    );
  });
});
