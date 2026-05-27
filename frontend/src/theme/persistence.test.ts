/**
 * Tests for `theme/persistence.ts`.
 *
 * Mirrors `i18n/persistence.test.ts` — happy-path round-trip, storage
 * failure behaviors, and single-warn-per-session dedup.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  __resetThemePersistWarnedForTests,
  persistVisualMode,
  readStoredVisualMode,
} from './persistence';
import { THEME_STORAGE_KEY } from './constants';

beforeEach(() => {
  try {
    localStorage.removeItem(THEME_STORAGE_KEY);
  } catch {
    // ignore
  }
  __resetThemePersistWarnedForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('round-trip', () => {
  it('persistVisualMode then readStoredVisualMode returns the same value', () => {
    persistVisualMode('light');
    expect(readStoredVisualMode()).toBe('light');
    persistVisualMode('dark');
    expect(readStoredVisualMode()).toBe('dark');
    persistVisualMode('browser-default');
    expect(readStoredVisualMode()).toBe('browser-default');
  });

  it('readStoredVisualMode returns null when nothing has been stored', () => {
    expect(readStoredVisualMode()).toBeNull();
  });

  it('persistVisualMode writes under THEME_STORAGE_KEY', () => {
    persistVisualMode('light');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
  });
});

describe('setItem throws', () => {
  it('swallows the error', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(() => persistVisualMode('light')).not.toThrow();
  });

  it('warns exactly once per session', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    persistVisualMode('light');
    persistVisualMode('dark');
    persistVisualMode('browser-default');
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0][0]).toMatch(/Failed to persist visual-mode/);
  });
});
