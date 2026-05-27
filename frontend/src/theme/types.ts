/**
 * Theme types for the user settings menu.
 *
 * `VisualMode` is the user-facing selection. `ResolvedMode` is what the
 * DOM actually renders at any moment: `browser-default` resolves to either
 * `light` or `dark` via `matchMedia('(prefers-color-scheme: dark)')`.
 */

/** User-facing visual-mode options, mirroring the AWS Console menu. */
export type VisualMode = 'browser-default' | 'light' | 'dark';

/** The actual Cloudscape `Mode` applied to the root at any moment. */
export type ResolvedMode = 'light' | 'dark';

export const SUPPORTED_VISUAL_MODES = [
  'browser-default',
  'light',
  'dark',
] as const satisfies readonly VisualMode[];
