/**
 * Single source of truth for supported Git providers in the frontend.
 *
 * Replaces the duplicated single-entry `PROVIDER_OPTIONS` literal that
 * previously lived in both `GitRepoForm.tsx` and `GitMappingForm.tsx`.
 */

import type { SelectProps } from '@cloudscape-design/components/select';
import type { TranslationKey } from '../locales/keys';

export const SUPPORTED_GIT_PROVIDERS = ['github', 'gitlab'] as const;

export type SupportedGitProvider = (typeof SUPPORTED_GIT_PROVIDERS)[number];

export function buildProviderOptions(
  t: (key: TranslationKey) => string,
): SelectProps.Option[] {
  return SUPPORTED_GIT_PROVIDERS.map((p) => ({
    value: p,
    label: t(`git.provider.${p}` as TranslationKey),
  }));
}
