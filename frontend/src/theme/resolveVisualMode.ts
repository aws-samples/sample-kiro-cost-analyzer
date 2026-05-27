/**
 * Pure resolution logic for the visual-mode preference.
 *
 * Mirrors `src/i18n/resolveLocale.ts`. Given a (possibly-invalid) stored
 * preference, returns the `VisualMode` that should be applied. The actual
 * `ResolvedMode` (what Cloudscape renders) is computed separately by
 * `resolveToCloudscapeMode`, which factors in the browser's
 * `prefers-color-scheme` media query.
 */

import { DEFAULT_VISUAL_MODE } from './constants';
import { SUPPORTED_VISUAL_MODES, type ResolvedMode, type VisualMode } from './types';

/**
 * Normalizes a stored string into a supported `VisualMode`. Unknown values
 * resolve to `DEFAULT_VISUAL_MODE` so boot is total over any stored input.
 */
export function resolveInitialVisualMode(stored: string | null): VisualMode {
  if (stored === null) return DEFAULT_VISUAL_MODE;
  if ((SUPPORTED_VISUAL_MODES as readonly string[]).includes(stored)) {
    return stored as VisualMode;
  }
  return DEFAULT_VISUAL_MODE;
}

/**
 * Maps a `VisualMode` to the concrete `ResolvedMode` that should be
 * applied to the DOM. `'browser-default'` consults
 * `window.matchMedia('(prefers-color-scheme: dark)')`; the other two are
 * straight pass-throughs.
 *
 * `matchMedia` defaults are engine-specific when unavailable (SSR, test
 * environments without stubs); we default to `'light'` in that case,
 * matching the browser's own default for unsupported media queries.
 */
export function resolveToCloudscapeMode(mode: VisualMode): ResolvedMode {
  if (mode === 'light') return 'light';
  if (mode === 'dark') return 'dark';
  // 'browser-default'
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'light';
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
