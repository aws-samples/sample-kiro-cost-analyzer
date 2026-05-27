/**
 * Property-based tests for locale catalogs (Tasks 4.27–4.30).
 *
 * Four correctness properties guard catalog integrity at runtime:
 *
 * Property 7  — Catalog key parity: `keys(en.json) == keys(pt-BR.json)` as sets.
 * Property 8  — No empty translations: every value is a non-empty string.
 * Property 9  — Missing-key fallback: keys absent from the active locale
 *               resolve to the en value via i18next's `fallbackLng`.
 * Property 10 — Brand invariance: `brand.*` keys resolve to the canonical
 *               literal in every locale (`"Kiro Cost Analyzer"` / `"Kiro"`).
 *
 * Validates Requirements 9.1, 9.2, 10.1, 10.2, 10.3, 16.7, 16.8, 16.9, 16.10.
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import i18next from 'i18next';
import enCatalog from '../locales/en.json';
import ptBRCatalog from '../locales/pt-BR.json';
import { SUPPORTED_LOCALES, BRAND_STRINGS } from './constants';
import type { SupportedLocale } from './types';

type Catalog = Record<string, string>;

const CATALOGS: Record<SupportedLocale, Catalog> = {
  en: enCatalog as Catalog,
  'pt-BR': ptBRCatalog as Catalog,
};

describe('Property 7: catalog key parity', () => {
  it('symmetric difference of key sets is empty', () => {
    const enKeys = new Set(Object.keys(enCatalog));
    const ptBrKeys = new Set(Object.keys(ptBRCatalog));

    const onlyEn = [...enKeys].filter((k) => !ptBrKeys.has(k));
    const onlyPtBr = [...ptBrKeys].filter((k) => !enKeys.has(k));

    expect(onlyEn).toEqual([]);
    expect(onlyPtBr).toEqual([]);
  });
});

describe('Property 8: no empty translations', () => {
  it('every value in every catalog is a non-empty string', () => {
    for (const locale of SUPPORTED_LOCALES) {
      const catalog = CATALOGS[locale];
      for (const [key, value] of Object.entries(catalog)) {
        expect(typeof value, `[${locale}] key "${key}" must be a string`).toBe('string');
        expect(value.length, `[${locale}] key "${key}" must be non-empty`).toBeGreaterThan(0);
      }
    }
  });
});

describe('Property 9: missing-key fallback', () => {
  it('keys missing from the active catalog resolve to the en value', async () => {
    const allKeys = Object.keys(enCatalog) as (keyof typeof enCatalog)[];

    await fc.assert(
      fc.asyncProperty(
        fc.subarray(allKeys, { minLength: 1 }),
        async (holedKeys) => {
          // Build a partial pt-BR catalog missing the "holed" keys.
          const partialPtBR: Catalog = { ...(ptBRCatalog as Catalog) };
          for (const k of holedKeys) {
            delete partialPtBR[k];
          }

          const instance = i18next.createInstance();
          await instance.init({
            lng: 'pt-BR',
            fallbackLng: 'en',
            supportedLngs: ['en', 'pt-BR'],
            defaultNS: 'translation',
            ns: ['translation'],
            keySeparator: false,
            nsSeparator: false,
            interpolation: { escapeValue: false, prefix: '{{', suffix: '}}' },
            returnNull: false,
            resources: {
              en: { translation: enCatalog },
              'pt-BR': { translation: partialPtBR },
            },
          });

          for (const k of holedKeys) {
            const resolved = instance.t(k);
            if (resolved !== (enCatalog as Catalog)[k]) {
              return false;
            }
          }
          return true;
        },
      ),
      { numRuns: 100 },
    );
  });
});

describe('Property 10: brand invariance', () => {
  const BRAND_KEY_MAP: Record<keyof typeof BRAND_STRINGS, string> = {
    productName: 'brand.productName',
    short: 'brand.short',
  };

  // Concrete assertions per locale × brand key.
  for (const locale of SUPPORTED_LOCALES) {
    for (const brandKey of Object.keys(BRAND_STRINGS) as (keyof typeof BRAND_STRINGS)[]) {
      it(`[${locale}] ${BRAND_KEY_MAP[brandKey]} equals "${BRAND_STRINGS[brandKey]}"`, () => {
        const catalog = CATALOGS[locale];
        expect(catalog[BRAND_KEY_MAP[brandKey]]).toBe(BRAND_STRINGS[brandKey]);
      });
    }
  }

  it('property: catalog[L][brand.*] == BRAND_STRINGS[*] for every (L, brandKey)', () => {
    fc.assert(
      fc.property(
        fc.constantFrom<SupportedLocale>(...SUPPORTED_LOCALES),
        fc.constantFrom(...(Object.keys(BRAND_STRINGS) as (keyof typeof BRAND_STRINGS)[])),
        (locale, brandKey) => {
          const catalog = CATALOGS[locale];
          const catalogKey = BRAND_KEY_MAP[brandKey];
          return catalog[catalogKey] === BRAND_STRINGS[brandKey];
        },
      ),
      { numRuns: 100 },
    );
  });
});
