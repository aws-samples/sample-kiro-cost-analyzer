/**
 * Property-based test for the GitLab-feature-specific locale catalog
 * invariants: the five new keys exist with parity, and none of them
 * collides with another key as a dot-notation leaf/prefix pair.
 *
 * The general-purpose build-time check (`scripts/check-locales.ts`) already
 * verifies full key-set parity, non-empty string values, and alphabetical
 * sort order for both catalogs on every build. This test does not duplicate
 * that mechanism. It exists for a narrower concern: `gitMappingForm.success`
 * already exists as a leaf key, and `gitMappingForm.successReplaced` was
 * deliberately named as a flat sibling rather than `gitMappingForm.success.replaced`
 * because i18next resolves a key that is simultaneously a leaf and a
 * dot-notation prefix of another key unpredictably. This test pins that
 * class of regression for the five keys this feature added: none of them
 * is a dot-notation prefix of another key, and none of them collides as a
 * dot-notation descendant of a pre-existing key, in either catalog. (The
 * catalog holds a handful of pre-existing, unrelated leaf/prefix pairs from
 * before this feature — e.g. `common.loading` / `common.loading.chart` —
 * that are out of scope here and are not asserted against.)
 *
 * Validates Requirements 9.5, 9.8.
 */

import { describe, it } from 'vitest';
import fc from 'fast-check';
import enCatalog from './en.json';
import ptBRCatalog from './pt-BR.json';
import { SUPPORTED_LOCALES } from '../i18n/constants';
import type { SupportedLocale } from '../i18n/types';

type Catalog = Record<string, string>;

const CATALOGS: Record<SupportedLocale, Catalog> = {
  en: enCatalog as Catalog,
  'pt-BR': ptBRCatalog as Catalog,
};

// The five keys added by this feature (task 15.2).
const NEW_KEYS = [
  'productivity.correlation.status.gitlabTokenMissing',
  'productivity.correlation.status.gitlabAuthFailed',
  'productivity.correlation.status.gitlabRateLimit',
  'gitMappingForm.successReplaced',
  'gitSettings.mappings.success.removed',
] as const;

/** True when `other` is a strict dot-notation descendant of `key`. */
function isDotPrefixOf(key: string, other: string): boolean {
  return other !== key && other.startsWith(`${key}.`);
}

describe('Property 21: Locale catalog key parity', () => {
  // Feature: gitlab-provider-support, Property 21: Locale catalog key parity
  it('both catalogs share exactly the same key set (baseline sanity check)', () => {
    const enKeys = new Set(Object.keys(enCatalog));
    const ptBrKeys = new Set(Object.keys(ptBRCatalog));

    const onlyEn = [...enKeys].filter((k) => !ptBrKeys.has(k));
    const onlyPtBr = [...ptBrKeys].filter((k) => !enKeys.has(k));

    if (onlyEn.length > 0 || onlyPtBr.length > 0) {
      throw new Error(
        `catalog key sets diverge: only in en=[${onlyEn.join(', ')}] only in pt-BR=[${onlyPtBr.join(', ')}]`,
      );
    }
  });

  // Feature: gitlab-provider-support, Property 21: Locale catalog key parity
  it('the five new keys exist in both catalogs with non-empty string values, for every supported locale', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...NEW_KEYS),
        fc.constantFrom(...SUPPORTED_LOCALES),
        (key, locale) => {
          const catalog = CATALOGS[locale];
          const value = catalog[key];
          return typeof value === 'string' && value.length > 0;
        },
      ),
      { numRuns: 20 },
    );
  });

  // Feature: gitlab-provider-support, Property 21: Locale catalog key parity
  it('gitMappingForm.success and gitMappingForm.successReplaced do not collide as leaf/prefix, in either locale', () => {
    for (const locale of SUPPORTED_LOCALES) {
      const catalog = CATALOGS[locale];

      // Both keys must exist as independent leaves.
      if (typeof catalog['gitMappingForm.success'] !== 'string') {
        throw new Error(`[${locale}] gitMappingForm.success is missing or not a string`);
      }
      if (typeof catalog['gitMappingForm.successReplaced'] !== 'string') {
        throw new Error(`[${locale}] gitMappingForm.successReplaced is missing or not a string`);
      }

      // successReplaced must NOT be of the form "success.<anything>" — it is
      // a flat sibling key, not a nested child of gitMappingForm.success.
      if (isDotPrefixOf('gitMappingForm.success', 'gitMappingForm.successReplaced')) {
        throw new Error(
          `[${locale}] gitMappingForm.successReplaced collides as a dot-notation ` +
            'child of gitMappingForm.success — it must be a flat sibling key',
        );
      }
    }
  });

  // Feature: gitlab-provider-support, Property 21: Locale catalog key parity
  it('none of the five new keys introduces an accidental prefix collision against any pre-existing key', () => {
    for (const locale of SUPPORTED_LOCALES) {
      const catalog = CATALOGS[locale];
      const allKeys = Object.keys(catalog);

      for (const newKey of NEW_KEYS) {
        for (const other of allKeys) {
          if (isDotPrefixOf(newKey, other)) {
            throw new Error(
              `[${locale}] new key "${newKey}" is a dot-notation prefix of pre-existing key "${other}"`,
            );
          }
          if (isDotPrefixOf(other, newKey)) {
            throw new Error(
              `[${locale}] pre-existing key "${other}" is a dot-notation prefix of new key "${newKey}"`,
            );
          }
        }
      }
    }
  });
});
