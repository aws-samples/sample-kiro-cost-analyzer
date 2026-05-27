/**
 * Tests for `formatters.ts` (Task 1.16).
 *
 * Uses concrete, environment-stable assertions: the exact output of
 * `Intl.NumberFormat` / `Intl.DateTimeFormat` varies subtly across ICU
 * versions, so most assertions compare against a freshly-constructed
 * `Intl.*` instance rather than a hard-coded string. The meaningful contract
 * is "the formatter output matches Intl exactly", which is the same
 * invariant Property 4 / Property 5 encode — this file exercises it
 * non-randomly for fast feedback.
 */

import { describe, expect, it } from 'vitest';
import { createFormatters } from './formatters';

const EN = createFormatters('en');
const PTBR = createFormatters('pt-BR');

const FIXED = new Date('2025-03-14T15:09:26Z');

describe('createFormatters.formatNumber', () => {
  it('en renders 1234.5 with default options', () => {
    expect(EN.formatNumber(1234.5)).toBe(new Intl.NumberFormat('en').format(1234.5));
  });

  it('pt-BR renders 1234.5 with default options', () => {
    expect(PTBR.formatNumber(1234.5)).toBe(new Intl.NumberFormat('pt-BR').format(1234.5));
  });

  it('honors explicit options', () => {
    const opts: Intl.NumberFormatOptions = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
    expect(EN.formatNumber(1234.5, opts)).toBe(new Intl.NumberFormat('en', opts).format(1234.5));
    expect(PTBR.formatNumber(1234.5, opts)).toBe(new Intl.NumberFormat('pt-BR', opts).format(1234.5));
  });

  it('produces locale-distinct output when separators differ', () => {
    // Sanity check — 1234.5 renders with "," separator in en and "." in pt-BR.
    expect(EN.formatNumber(1234.5, { minimumFractionDigits: 1 })).not.toBe(
      PTBR.formatNumber(1234.5, { minimumFractionDigits: 1 }),
    );
  });
});

describe('createFormatters.formatDate', () => {
  it('uses default date options when none are provided', () => {
    const opts: Intl.DateTimeFormatOptions = { year: 'numeric', month: '2-digit', day: '2-digit' };
    expect(EN.formatDate(FIXED)).toBe(new Intl.DateTimeFormat('en', opts).format(FIXED));
    expect(PTBR.formatDate(FIXED)).toBe(new Intl.DateTimeFormat('pt-BR', opts).format(FIXED));
  });

  it('accepts Date, number, and ISO string inputs identically', () => {
    const asNum = EN.formatDate(FIXED.getTime());
    const asStr = EN.formatDate(FIXED.toISOString());
    const asDate = EN.formatDate(FIXED);
    expect(asNum).toBe(asDate);
    expect(asStr).toBe(asDate);
  });
});

describe('createFormatters.formatTime', () => {
  it('uses default time options when none are provided', () => {
    const opts: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' };
    expect(EN.formatTime(FIXED)).toBe(new Intl.DateTimeFormat('en', opts).format(FIXED));
    expect(PTBR.formatTime(FIXED)).toBe(new Intl.DateTimeFormat('pt-BR', opts).format(FIXED));
  });
});

describe('createFormatters.formatDateTime', () => {
  it('uses default date-time options when none are provided', () => {
    const opts: Intl.DateTimeFormatOptions = {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    };
    expect(EN.formatDateTime(FIXED)).toBe(new Intl.DateTimeFormat('en', opts).format(FIXED));
    expect(PTBR.formatDateTime(FIXED)).toBe(new Intl.DateTimeFormat('pt-BR', opts).format(FIXED));
  });
});

describe('createFormatters invalid-input handling', () => {
  it('does not throw on Invalid Date', () => {
    expect(() => EN.formatDate(new Date('not-a-date'))).not.toThrow();
    expect(() => EN.formatDateTime(NaN)).not.toThrow();
    expect(() => EN.formatTime('nope')).not.toThrow();
  });

  it("returns Intl's native Invalid Date string", () => {
    // ICU reports "Invalid Date" on modern engines; assert substring match
    // to stay tolerant of minor engine variation.
    const result = EN.formatDate(new Date('not-a-date'));
    expect(result.toLowerCase()).toContain('invalid');
  });
});
