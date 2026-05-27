/**
 * Component tests for the SettingsPage Identity Store role ARN block
 * (Task 9.4).
 *
 * Scope:
 * - `GET /api/config` returning `identityStoreRoleArn` populates the input.
 * - Typing + clicking Save issues `PUT /api/config/identity-store-role-arn`
 *   with the current value in the body.
 * - Successful save renders the i18n-backed success message.
 * - Failed save renders the i18n-backed error message.
 * - Clearing the field and saving submits `{ identityStoreRoleArn: "" }`.
 *
 * The harness mirrors `pages/ptBrSnapshots.test.tsx`: `I18nProvider` +
 * stubbed `AuthContext` + `SplitPanelProvider` + `MemoryRouter`. `fetch`
 * is stubbed globally so `api/client.ts` resolves deterministically, and
 * a minimal in-memory `localStorage` shim is installed (the
 * `NODE_OPTIONS=--no-webstorage` test flag strips the real one).
 *
 * Validates Requirements 11.2, 11.8, 11.9.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';
import { I18nProvider } from '../../i18n/I18nProvider';
import { i18n } from '../../i18n/index';
import { AuthContext, type AuthContextValue, type AuthUser } from '../../auth/AuthProvider';
import { SplitPanelProvider } from '../../hooks/useSplitPanel';
import SettingsPage from '../SettingsPage';

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

function Harness({ children }: { children: ReactNode }) {
  return (
    <I18nProvider>
      <AuthContext.Provider value={makeAuthValue()}>
        <SplitPanelProvider>
          <MemoryRouter>{children}</MemoryRouter>
        </SplitPanelProvider>
      </AuthContext.Provider>
    </I18nProvider>
  );
}

/**
 * Description of a mocked request captured by the `fetch` stub. Kept
 * minimal — only the fields the tests need to assert on.
 */
interface CapturedRequest {
  url: string;
  method: string;
  body: unknown;
}

/**
 * Install a `fetch` stub that:
 * - Responds to `GET /api/config` with the provided payload.
 * - Responds to `GET /api/config/schedule` with a minimal disabled schedule.
 * - Delegates `PUT /api/config/identity-store-role-arn` to `putHandler` so
 *   the individual test can decide success / error / body shape.
 * - Returns a permissive `{}` for every other URL so the page's other
 *   effects don't throw.
 */
