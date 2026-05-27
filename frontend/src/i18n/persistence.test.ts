/**
 * Tests for `persistence.ts` (Task 1.17).
 *
 * Covers:
 * - Happy-path round-trip: write then read.
 * - `localStorage.getItem` throwing → `readStored()` returns `null`.
 * - `localStorage.setItem` throwing → `persistLocale()` swallows, warns once.
 * - Single-warn-per-session dedup.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { persistLocale, readStored, __resetPersistWarnedForTests } from './persistence';
import { LOCALE_STORAGE_KEY } from './constants';

// jsdom provides a working localStorage by default. Each test removes the
// key and resets the single-warn flag to stay hermetic. (We avoid
// `localStorage.clear()` since some test runners stub localStorage with an
// incomplete Storage API.)
beforeEach(() => {
  try {
    localStorage.removeItem(LOCALE_STORAGE_KEY);
  } catch {
    // ignore — individual tests handle storage-unavailable scenarios
  }
  __resetPersistWarnedForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('round-trip', () => {
  it('persistLocale then readStored returns the same value', () => {
    persistLocale('en');
    expect(readStored()).toBe('en');
    persistLocale('pt-BR');
    expect(readStored()).toBe('pt-BR');
  });

  it('readStored returns null when nothing has been stored', () => {
    expect(readStored()).toBeNull();
  });

  it('persistLocale writes under LOCALE_STORAGE_KEY', () => {
    persistLocale('en');
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('en');
  });
});

describe('readStored: getItem throws', () => {
  it('returns null without throwing', () => {
    const spy = vi
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('storage disabled');
      });
    expect(readStored()).toBeNull();
    spy.mockRestore();
  });
});

describe('persistLocale: setItem throws', () => {
  it('swallows the error', () => {
    const spy = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('quota exceeded');
      });
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(() => persistLocale('en')).not.toThrow();
    spy.mockRestore();
  });

  it('warns exactly once per session', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    persistLocale('en');
    persistLocale('pt-BR');
    persistLocale('en');
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0][0]).toMatch(/Failed to persist locale/);
  });

  it('warns again after the dedup flag is reset (simulates new session)', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    persistLocale('en');
    expect(warn).toHaveBeenCalledTimes(1);
    __resetPersistWarnedForTests();
    persistLocale('pt-BR');
    expect(warn).toHaveBeenCalledTimes(2);
  });
});
