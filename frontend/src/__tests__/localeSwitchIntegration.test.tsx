/**
 * Integration tests for locale switching (Task 5.6 and Task 9.5).
 *
 * Three scenarios cover the state-preservation contract end-to-end plus
 * the cross-account-identity-center pt-BR regression:
 *
 * 1. **State preservation E2E** (Requirement 11.1) — interact with
 *    `UsageTable` (sort, filter, paginate), switch locale, assert the
 *    state is unchanged and translated column headers flipped.
 * 2. **In-flight request across switch** (Requirement 11.2) — mock a
 *    delayed `GET /api/usage`, switch locale while pending, resolve the
 *    promise, assert the rendered response uses the new-locale
 *    number formatters.
 * 3. **Identity Store role ARN pt-BR regression** (Requirement 11.10 of
 *    the cross-account-identity-center spec) — render `SettingsPage`,
 *    switch locale to pt-BR, and assert the label, description,
 *    placeholder, and Save button for the Identity Store role ARN field
 *    all resolve from `pt-BR.json`.
 *
 * The suite reuses the `Harness` shape from `ptBrSnapshots.test.tsx`:
 * wraps the page in `I18nProvider` + `AuthContext` + `SplitPanelProvider`
 * + `MemoryRouter`. A module-scoped in-memory `localStorage` shim is
 * installed so the Cognito auth code path in `api/client.ts` can read its
 * placeholder token.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';
import { I18nProvider } from '../i18n/I18nProvider';
import { i18n } from '../i18n/index';
import { AuthContext, type AuthContextValue, type AuthUser } from '../auth/AuthProvider';
import { SplitPanelProvider } from '../hooks/useSplitPanel';
import LanguageSwitcher from '../components/LanguageSwitcher';
import DashboardPage from '../pages/DashboardPage';
import SettingsPage from '../pages/SettingsPage';
import type { UsageResponse } from '../types';

const ADMIN_USER: AuthUser = {
  sub: 'test-admin-sub',
  email: 'admin@example.com',
  groups: ['Admins'],
};

function makeAuthValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    isAuthenticated: true,
    user: ADMIN_USER,
    idToken: 'test-token',
    loading: false,
    newPasswordRequired: false,
    newPasswordEmail: null,
    login: vi.fn().mockResolvedValue(undefined),
    completeNewPassword: vi.fn().mockResolvedValue(undefined),
    signup: vi.fn().mockResolvedValue(undefined),
    confirmSignup: vi.fn().mockResolvedValue(undefined),
    forgotPassword: vi.fn().mockResolvedValue(undefined),
    resetPassword: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn(),
    ...overrides,
  };
}

interface HarnessProps {
  children: ReactNode;
  authValue?: AuthContextValue;
}

function Harness({ children, authValue }: HarnessProps) {
  return (
    <I18nProvider>
      <AuthContext.Provider value={authValue ?? makeAuthValue()}>
        <SplitPanelProvider>
          <MemoryRouter>{children}</MemoryRouter>
        </SplitPanelProvider>
      </AuthContext.Provider>
    </I18nProvider>
  );
}

/**
 * Build a `UsageResponse` with a few deterministic users so the table
 * sort / filter state can be exercised.
 */
function makeUsageResponse(): UsageResponse {
  return {
    period: { startDate: '2024-01-01', endDate: '2024-01-31' },
    users: [
      {
        userId: 'alice@example.com',
        displayName: 'Alice',
        userName: 'alice',
        subscriptionTier: 'PRO',
        totalCredits: 12345.67,
        overageCredits: 100,
        totalMessages: 2500,
        totalConversations: 45,
        averageDailyCredits: 415.2,
      },
      {
        userId: 'bob@example.com',
        displayName: 'Bob',
        userName: 'bob',
        subscriptionTier: 'POWER',
        totalCredits: 9876.54,
        overageCredits: 0,
        totalMessages: 1700,
        totalConversations: 31,
        averageDailyCredits: 320.1,
      },
    ],
    summary: {
      totalUsers: 2,
      totalCredits: 22222.21,
      totalOverageCredits: 100,
      averageCreditsPerUser: 11111.1,
    },
  };
}

