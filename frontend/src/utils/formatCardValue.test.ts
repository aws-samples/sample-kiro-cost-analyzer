/**
 * Tests for formatCardValue (issue #20 — summary card number overflow).
 *
 * Feature: summary-card-number-overflow, Property 1: Threshold split
 * Feature: summary-card-number-overflow, Property 2: Locale coherence
 */

import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { createFormatters } from '../i18n/formatters';
import { COMPACT_THRESHOLD, formatCardValue } from './formatCardValue';

const en = createFormatters('en');
const ptBR = createFormatters('pt-BR');

describe('formatCardValue', () => {
  // Feature: summary-card-number-overflow, Property 1: Threshold split
  it('uses compact notation iff |value| >= threshold (property, en)', () => {
    fc.assert(
      fc.property(
        fc.double({ min: -1e12, max: 1e12, noNaN: true, noDefaultInfinity: true }),
        (value) => {
          const output = formatCardValue(value, en.formatNumber);
          const expected =
            Math.abs(value) >= COMPACT_THRESHOLD
              ? en.formatNumber(value, { notation: 'compact', maximumFractionDigits: 1 })
              : en.formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
          expect(output).toBe(expected);
        },
      ),
      { numRuns: 100 },
    );
  });

  // Feature: summary-card-number-overflow, Property 2: Locale coherence
  it('matches Intl.NumberFormat output for both locales (property)', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: 1e9, noNaN: true, noDefaultInfinity: true }),
        (value) => {
          for (const [locale, fmts] of [['en', en], ['pt-BR', ptBR]] as const) {
            const output = formatCardValue(value, fmts.formatNumber);
            const options: Intl.NumberFormatOptions =
              Math.abs(value) >= COMPACT_THRESHOLD
                ? { notation: 'compact', maximumFractionDigits: 1 }
                : { minimumFractionDigits: 2, maximumFractionDigits: 2 };
            expect(output).toBe(new Intl.NumberFormat(locale, options).format(value));
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it('abbreviates the reported repro value 10342.18 (en)', () => {
    expect(formatCardValue(10342.18, en.formatNumber)).toBe('10.3K');
  });

  it('abbreviates the reported repro value 10342.18 (pt-BR)', () => {
    expect(formatCardValue(10342.18, ptBR.formatNumber)).toBe(
      new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 }).format(10342.18),
    );
  });

  it('keeps 2-decimal formatting below the threshold (en)', () => {
    expect(formatCardValue(9876.54, en.formatNumber)).toBe('9,876.54');
  });

  it('renders integer counts without decimals below the threshold', () => {
    expect(formatCardValue(42, en.formatNumber, { fractionDigits: 0 })).toBe('42');
  });

  it('handles zero', () => {
    expect(formatCardValue(0, en.formatNumber)).toBe('0.00');
  });

  it('compacts large negative values', () => {
    expect(formatCardValue(-25000, en.formatNumber)).toBe('-25K');
  });
});
