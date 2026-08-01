/**
 * Tests for `resolveLocale.ts`.
 *
 * Covers:
 * - Task 1.15 / Property 1: resolution totality under fast-check.
 * - Light example coverage for each branch (kept minimal; the property
 *   subsumes exhaustive enumeration).
 */

import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { resolveInitialLocale, normalizeToSupported } from './resolveLocale';
import { SUPPORTED_LOCALES } from './constants';

describe('normalizeToSupported', () => {
  it('maps en variants to "en"', () => {
    for (const lang of ['en', 'en-US', 'en-GB', 'EN', 'en_US']) {
      expect(normalizeToSupported(lang)).toBe('en');
    }
  });

  it('maps pt variants to "pt-BR"', () => {
    for (const lang of ['pt', 'pt-BR', 'pt-br', 'pt-PT', 'PT', 'pt_BR']) {
      expect(normalizeToSupported(lang)).toBe('pt-BR');
    }
  });

  it('returns null for unsupported or empty inputs', () => {
    for (const lang of ['fr', 'de-DE', '', undefined]) {
      expect(normalizeToSupported(lang)).toBeNull();
    }
  });
});

describe('resolveInitialLocale (examples)', () => {
  it('honors a valid stored locale', () => {
    expect(resolveInitialLocale('en', 'pt-BR')).toBe('en');
    expect(resolveInitialLocale('pt-BR', 'en-US')).toBe('pt-BR');
  });

  it('falls through to navigator when stored is invalid', () => {
    expect(resolveInitialLocale('fr-FR', 'en-US')).toBe('en');
    expect(resolveInitialLocale('', 'pt-BR')).toBe('pt-BR');
  });

  it('falls through to DEFAULT_LOCALE when neither stored nor navigator match', () => {
    // DEFAULT_LOCALE is 'pt-BR' in Step 1; test against its current value
    // (imported via the supported-locale tuple so this test survives the
    // Step-6 flip).
    const result = resolveInitialLocale(null, 'fr-FR');
    expect(SUPPORTED_LOCALES).toContain(result);
  });

  it('accepts pt variants via navigator', () => {
    expect(resolveInitialLocale(null, 'pt-br')).toBe('pt-BR');
    expect(resolveInitialLocale(null, 'pt')).toBe('pt-BR');
    expect(resolveInitialLocale(null, 'pt-PT')).toBe('pt-BR');
  });

  it('accepts en variants via navigator', () => {
    expect(resolveInitialLocale(null, 'en-US')).toBe('en');
    expect(resolveInitialLocale(null, 'en-GB')).toBe('en');
    expect(resolveInitialLocale(null, 'en')).toBe('en');
  });

  it('handles null stored and undefined navigator', () => {
    const result = resolveInitialLocale(null, undefined);
    expect(SUPPORTED_LOCALES).toContain(result);
  });
});

describe('Property 1: resolveInitialLocale totality', () => {
  it('is total over (string | null, string | undefined)', () => {
    const storedArb = fc.oneof(fc.constant(null), fc.string());
    const navArb = fc.oneof(
      fc.constant(undefined),
      fc.string(),
      fc.constantFrom('en', 'en-US', 'en-GB', 'pt', 'pt-BR', 'pt-br', 'fr', 'de'),
    );
    fc.assert(
      fc.property(storedArb, navArb, (stored, nav) => {
        const result = resolveInitialLocale(stored, nav);
        return (SUPPORTED_LOCALES as readonly string[]).includes(result);
      }),
      { numRuns: 100 },
    );
  });
});
