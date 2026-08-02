/**
 * pt-BR snapshot regression tests (Task 4.31).
 *
 * Goal: catch accidental string drift in the pt-BR catalog. Each test sets
 * `localStorage.kiro_locale = 'pt-BR'` before rendering, wraps the page in a
 * minimal harness (I18nProvider + MemoryRouter + stubbed AuthContext), mocks
 * `fetch` so API calls resolve with sensible defaults, and snapshots the
 * visible translated text content (not the full DOM).
 *
 * Scope: `LoginPage`, `ForgotPasswordPage`, `ResetPasswordPage`,
 * `NewPasswordPage`, `SignupPage` (unauthenticated flows — no network), plus
 * `UsersPage`, `SettingsPage` with simple empty-response
 * fetch mocks. `DashboardPage`, `AccountUsagePage`, and `UserDetailPage`
 * depend on multiple interacting endpoints and formatter output that changes
 * with time; they are covered by their own component-level tests and by the
 * catalog parity / byte-identical pt-BR catalog assertions.
 *
 * Validates Requirements 8.1, 8.2.
 */

import { act, render } from '@testing-library/react';
import { beforeEach, beforeAll, afterAll, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import type { ReactNode } from 'react';
import { I18nProvider } from '../i18n/I18nProvider';
import { i18n } from '../i18n/index';
import { AuthContext, type AuthContextValue, type AuthUser } from '../auth/AuthProvider';
import { SplitPanelProvider } from '../hooks/useSplitPanel';
import LoginPage from './LoginPage';
import ForgotPasswordPage from './ForgotPasswordPage';
import ResetPasswordPage from './ResetPasswordPage';
import NewPasswordPage from './NewPasswordPage';
import SignupPage from './SignupPage';
import UsersPage from './UsersPage';
import SettingsPage from './SettingsPage';

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
  initialRoute?: string;
}

function Harness({ children, authValue, initialRoute = '/' }: HarnessProps) {
  return (
    <I18nProvider>
      <AuthContext.Provider value={authValue ?? makeAuthValue()}>
        <SplitPanelProvider>
          <MemoryRouter initialEntries={[initialRoute]}>{children}</MemoryRouter>
        </SplitPanelProvider>
      </AuthContext.Provider>
    </I18nProvider>
  );
}

/**
 * Extract the visible translated text as a newline-separated string,
 * skipping empty text nodes. This keeps snapshots robust against Cloudscape
 * internal DOM churn: we assert on the user-visible prose only.
 */
function extractVisibleText(root: HTMLElement): string {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts: string[] = [];
  let node: Node | null = walker.nextNode();
  while (node) {
    const raw = node.textContent ?? '';
    const trimmed = raw.trim();
    if (trimmed.length > 0) texts.push(trimmed);
    node = walker.nextNode();
  }
  return texts.join('\n');
}

async function emptyFetchResponse(path: string): Promise<Response> {
  // Return an empty-but-valid body for every endpoint the pages may hit.
  // The pages are tolerant to missing fields, so this keeps the snapshot
  // scoped to the static translated text.
  const url = typeof path === 'string' ? path : String(path);
  let body: unknown = {};
  if (url.includes('/api/users')) {
    body = { users: [] };
  } else if (url.includes('/api/config/schedule')) {
    body = { expression: null, enabled: false, humanReadable: '', error: true };
  } else if (url.includes('/api/config')) {
    body = {
      bucketName: '',
      sourcePrefix: '',
      promptsPrefix: '',
      identityStoreId: '',
      sourceBucketRoleArn: '',
      etlStatus: null,
    };
  }
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('pt-BR snapshot regression', () => {
  beforeAll(async () => {
    // Some of the pages call `localStorage.getItem` via `api/client.ts` to
    // read the auth token. The `--no-webstorage` test flag strips
    // localStorage entirely, so we shim a minimal in-memory implementation
    // for the duration of this suite.
    const memoryStore = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => memoryStore.get(k) ?? null,
      setItem: (k: string, v: string) => { memoryStore.set(k, v); },
      removeItem: (k: string) => { memoryStore.delete(k); },
      clear: () => memoryStore.clear(),
      key: (i: number) => [...memoryStore.keys()][i] ?? null,
      get length() { return memoryStore.size; },
    });

    // Install deterministic fetch mock for the suite.
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      return emptyFetchResponse(url);
    }));
  });

  afterAll(() => {
    vi.unstubAllGlobals();
  });

  beforeEach(async () => {
    // Force pt-BR before every render. The `NODE_OPTIONS=--no-webstorage`
    // flag strips localStorage in this environment, so switch the i18next
    // instance directly — persistence is tested elsewhere.
    if (i18n.language !== 'pt-BR') {
      await act(async () => {
        await i18n.changeLanguage('pt-BR');
      });
    }
  });

  it('LoginPage renders translated pt-BR text', async () => {
    const { container } = render(
      <Harness authValue={makeAuthValue({ isAuthenticated: false, user: null })}>
        <LoginPage />
      </Harness>,
    );
    await act(async () => { await Promise.resolve(); });
    expect(extractVisibleText(container)).toMatchSnapshot();
  });

  it('ForgotPasswordPage renders translated pt-BR text', async () => {
    const { container } = render(
      <Harness authValue={makeAuthValue({ isAuthenticated: false, user: null })}>
        <ForgotPasswordPage />
      </Harness>,
    );
    await act(async () => { await Promise.resolve(); });
    expect(extractVisibleText(container)).toMatchSnapshot();
  });

  it('ResetPasswordPage renders translated pt-BR text', async () => {
    const { container } = render(
      <Harness authValue={makeAuthValue({ isAuthenticated: false, user: null })}>
        <ResetPasswordPage />
      </Harness>,
    );
    await act(async () => { await Promise.resolve(); });
    expect(extractVisibleText(container)).toMatchSnapshot();
  });

  it('NewPasswordPage renders translated pt-BR text', async () => {
    const { container } = render(
      <Harness
        authValue={makeAuthValue({
          isAuthenticated: false,
          user: null,
          newPasswordRequired: true,
          newPasswordEmail: 'admin@example.com',
        })}
      >
        <NewPasswordPage />
      </Harness>,
    );
    await act(async () => { await Promise.resolve(); });
    expect(extractVisibleText(container)).toMatchSnapshot();
  });

  it('SignupPage renders translated pt-BR text', async () => {
    const { container } = render(
      <Harness authValue={makeAuthValue({ isAuthenticated: false, user: null })}>
        <SignupPage />
      </Harness>,
    );
    await act(async () => { await Promise.resolve(); });
    expect(extractVisibleText(container)).toMatchSnapshot();
  });

  it('UsersPage renders translated pt-BR text', async () => {
    const { container } = render(
      <Harness>
        <UsersPage />
      </Harness>,
    );
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(extractVisibleText(container)).toMatchSnapshot();
  });

  it('SettingsPage renders translated pt-BR text', async () => {
    const { container } = render(
      <Harness>
        <SettingsPage />
      </Harness>,
    );
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(extractVisibleText(container)).toMatchSnapshot();
  });

});
