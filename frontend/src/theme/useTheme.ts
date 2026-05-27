/**
 * Public hook for reading/writing the visual-mode preference.
 *
 * Throws when called outside `ThemeProvider` so missing wiring is caught
 * immediately in development.
 */

import { useContext } from 'react';
import { ThemeContext, type ThemeContextValue } from './ThemeContext';

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useTheme must be used within <ThemeProvider>');
  }
  return ctx;
}
