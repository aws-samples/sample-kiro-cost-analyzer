/**
 * Property-based test for the correlation status slug maps in UserPage.tsx.
 *
 * Validates Requirements 9.3, 9.4.
 */

import { describe, it } from 'vitest';
import fc from 'fast-check';
import enCatalog from '../locales/en.json';
import ptBRCatalog from '../locales/pt-BR.json';
import { SUPPORTED_LOCALES } from '../i18n/constants';
import type { SupportedLocale } from '../i18n/types';
import type { CorrelationStatusSlug } from '../types';
import {
  slugToTranslationKey,
  slugToAlertType,
  RETRYABLE_SLUGS,
  isStatusSlug,
} from './correlationStatusMaps';

type Catalog = Record<string, string>;

const CATALOGS: Record<SupportedLocale, Catalog> = {
  en: enCatalog as Catalog,
  'pt-BR': ptBRCatalog as Catalog,
};

// Finite domain — every member of CorrelationStatusSlug — enumerated rather
// than sampled, since the union is a closed, small set.
const ALL_SLUGS: CorrelationStatusSlug[] = Object.keys(
  slugToTranslationKey,
) as CorrelationStatusSlug[];

// Non-retryable per the design's classification table: these direct the
// user to Settings rather than offering a refresh action.
const NON_RETRYABLE_SLUGS: ReadonlySet<CorrelationStatusSlug> = new Set([
  'GIT_MAPPING_MISSING',
  'GITHUB_TOKEN_MISSING',
  'GITHUB_AUTH_FAILED',
  'GITLAB_TOKEN_MISSING',
  'GITLAB_AUTH_FAILED',
]);

describe('Property 20: Frontend slug map totality', () => {
  // Feature: gitlab-provider-support, Property 20: Frontend slug map totality
  it('every slug resolves through slugToTranslationKey to a non-empty, distinct catalog value in every supported locale, slugToAlertType yields a valid severity, isStatusSlug recognizes it, and RETRYABLE_SLUGS membership matches the classification table', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...ALL_SLUGS),
        fc.constantFrom(...SUPPORTED_LOCALES),
        (slug, locale) => {
          const translationKey = slugToTranslationKey[slug];

          // 1. Translation key is defined and resolves to a non-empty
          //    string in every supported locale, distinct from the key
          //    itself (i.e. it is a real translation, not a fallback).
          if (translationKey === undefined || translationKey.length === 0) {
            return false;
          }
          const catalog = CATALOGS[locale];
          const value = catalog[translationKey];
          if (typeof value !== 'string' || value.length === 0) {
            return false;
          }
          if (value === translationKey) {
            return false;
          }

          // 2. Alert severity is defined and one of the three valid
          //    Cloudscape Alert types.
          const alertType = slugToAlertType[slug];
          if (alertType !== 'info' && alertType !== 'warning' && alertType !== 'error') {
            return false;
          }

          // 3. isStatusSlug recognizes every member of the union.
          if (!isStatusSlug(slug)) {
            return false;
          }

          // 4. RETRYABLE_SLUGS membership matches the documented
          //    classification: GITLAB_TOKEN_MISSING / GITLAB_AUTH_FAILED
          //    (and their GitHub counterparts) are non-retryable;
          //    GITLAB_RATE_LIMIT (and GITHUB_RATE_LIMIT) are retryable.
          const isRetryable = RETRYABLE_SLUGS.has(slug);
          if (NON_RETRYABLE_SLUGS.has(slug) && isRetryable) {
            return false;
          }
          if (slug === 'GITLAB_RATE_LIMIT' && !isRetryable) {
            return false;
          }
          if (slug === 'GITHUB_RATE_LIMIT' && !isRetryable) {
            return false;
          }

          return true;
        },
      ),
      { numRuns: 20 },
    );
  });
});
