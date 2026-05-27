/**
 * Tests for `resolveVisualMode.ts`.
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { resolveInitialVisualMode, resolveToCloudscapeMode } from './resolveVisualMode';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('resolveInitialVisualMode', () => {
  it('honors each supported value', () => {
    expect(resolveInitialVisualMode('light')).toBe('light');
    expect(resolveInitialVisualMode('dark')).toBe('dark');
    expect(resolveInitialVisualMode('browser-default')).toBe('browser-default');
  });

  it('falls back to the default for null', () => {
    // Default is 'dark' (preserves pre-feature behavior).
    expect(resolveInitialVisualMode(null)).toBe('dark');
  });

  it('falls back to the default for unknown values', () => {
    expect(resolveInitialVisualMode('')).toBe('dark');
    expect(resolveInitialVisualMode('solarized')).toBe('dark');
    expect(resolveInitialVisualMode('LIGHT')).toBe('dark'); // case-sensitive match
  });
});

describe('resolveToCloudscapeMode', () => {
  it('maps explicit light/dark straight through', () => {
    expect(resolveToCloudscapeMode('light')).toBe('light');
    expect(resolveToCloudscapeMode('dark')).toBe('dark');
  });

  it('maps browser-default via matchMedia', () => {
    vi.stubGlobal('window', {
      matchMedia: vi.fn((query: string) => ({
        matches: query.includes('dark'),
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        onchange: null,
        dispatchEvent: vi.fn(),
      })),
    });
    expect(resolveToCloudscapeMode('browser-default')).toBe('dark');
  });

  it('maps browser-default to light when prefers-color-scheme is not dark', () => {
    vi.stubGlobal('window', {
      matchMedia: vi.fn(() => ({
        matches: false,
        media: '(prefers-color-scheme: dark)',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        onchange: null,
        dispatchEvent: vi.fn(),
      })),
    });
    expect(resolveToCloudscapeMode('browser-default')).toBe('light');
  });

  it('defaults to light when matchMedia is unavailable', () => {
    vi.stubGlobal('window', {});
    expect(resolveToCloudscapeMode('browser-default')).toBe('light');
  });
});