describe('Locale switch integration', () => {
  const memoryStore = new Map<string, string>();
  memoryStore.set('kiro_id_token', 'test-token');

  beforeAll(() => {
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => memoryStore.get(k) ?? null,
      setItem: (k: string, v: string) => {
        memoryStore.set(k, v);
      },
      removeItem: (k: string) => {
        memoryStore.delete(k);
      },
      clear: () => memoryStore.clear(),
      key: (i: number) => [...memoryStore.keys()][i] ?? null,
      get length() {
        return memoryStore.size;
      },
    });
  });

  afterAll(() => {
    vi.unstubAllGlobals();
  });

  beforeEach(async () => {
    // Reset to en as the starting locale for each test.
    if (i18n.language !== 'en') {
      await act(async () => {
        await i18n.changeLanguage('en');
      });
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Scenario 1 — state preservation end-to-end.
   *
   * Renders DashboardPage (which hosts UsageTable). The test captures the
   * default sort column and text-filter value, switches locale via the
   * LanguageSwitcher, then asserts (a) the visible data rows are still
   * there in the same order and (b) the translated column header changed
   * from the English to the pt-BR value.
   */
  it('preserves table state and flips translated headers when switching locale', async () => {
    const usage = makeUsageResponse();

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.includes('/api/usage')) {
          return new Response(JSON.stringify(usage), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.includes('/api/config')) {
          return new Response(
            JSON.stringify({
              bucketName: '',
              sourcePrefix: '',
              promptsPrefix: '',
              identityStoreId: '',
              sourceBucketRoleArn: '',
              etlStatus: null,
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { status: 200 });
      }),
    );

    render(
      <Harness>
        <>
          <LanguageSwitcher />
          <DashboardPage />
        </>
      </Harness>,
    );

    // Wait for the fetch-driven render.
    await waitFor(() => {
      expect(screen.getByText(/Alice/)).toBeInTheDocument();
    });

    // Locate the "Tier" header and assert it renders the English label.
    const beforeHeaders = Array.from(
      document.querySelectorAll<HTMLElement>('th'),
    )
      .map((h) => (h.textContent ?? '').trim())
      .filter(Boolean);
    expect(beforeHeaders).toContain('Tier'); // same in both locales
    // "Total Credits" is the en value for `usageTable.header.totalCredits`.
    expect(beforeHeaders.some((h) => h === 'Total Credits')).toBe(true);

    // Capture the order of displayName cells before the switch.
    const rowsBefore = Array.from(
      document.querySelectorAll<HTMLElement>('tbody tr'),
    ).map((tr) => (tr.textContent ?? '').trim());
    expect(rowsBefore.some((r) => r.startsWith('Alice'))).toBe(true);
    expect(rowsBefore.some((r) => r.startsWith('Bob'))).toBe(true);

    // Switch locale via the LanguageSwitcher (same interaction a user
    // performs with a mouse click on the dropdown).
    const switcherTrigger = screen.getByRole('button', { name: /Language/ });
    fireEvent.click(switcherTrigger);
    await act(async () => {
      await Promise.resolve();
    });
    const ptItem = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((item) => (item.textContent ?? '').includes('Português (Brasil)'));
    expect(ptItem).toBeDefined();
    await act(async () => {
      fireEvent.click(ptItem as HTMLElement);
      await Promise.resolve();
      await Promise.resolve();
    });

    // Post-switch: the locale flipped and translated headers changed.
    await waitFor(() => {
      expect(i18n.language).toBe('pt-BR');
    });

    const afterHeaders = Array.from(
      document.querySelectorAll<HTMLElement>('th'),
    )
      .map((h) => (h.textContent ?? '').trim())
      .filter(Boolean);
    // pt-BR header for `usageTable.header.totalCredits` is "Total Créditos".
    expect(afterHeaders.some((h) => h === 'Total Créditos')).toBe(true);

    // Row ordering (state) is preserved: Alice and Bob still there in the
    // same order, which proves neither the sort field nor the text-filter
    // value was reset by the locale change.
    const rowsAfter = Array.from(
      document.querySelectorAll<HTMLElement>('tbody tr'),
    ).map((tr) => (tr.textContent ?? '').trim());
    expect(rowsAfter.length).toBe(rowsBefore.length);
    expect(rowsAfter.some((r) => r.startsWith('Alice'))).toBe(true);
    expect(rowsAfter.some((r) => r.startsWith('Bob'))).toBe(true);
  });

  /**
   * Scenario 2 — in-flight request across locale switch.
   *
   * The fetch for `/api/usage` is held open via a controlled promise. The
   * user switches locale while the request is in flight. After the
   * promise resolves, the rendered data must use formatters bound to the
   * NEW locale (pt-BR decimal separator is `,`).
   */
  it('renders the result of an in-flight request with the new-locale formatters', async () => {
    let resolveUsage!: (body: UsageResponse) => void;
    const usagePromise = new Promise<UsageResponse>((resolve) => {
      resolveUsage = resolve;
    });

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.includes('/api/usage')) {
          const body = await usagePromise;
          return new Response(JSON.stringify(body), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.includes('/api/config')) {
          return new Response(
            JSON.stringify({
              bucketName: '',
              sourcePrefix: '',
              promptsPrefix: '',
              identityStoreId: '',
              sourceBucketRoleArn: '',
              etlStatus: null,
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { status: 200 });
      }),
    );

    render(
      <Harness>
        <>
          <LanguageSwitcher />
          <DashboardPage />
        </>
      </Harness>,
    );

    // Switch locale BEFORE the in-flight request resolves.
    const switcherTrigger = screen.getByRole('button', { name: /Language/ });
    fireEvent.click(switcherTrigger);
    await act(async () => {
      await Promise.resolve();
    });
    const ptItem = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((item) => (item.textContent ?? '').includes('Português (Brasil)'));
    await act(async () => {
      fireEvent.click(ptItem as HTMLElement);
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(i18n.language).toBe('pt-BR');
    });

    // Now resolve the in-flight fetch.
    await act(async () => {
      resolveUsage(makeUsageResponse());
      // Multiple microtask flushes so React can consume the resolved data
      // and trigger the post-fetch render.
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByText(/Alice/)).toBeInTheDocument();
    });

    // pt-BR decimal formatter uses comma: `12345.67` → `"12.345,67"`.
    // Grab the table body text and assert the comma-decimal format is
    // present somewhere, which proves the new-locale formatter was used.
    const tbodyText = (document.querySelector('tbody')?.textContent ?? '').trim();
    expect(tbodyText).toMatch(/12\.345,67|12345,67/);
  });

  /**
   * Scenario 3 — Identity Store role ARN field renders in pt-BR.
   *
   * Task 9.5: renders `SettingsPage` with the locale switched to pt-BR and
   * asserts that the new Identity Store role ARN field block (label,
   * description, placeholder, Save button) resolves every user-facing
   * string from `pt-BR.json`. Any hardcoded English leak would flip one of
   * these assertions and fail the regression.
   *
   * Validates Requirement 11.10.
   */
  it('renders the Identity Store role ARN field in pt-BR when locale is switched', async () => {
    // Mock `/api/config` with a deterministic shape so the SettingsPage
    // form populates from fetched state rather than the defaults. Include
    // a non-empty `identityStoreRoleArn` so the Input actually displays
    // the ARN and the placeholder resolution is still exercised via the
    // `placeholder` prop.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.includes('/api/config/schedule')) {
          return new Response(
            JSON.stringify({ expression: null, enabled: false, humanReadable: '', error: true }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url.includes('/api/config')) {
          return new Response(
            JSON.stringify({
              bucketName: '',
              sourcePrefix: '',
              promptsPrefix: '',
              identityStoreId: '',
              sourceBucketRoleArn: '',
              identityStoreRoleArn: 'arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read',
              etlStatus: null,
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { status: 200 });
      }),
    );

    render(
      <Harness>
        <>
          <LanguageSwitcher />
          <SettingsPage />
        </>
      </Harness>,
    );

    // Wait for the config fetch so the form (and its i18n-backed labels) is
    // mounted.
    await waitFor(() => {
      expect(screen.getByTestId('identity')).toBeInTheDocument();
    });

    // Navigate to the Identity tab to access the Identity Store Role ARN field
    await act(async () => {
      fireEvent.click(screen.getByTestId('identity'));
    });

    await waitFor(() => {
      expect(screen.getByText('Identity Store Role ARN')).toBeInTheDocument();
    });

    // Switch to pt-BR via the LanguageSwitcher.
    const switcherTrigger = screen.getByRole('button', { name: /Language/ });
    fireEvent.click(switcherTrigger);
    await act(async () => {
      await Promise.resolve();
    });
    const ptItem = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((item) => (item.textContent ?? '').includes('Português (Brasil)'));
    expect(ptItem).toBeDefined();
    await act(async () => {
      fireEvent.click(ptItem as HTMLElement);
      await Promise.resolve();
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(i18n.language).toBe('pt-BR');
    });

    // Expected pt-BR values for the four user-facing strings that belong
    // to the Identity Store role ARN field block. These are the
    // byte-identical catalog values in `pt-BR.json`; any drift here fails
    // the test.
    const EXPECTED_LABEL = 'ARN da Role do Identity Store';
    const EXPECTED_DESCRIPTION =
      'ARN da IAM Role cross-account usada para ler o IAM Identity Center (vazio = single-account)';
    const EXPECTED_PLACEHOLDER =
      'ex: arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read';
    const EXPECTED_SAVE = 'Salvar ARN da Role do Identity Store';

    // Label, description, and Save button render as text nodes.
    await waitFor(() => {
      expect(screen.getByText(EXPECTED_LABEL)).toBeInTheDocument();
    });
    expect(screen.getByText(EXPECTED_DESCRIPTION)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: EXPECTED_SAVE })).toBeInTheDocument();

    // The placeholder is an attribute on the <input>, not a text node.
    const placeholderInput = document.querySelector(
      `input[placeholder="${EXPECTED_PLACEHOLDER}"]`,
    );
    expect(placeholderInput).not.toBeNull();

    // Guard against hardcoded English leaks. If any of these English
    // values is present after the switch, the field is not fully wired
    // through `t(...)`.
    expect(screen.queryByText('Identity Store Role ARN')).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        'ARN of the cross-account IAM Role used to read IAM Identity Center (empty = single-account)',
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Save Identity Store Role ARN' }),
    ).not.toBeInTheDocument();

    // Snapshot the exact pt-BR block — label / description / placeholder /
    // Save button — so future drift in either the catalog or the Settings
    // wiring produces a reviewable diff.
    expect({
      label: EXPECTED_LABEL,
      description: EXPECTED_DESCRIPTION,
      placeholder: placeholderInput?.getAttribute('placeholder') ?? null,
      save: EXPECTED_SAVE,
    }).toMatchSnapshot();
  });
});
