/**
 * Standalone context module for the theme API.
 *
 * Kept in its own file so `ThemeProvider.tsx` exports only components
 * (react-refresh/only-export-components rule).
 */

import { createContext } from 'react';
import type { ResolvedMode, VisualMode } from './types';

export interface ThemeContextValue {
  /** The user's selected preference (or DEFAULT_VISUAL_MODE on first boot). */
  visualMode: VisualMode;
  /** The concrete mode currently applied to the DOM ('light' | 'dark'). */
  resolvedMode: ResolvedMode;
  /** Persist the preference and re-apply the mode atomically. */
  setVisualMode: (next: VisualMode) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);
