/**
 * Tests for `I18nProvider.tsx` + `useI18n.ts` (Task 1.18).
 *
 * Covers:
 * - `useI18n()` throws when called outside the provider.
 * - `setLocale(L)` calls `persistLocale(L)` *before* `i18n.changeLanguage(L)`
 *   (assert via spy call order).
 * - A locale change produces exactly one re-render of a probe child
 *   (render counter).
 */

import { act, render, renderHook, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { useRef } from 'react';
import * as persistence from './persistence';
import { i18n } from './index';
import { I18nProvider } from './I18nProvider';
import { useI18n } from './useI18n';

describe('useI18n outside provider', () => {
  it('throws a useful error', () => {
    // renderHook without a wrapper will cause useI18n to throw on first call.
    // Vitest/React will surface the error via the hook invocation.
    expect(() => renderHook(() => useI18n())).toThrow(
      /useI18n must be used within <I18nProvider>/,
    );
  });
});

describe('setLocale ordering', () => {
  beforeEach(() => {
    // Start from a known locale.
    if (i18n.language !== 'en') {
      return i18n.changeLanguage('en');
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls persistLocale before i18n.changeLanguage', async () => {
    const order: string[] = [];

    const persistSpy = vi
      .spyOn(persistence, 'persistLocale')
      .mockImplementation((loc) => {
        order.push(`persist:${loc}`);
      });

    const changeSpy = vi
      .spyOn(i18n, 'changeLanguage')
      .mockImplementation((async (loc: string) => {
        order.push(`change:${loc}`);
        return ((_key: string) => _key) as never;
      }) as typeof i18n.changeLanguage);

    const { result } = renderHook(() => useI18n(), {
      wrapper: ({ children }) => <I18nProvider>{children}</I18nProvider>,
    });

    await act(async () => {
      await result.current.setLocale('pt-BR');
    });

    // persist must appear before change
    const persistIdx = order.findIndex((s) => s === 'persist:pt-BR');
    const changeIdx = order.findIndex((s) => s === 'change:pt-BR');
    expect(persistIdx).toBeGreaterThanOrEqual(0);
    expect(changeIdx).toBeGreaterThanOrEqual(0);
    expect(persistIdx).toBeLessThan(changeIdx);

    persistSpy.mockRestore();
    changeSpy.mockRestore();
  });
});

describe('render-count invariant under locale switch', () => {
  it('one locale switch produces exactly one re-render of a probe child', async () => {
    // Start from a known locale.
    await act(async () => {
      if (i18n.language !== 'en') {
        await i18n.changeLanguage('en');
      }
    });

    // Use a container object so the test-time assignment is treated as
    // a mutation (allowed) rather than a reassignment of a captured let
    // (flagged by react-hooks/globals).
    const counter = { count: 0 };

    function Probe() {
      const { locale } = useI18n();
      // Count renders via a ref to avoid triggering extra renders.
      const ref = useRef<number>(0);
      ref.current += 1;
      // eslint-disable-next-line react-hooks/globals -- test probe intentionally mutates external counter
      counter.count = ref.current;
      return <span data-testid="probe">{locale}</span>;
    }

    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );

    // Give react-i18next a tick to settle any async init.
    await act(async () => {
      await Promise.resolve();
    });

    const initialRenders = counter.count;
    expect(screen.getByTestId('probe').textContent).toBe('en');

    // Trigger a real locale change via i18next so only the framework-driven
    // re-render path is exercised.
    await act(async () => {
      await i18n.changeLanguage('pt-BR');
    });

    // Expect exactly one additional render (the tree receives the new
    // language and re-commits once).
    expect(counter.count - initialRenders).toBe(1);
    expect(screen.getByTestId('probe').textContent).toBe('pt-BR');

    // Restore for the rest of the suite.
    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });
});
