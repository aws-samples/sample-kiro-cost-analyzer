/**
 * Theme constants.
 *
 * `DEFAULT_VISUAL_MODE` is `'dark'` to preserve the pre-feature behavior:
 * the app shipped with `applyMode(Mode.Dark)` wired statically in
 * `main.tsx`. Users who have never opened the settings menu continue to
 * see the dark theme; users who do open it can opt into light mode or let
 * the browser decide.
 */

import type { VisualMode } from './types';

/** localStorage key used to persist the user's visual-mode preference. */
export const THEME_STORAGE_KEY = 'kiro_theme';

/** Default visual mode when nothing is stored — preserves current behavior. */
export const DEFAULT_VISUAL_MODE: VisualMode = 'dark';
