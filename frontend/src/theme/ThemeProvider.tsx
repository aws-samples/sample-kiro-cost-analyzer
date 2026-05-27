/**
 * ThemeProvider — applies the user's visual-mode preference to the DOM
 * via Cloudscape's `applyMode` and publishes the current mode on
 * `ThemeContext`.
 *
 * Resolution order on first render:
 *   1. `localStorage.kiro_theme` (if a supported `VisualMode`)
 *   2. `DEFAULT_VISUAL_MODE` (currently `'dark'`)
 *
 * `'browser-default'` subscribes to `matchMedia('(prefers-color-scheme:
 * dark)')` so the applied mode follows the system theme live.
 *
 * `setVisualMode(next)` persists the preference *before* calling
 * `applyMode`, so the write to localStorage is causally upstream of the
 * DOM mutation.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { applyMode, Mode } from '@cloudscape-design/global-styles';
import { ThemeContext, type ThemeContextValue } from './ThemeContext';
import { resolveInitialVisualMode, resolveToCloudscapeMode } from './resolveVisualMode';
import { persistVisualMode, readStoredVisualMode } from './persistence';
import type { ResolvedMode, VisualMode } from './types';

function applyResolvedMode(resolved: ResolvedMode): void {
  applyMode(resolved === 'dark' ? Mode.Dark : Mode.Light);
}

export interface ThemeProviderProps {
  children: ReactNode;
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const [visualMode, setVisualModeState] = useState<VisualMode>(() =>
    resolveInitialVisualMode(readStoredVisualMode()),
  );
  const [resolvedMode, setResolvedMode] = useState<ResolvedMode>(() =>
    resolveToCloudscapeMode(resolveInitialVisualMode(readStoredVisualMode())),
  );

  // Re-apply the mode whenever the preference changes.
  useEffect(() => {
    const next = resolveToCloudscapeMode(visualMode);
    setResolvedMode(next);
    applyResolvedMode(next);
  }, [visualMode]);

  // When the user chose 'browser-default', follow prefers-color-scheme live.
  useEffect(() => {
    if (visualMode !== 'browser-default') return;
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;

    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => {
      const next: ResolvedMode = mq.matches ? 'dark' : 'light';
      setResolvedMode(next);
      applyResolvedMode(next);
    };

    // Modern browsers use addEventListener; Safari < 14 used addListener.
    if (typeof mq.addEventListener === 'function') {
      mq.addEventListener('change', handler);
      return () => mq.removeEventListener('change', handler);
    }
    mq.addListener(handler);
    return () => mq.removeListener(handler);
  }, [visualMode]);

  const setVisualMode = useCallback((next: VisualMode) => {
    persistVisualMode(next);
    setVisualModeState(next);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ visualMode, resolvedMode, setVisualMode }),
    [visualMode, resolvedMode, setVisualMode],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