function installFetchStub(params: {
  config: Record<string, unknown>;
  putHandler: (body: unknown) => Response | Promise<Response>;
  captured: CapturedRequest[];
}) {
  const { config, putHandler, captured } = params;

  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = (init?.method ?? 'GET').toUpperCase();
    let body: unknown = undefined;
    if (typeof init?.body === 'string') {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    }
    captured.push({ url, method, body });

    if (method === 'GET' && url.endsWith('/api/config')) {
      return new Response(JSON.stringify(config), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (method === 'GET' && url.includes('/api/config/schedule')) {
      return new Response(
        JSON.stringify({
          expression: null,
          enabled: false,
          humanReadable: '',
          error: true,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }
    if (method === 'PUT' && url.endsWith('/api/config/identity-store-role-arn')) {
      return putHandler(body);
    }
    return new Response('{}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });

  vi.stubGlobal('fetch', fetchImpl);
  return fetchImpl;
}

/**
 * The Identity Store Role ARN `FormField` is inside the "Cross-Account
 * Access" container. Cloudscape wires the label to the input via
 * `aria-labelledby`, so we look up the `Input` element by resolving the
 * English label text back to its DOM id and following the `for`/
 * `aria-labelledby` linkage.
 *
 * In practice the simplest, version-stable lookup is: find the label text
 * node, walk up to its `FormField` wrapper, then query the `<input>`
 * inside that wrapper.
 */
function getIdentityStoreRoleArnInput(): HTMLInputElement {
  const labelText = i18n.t('settings.identityStoreRoleArn.label');
  const label = screen.getByText(labelText);
  // `FormField` renders the label inside a wrapper that also contains the
  // input; walking up a few levels reaches that wrapper.
  let node: HTMLElement | null = label;
  for (let i = 0; i < 6 && node; i++) {
    const input = node.querySelector('input');
    if (input) return input as HTMLInputElement;
    node = node.parentElement;
  }
  throw new Error('Identity Store role ARN input not found next to its label');
}

function getSaveButton(): HTMLButtonElement {
  const saveText = i18n.t('settings.identityStoreRoleArn.save');
  return screen.getByRole('button', { name: saveText }) as HTMLButtonElement;
}

describe('SettingsPage — Identity Store role ARN (Req 11.2, 11.8, 11.9)', () => {
  const memoryStore = new Map<string, string>();

  beforeAll(() => {
    // Install an in-memory localStorage so `api/client.ts` can read the
    // placeholder auth token. The `--no-webstorage` test flag strips the
    // real localStorage; without this shim every fetch path crashes.
    memoryStore.clear();
    memoryStore.set('kiro_id_token', 'test-token');
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
    // Force `en` before every test so asserted strings and label lookups
    // are deterministic. Another suite may have flipped the locale.
    if (i18n.language !== 'en') {
      await act(async () => {
        await i18n.changeLanguage('en');
      });
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('populates the input with the fetched identityStoreRoleArn', async () => {
    const captured: CapturedRequest[] = [];
    const fetchedArn = 'arn:aws:iam::123456789012:role/kiro-cost-analyzer-identity-store-read';
    installFetchStub({
      config: {
        bucketName: '',
        sourcePrefix: '',
        promptsPrefix: '',
        identityStoreId: '',
        sourceBucketRoleArn: '',
        identityStoreRoleArn: fetchedArn,
        etlStatus: null,
      },
      putHandler: () =>
        new Response(JSON.stringify({ status: 'valid' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      captured,
    });

    render(
      <Harness>
        <SettingsPage />
      </Harness>,
    );

    // Navigate to the Identity tab first
    const identityTab = await screen.findByTestId('identity');
    await act(async () => {
      fireEvent.click(identityTab);
    });

    await waitFor(() => {
      const input = getIdentityStoreRoleArnInput();
      expect(input.value).toBe(fetchedArn);
    });
  });

  it('typing + Save issues PUT /api/config/identity-store-role-arn with the current value', async () => {
    const captured: CapturedRequest[] = [];
    const initialArn = 'arn:aws:iam::111111111111:role/initial-role';
    const typedSuffix = '-edit';
    installFetchStub({
      config: {
        bucketName: '',
        sourcePrefix: '',
        promptsPrefix: '',
        identityStoreId: '',
        sourceBucketRoleArn: '',
        identityStoreRoleArn: initialArn,
        etlStatus: null,
      },
      putHandler: () =>
        new Response(JSON.stringify({ status: 'valid' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      captured,
    });

    render(
      <Harness>
        <SettingsPage />
      </Harness>,
    );

    // Navigate to the Identity tab first
    const identityTab = await screen.findByTestId('identity');
    await act(async () => {
      fireEvent.click(identityTab);
    });

    await waitFor(() => {
      expect(getIdentityStoreRoleArnInput().value).toBe(initialArn);
    });

    const user = userEvent.setup();
    const input = getIdentityStoreRoleArnInput();
    // Append characters to the existing value. userEvent.type focuses the
    // element first and fires realistic keydown/input events so
    // Cloudscape's controlled `Input` propagates every keystroke.
    await user.click(input);
    await user.type(input, typedSuffix);

    await waitFor(() => {
      expect(getIdentityStoreRoleArnInput().value).toBe(initialArn + typedSuffix);
    });

    await user.click(getSaveButton());

    await waitFor(() => {
      const put = captured.find(
        (c) => c.method === 'PUT' && c.url.endsWith('/api/config/identity-store-role-arn'),
      );
      expect(put).toBeDefined();
      expect(put!.body).toEqual({ identityStoreRoleArn: initialArn + typedSuffix });
    });
  });

  it('renders the i18n success message after a successful save', async () => {
    const captured: CapturedRequest[] = [];
    installFetchStub({
      config: {
        bucketName: '',
        sourcePrefix: '',
        promptsPrefix: '',
        identityStoreId: '',
        sourceBucketRoleArn: '',
        identityStoreRoleArn: 'arn:aws:iam::222222222222:role/some-role',
        etlStatus: null,
      },
      // Return `{ status: 'valid' }` with no `message` so the page falls
      // back to the i18n success key — that is what Req 11.10 mandates the
      // UI display when the backend does not send a custom message.
      putHandler: () =>
        new Response(JSON.stringify({ status: 'valid' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      captured,
    });

    render(
      <Harness>
        <SettingsPage />
      </Harness>,
    );

    // Navigate to the Identity tab first
    const identityTab = await screen.findByTestId('identity');
    await act(async () => {
      fireEvent.click(identityTab);
    });

    // Wait for the initial GET to populate the input.
    await waitFor(() => {
      expect(getIdentityStoreRoleArnInput().value).toBeTruthy();
    });

    const user = userEvent.setup();
    await user.click(getSaveButton());

    const successMsg = i18n.t('settings.identityStoreRoleArn.status.success');
    await waitFor(() => {
      expect(screen.getByText(successMsg)).toBeInTheDocument();
    });
  });

  it('renders the i18n error message when the save fails', async () => {
    const captured: CapturedRequest[] = [];
    installFetchStub({
      config: {
        bucketName: '',
        sourcePrefix: '',
        promptsPrefix: '',
        identityStoreId: '',
        sourceBucketRoleArn: '',
        identityStoreRoleArn: 'arn:aws:iam::333333333333:role/another-role',
        etlStatus: null,
      },
      // The handler treats `{ status: 'error' }` without a `message` as
      // the "fall back to the i18n error key" path (Req 11.10).
      putHandler: () =>
        new Response(JSON.stringify({ status: 'error' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      captured,
    });

    render(
      <Harness>
        <SettingsPage />
      </Harness>,
    );

    // Navigate to the Identity tab first
    const identityTab = await screen.findByTestId('identity');
    await act(async () => {
      fireEvent.click(identityTab);
    });

    await waitFor(() => {
      expect(getIdentityStoreRoleArnInput().value).toBeTruthy();
    });

    const user = userEvent.setup();
    await user.click(getSaveButton());

    const errorMsg = i18n.t('settings.identityStoreRoleArn.status.error');
    await waitFor(() => {
      expect(screen.getByText(errorMsg)).toBeInTheDocument();
    });
  });

  it('clearing the field and saving submits { identityStoreRoleArn: "" }', async () => {
    const captured: CapturedRequest[] = [];
    const initialArn = 'arn:aws:iam::444444444444:role/to-be-cleared';
    installFetchStub({
      config: {
        bucketName: '',
        sourcePrefix: '',
        promptsPrefix: '',
        identityStoreId: '',
        sourceBucketRoleArn: '',
        identityStoreRoleArn: initialArn,
        etlStatus: null,
      },
      putHandler: () =>
        new Response(JSON.stringify({ status: 'valid' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      captured,
    });

    render(
      <Harness>
        <SettingsPage />
      </Harness>,
    );

    // Navigate to the Identity tab first
    const identityTab = await screen.findByTestId('identity');
    await act(async () => {
      fireEvent.click(identityTab);
    });

    await waitFor(() => {
      expect(getIdentityStoreRoleArnInput().value).toBe(initialArn);
    });

    // Clear the input. Cloudscape `Input` is controlled, so the most
    // reliable reset is a direct React-compatible change event via
    // `fireEvent.change` on the underlying native input — `userEvent.clear`
    // also works but adds focus/blur noise we don't care about here.
    const input = getIdentityStoreRoleArnInput();
    await act(async () => {
      fireEvent.change(input, { target: { value: '' } });
    });

    await waitFor(() => {
      expect(getIdentityStoreRoleArnInput().value).toBe('');
    });

    const user = userEvent.setup();
    await user.click(getSaveButton());

    await waitFor(() => {
      const put = captured.find(
        (c) => c.method === 'PUT' && c.url.endsWith('/api/config/identity-store-role-arn'),
      );
      expect(put).toBeDefined();
      expect(put!.body).toEqual({ identityStoreRoleArn: '' });
    });
  });
});
