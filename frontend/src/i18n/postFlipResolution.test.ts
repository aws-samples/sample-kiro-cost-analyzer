/**
 * Post-flip resolution-chain tests (Task 6.3).
 *
 * Exercises every branch of the Locale_Resolution_Chain after the Step-6
 * flip (`DEFAULT_LOCALE = 'en'`), plus the persistence-realignment rule
 * (Requirement 2.4): when a stored value is invalid, it is ignored and the
 * resolved locale is persisted back to `Locale_Storage_Key`.
 *
 * We use an in-memory `Map` as the storage so the suite stays hermetic
 * against the jsdom/Node-25 localStorage interaction.
 */

import { describe, it, expect } from 'vitest';
import { resolveInitialLocale } from './resolveLocale';
import { DEFAULT_LOCALE, LOCALE_STORAGE_KEY, SUPPORTED_LOCALES } from './constants';
import type { SupportedLocale } from './types';

describe('DEFAULT_LOCALE is "en" after Step 6 flip', () => {
  it('sanity: DEFAULT_LOCALE resolved to "en"', () => {
    expect(DEFAULT_LOCALE).toBe('en');
  });
});

describe('Stored preference wins when supported', () => {
  it('stored "en" → en', () => {
    expect(resolveInitialLocale('en', 'pt-BR')).toBe('en');
    expect(resolveInitialLocale('en', undefined)).toBe('en');
    expect(resolveInitialLocale('en', 'fr-FR')).toBe('en');
  });

  it('stored "pt-BR" → pt-BR', () => {
    expect(resolveInitialLocale('pt-BR', 'en-US')).toBe('pt-BR');
    expect(resolveInitialLocale('pt-BR', undefined)).toBe('pt-BR');
    expect(resolveInitialLocale('pt-BR', 'fr-FR')).toBe('pt-BR');
  });
});

describe('Invalid stored value falls through to navigator', () => {
  it('stored "fr-FR" with navigator "en-US" → en', () => {
    expect(resolveInitialLocale('fr-FR', 'en-US')).toBe('en');
  });

  it('stored "fr-FR" with navigator "pt-BR" → pt-BR', () => {
    expect(resolveInitialLocale('fr-FR', 'pt-BR')).toBe('pt-BR');
  });

  it('stored "" with navigator "pt-br" → pt-BR', () => {
    expect(resolveInitialLocale('', 'pt-br')).toBe('pt-BR');
  });

  it('stored "garbage" with navigator undefined → DEFAULT_LOCALE (en)', () => {
    expect(resolveInitialLocale('garbage', undefined)).toBe('en');
  });
});

describe('Navigator variants resolve correctly', () => {
  const cases: [string | undefined, SupportedLocale][] = [
    ['en', 'en'],
    ['en-US', 'en'],
    ['en-GB', 'en'],
    ['EN', 'en'],
    ['en_US', 'en'],
    ['pt', 'pt-BR'],
    ['pt-BR', 'pt-BR'],
    ['pt-br', 'pt-BR'],
    ['pt-PT', 'pt-BR'],
    ['PT', 'pt-BR'],
    ['pt_BR', 'pt-BR'],
  ];

  for (const [nav, expected] of cases) {
    it(`stored null, navigator "${nav}" → ${expected}`, () => {
      expect(resolveInitialLocale(null, nav)).toBe(expected);
    });
  }
});

describe('Unsupported navigator falls back to DEFAULT_LOCALE', () => {
  const cases: (string | undefined)[] = ['fr-FR', 'de-DE', 'es', 'ja-JP', '', undefined];

  for (const nav of cases) {
    it(`stored null, navigator ${JSON.stringify(nav)} → en (DEFAULT_LOCALE)`, () => {
      expect(resolveInitialLocale(null, nav)).toBe('en');
    });
  }
});

describe('Totality: every resolution lands in SUPPORTED_LOCALES', () => {
  it('null stored + undefined navigator lands in SUPPORTED_LOCALES', () => {
    const result = resolveInitialLocale(null, undefined);
    expect(SUPPORTED_LOCALES).toContain(result);
  });
});

describe('Persistence realignment (Requirement 2.4)', () => {
  // The resolver itself is pure — the persistence realignment happens in
  // `src/i18n/index.ts` after i18next init. Here we simulate the exact
  // sequence the runtime follows: resolve → compare against stored →
  // persist the resolved value when they differ.
  //
  // This mirrors the production guarantee: an invalid stored value is
  // overwritten on first boot so subsequent boots are idempotent.

  function simulateBoot(
    storage: Map<string, string>,
    navigatorLang: string | undefined,
  ): SupportedLocale {
    const stored = storage.get(LOCALE_STORAGE_KEY) ?? null;
    const resolved = resolveInitialLocale(stored, navigatorLang);
    if (stored !== resolved) {
      storage.set(LOCALE_STORAGE_KEY, resolved);
    }
    return resolved;
  }

  it('invalid stored "fr-FR" is overwritten with the resolved value on first boot', () => {
    const storage = new Map<string, string>();
    storage.set(LOCALE_STORAGE_KEY, 'fr-FR');

    const resolved = simulateBoot(storage, 'en-US');
    expect(resolved).toBe('en');
    expect(storage.get(LOCALE_STORAGE_KEY)).toBe('en');
  });

  it('invalid stored "garbage" with pt-BR navigator is overwritten with pt-BR', () => {
    const storage = new Map<string, string>();
    storage.set(LOCALE_STORAGE_KEY, 'garbage');

    const resolved = simulateBoot(storage, 'pt-BR');
    expect(resolved).toBe('pt-BR');
    expect(storage.get(LOCALE_STORAGE_KEY)).toBe('pt-BR');
  });

  it('valid stored value is not overwritten', () => {
    const storage = new Map<string, string>();
    storage.set(LOCALE_STORAGE_KEY, 'en');

    simulateBoot(storage, 'pt-BR');
    expect(storage.get(LOCALE_STORAGE_KEY)).toBe('en');
  });

  it('missing stored value is persisted after resolution', () => {
    const storage = new Map<string, string>();

    const resolved = simulateBoot(storage, 'en-US');
    expect(resolved).toBe('en');
    expect(storage.get(LOCALE_STORAGE_KEY)).toBe('en');
  });

  it('idempotent across two consecutive boots', () => {
    const storage = new Map<string, string>();
    storage.set(LOCALE_STORAGE_KEY, 'invalid');

    simulateBoot(storage, 'fr-FR');
    expect(storage.get(LOCALE_STORAGE_KEY)).toBe('en');

    simulateBoot(storage, 'fr-FR');
    expect(storage.get(LOCALE_STORAGE_KEY)).toBe('en');
  });
});
