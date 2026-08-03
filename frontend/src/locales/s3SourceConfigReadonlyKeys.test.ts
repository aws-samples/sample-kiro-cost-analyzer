/**
 * Locale-content smoke test for the s3-source-config-readonly feature.
 *
 * The Settings page's bucket/prompts-prefix write path was removed, which
 * made ten translation keys dead (they were only used by the removed
 * editable fields and Save actions) while eight shared field-label/
 * description/title keys had to be retained for the new read-only display.
 *
 * This test asserts both conditions directly against the shipped catalogs,
 * for both `en.json` and `pt-BR.json`. The general-purpose build-time check
 * (`scripts/check-locales.ts`) already verifies full key-set parity,
 * non-empty values, and alphabetical sort order; this test does not
 * duplicate that mechanism. It exists to pin the specific removed/retained
 * key lists from this feature so a future change cannot silently
 * reintroduce a dead key or drop a still-needed one.
 *
 * Validates Requirements 7.4, 7.5.
 */

import { describe, it, expect } from 'vitest';
import enCatalog from './en.json';
import ptBRCatalog from './pt-BR.json';
import { SUPPORTED_LOCALES } from '../i18n/constants';
import type { SupportedLocale } from '../i18n/types';

type Catalog = Record<string, string>;

const CATALOGS: Record<SupportedLocale, Catalog> = {
  en: enCatalog as Catalog,
  'pt-BR': ptBRCatalog as Catalog,
};

// Feature: s3-source-config-readonly, Requirement 7.4 — dead keys removed.
const REMOVED_KEYS = [
  'settings.bucket.submit',
  'settings.bucket.nameField.placeholder',
  'settings.bucket.sourcePrefixField.placeholder',
  'settings.error.bucketNameRequired',
  'settings.error.save',
  'settings.success.saved',
  'settings.prompts.submit',
  'settings.prompts.prefixField.placeholder',
  'settings.error.savePromptsPrefix',
  'settings.success.promptsPrefixSaved',
] as const;

// Feature: s3-source-config-readonly, Requirement 7.5 — shared keys retained.
const RETAINED_KEYS = [
  'settings.bucket.nameField.label',
  'settings.bucket.nameField.description',
  'settings.bucket.sourcePrefixField.label',
  'settings.bucket.sourcePrefixField.description',
  'settings.prompts.prefixField.label',
  'settings.prompts.prefixField.description',
  'settings.bucket.title',
  'settings.prompts.title',
] as const;

describe('s3-source-config-readonly: locale catalog content', () => {
  // Feature: s3-source-config-readonly, Requirement 7.4
  it.each(SUPPORTED_LOCALES)(
    '[%s] none of the ten removed keys is present in the catalog',
    (locale) => {
      const catalog = CATALOGS[locale];
      for (const key of REMOVED_KEYS) {
        expect(
          Object.prototype.hasOwnProperty.call(catalog, key),
          `[${locale}] expected removed key "${key}" to be absent`,
        ).toBe(false);
      }
    },
  );

  // Feature: s3-source-config-readonly, Requirement 7.5
  it.each(SUPPORTED_LOCALES)(
    '[%s] all eight retained keys are present with non-empty string values',
    (locale) => {
      const catalog = CATALOGS[locale];
      for (const key of RETAINED_KEYS) {
        const value = catalog[key];
        expect(typeof value, `[${locale}] expected retained key "${key}" to exist as a string`).toBe(
          'string',
        );
        expect(value.length, `[${locale}] expected retained key "${key}" to be non-empty`).toBeGreaterThan(
          0,
        );
      }
    },
  );
});
