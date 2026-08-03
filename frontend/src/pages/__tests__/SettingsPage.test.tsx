/**
 * Component tests for the SettingsPage Identity Store role ARN block
 * (Task 9.4), plus the read-only "Source Bucket" / "Prompts Configuration"
 * containers (Task 5.4, feature `s3-source-config-readonly`).
 *
 * Scope (Identity Store role ARN):
 * - `GET /api/config` returning `identityStoreRoleArn` populates the input.
 * - Typing + clicking Save issues `PUT /api/config/identity-store-role-arn`
 *   with the current value in the body.
 * - Successful save renders the i18n-backed success message.
 * - Failed save renders the i18n-backed error message.
 * - Clearing the field and saving submits `{ identityStoreRoleArn: "" }`.
 *
 * Scope (read-only bucket/prefix/prompts-prefix containers — Task 5.4):
 * - The "Source Bucket" and "Prompts Configuration" containers render no
 *   `<input>`/`<textarea>` and no button labeled with the removed
 *   `settings.bucket.submit`/`settings.prompts.submit` text.
 * - The "Prompts Configuration" container shows a loading indicator while a
 *   config fetch is pending, instead of the prefix value.
 * - The "Prompts Configuration" container shows an error indicator (with no
 *   prefix text) when the config fetch fails.
 *
 * The harness mirrors `pages/ptBrSnapshots.test.tsx`: `I18nProvider` +
 * stubbed `AuthContext` + `SplitPanelProvider` + `MemoryRouter`. `fetch`
 * is stubbed globally so `api/client.ts` resolves deterministically, and
 * a minimal in-memory `localStorage` shim is installed (the
 * `NODE_OPTIONS=--no-webstorage` test flag strips the real one).
 *
 * Validates Requirements 11.2, 11.8, 11.9 (Identity Store role ARN) and
 * 1.2, 1.3, 1.4, 2.3, 2.4, 2.5, 2.6 (read-only bucket/prompts containers).
 */

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import fc from 'fast-check';
import { MemoryRouter } from 'react-router';
import type { ReactNode } from 'react';
import { I18nProvider } from '../../i18n/I18nProvider';
import { i18n } from '../../i18n/index';
import { AuthContext, type AuthContextValue, type AuthUser } from '../../auth/AuthProvider';
import { SplitPanelProvider } from '../../hooks/useSplitPanel';
import SettingsPage, { displayValue } from '../SettingsPage';

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

/**
 * Read-only "Source Bucket" / "Prompts Configuration" containers
 * (Task 5.4, feature `s3-source-config-readonly`).
 *
 * Requirements 1.2/1.3/1.4/2.5/2.6 (no editable controls, no removed Save
 * buttons) are checked against the "Data" tab's rendered content as a
 * whole, since the whole point of the removal is that *no* editable
 * control for these three fields exists anywhere on the page, not merely
 * within one container's DOM subtree.
 *
 * Requirements 2.3/2.4 (loading indicator instead of a value; error
 * indicator instead of a value, with no stale prefix shown) are checked by
 * scoping to the "Prompts Configuration" container specifically, since that
 * container has state-aware rendering the "Source Bucket" container does
 * not.
 */
describe('SettingsPage — read-only Source Bucket / Prompts Configuration containers (Req 1.2, 1.3, 1.4, 2.3, 2.4, 2.5, 2.6)', () => {
  const memoryStore = new Map<string, string>();

  beforeAll(() => {
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
   * Install a `fetch` stub where `getConfigResponse` controls how
   * `GET /api/config` resolves: either a fixed `Response`, or a factory
   * producing a `Promise<Response>` that the test can leave pending to
   * observe the loading state. Every other request (including
   * `GET /api/config/schedule`) resolves immediately with an inert body so
   * the rest of the page's effects don't throw.
   */
  function installConfigFetchStub(
    getConfigResponse: () => Response | Promise<Response>,
  ) {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'GET' && url.endsWith('/api/config')) {
        return getConfigResponse();
      }
      if (method === 'GET' && url.includes('/api/config/schedule')) {
        return new Response(
          JSON.stringify({ expression: null, enabled: false, humanReadable: '', error: true }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    vi.stubGlobal('fetch', fetchImpl);
    return fetchImpl;
  }

  /**
   * Cloudscape renders a `Container`'s header and body as siblings inside a
   * shared `content-wrapper` div (see `container/internal.js`), which is
   * itself a sibling of every other container's `content-wrapper` under the
   * "Data" tab panel. Locating the `<h2>` heading and walking up to that
   * `content-wrapper` ancestor isolates one container's rendered content
   * from the other two containers on the same tab — this is what lets the
   * "no input anywhere in this container" assertions below target the
   * correct container rather than the whole tab.
   */
  function getContainerContentByHeading(headingText: string): HTMLElement {
    const heading = screen.getByRole('heading', { name: headingText, level: 2 });
    let node: HTMLElement | null = heading;
    for (let i = 0; i < 8 && node; i++) {
      if (node.className.includes('content-wrapper')) {
        return node;
      }
      node = node.parentElement;
    }
    throw new Error(`Could not find content-wrapper ancestor for heading "${headingText}"`);
  }

  it('renders the "Source Bucket" and "Prompts Configuration" containers with no editable controls or removed Save buttons', async () => {
    installConfigFetchStub(
      () =>
        new Response(
          JSON.stringify({
            bucketName: 'my-source-bucket',
            sourcePrefix: 'activities/AWSLogs/123456789012/KiroLogs/',
            promptsPrefix: 'prompts/AWSLogs/123456789012/KiroLogs/',
            identityStoreId: '',
            sourceBucketRoleArn: '',
            identityStoreRoleArn: '',
            etlStatus: null,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
    );

    render(
      <Harness>
        <SettingsPage />
      </Harness>,
    );

    const dataTab = await screen.findByTestId('data');
    await act(async () => {
      fireEvent.click(dataTab);
    });

    // Wait for the fetch to resolve and the read-only bucket value to render,
    // confirming the containers are past their loading state before we
    // assert on the absence of editable controls.
    await waitFor(() => {
      expect(screen.getByText('my-source-bucket')).toBeInTheDocument();
    });

    const bucketContainer = getContainerContentByHeading(i18n.t('settings.bucket.title'));
    const promptsContainer = getContainerContentByHeading(i18n.t('settings.prompts.title'));

    // Requirements 1.2/1.3/2.5: no Input/Textarea (editable form control) in
    // either container.
    expect(bucketContainer.querySelector('input')).toBeNull();
    expect(bucketContainer.querySelector('textarea')).toBeNull();
    expect(promptsContainer.querySelector('input')).toBeNull();
    expect(promptsContainer.querySelector('textarea')).toBeNull();

    // Requirements 1.4/2.6: no button anywhere on the page carries the
    // removed Save labels — the whole page is checked here (not just the
    // two containers) because the requirement is that no button, including
    // one belonging to a different setting, submits these removed writes.
    expect(screen.queryByRole('button', { name: 'settings.bucket.submit' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'settings.prompts.submit' })).toBeNull();
    expect(screen.queryByText('Save Configuration')).toBeNull();
    expect(screen.queryByText('Save Prompts Prefix')).toBeNull();

    // The values are shown as plain read-only text within their containers.
    expect(bucketContainer.textContent).toContain('my-source-bucket');
    expect(bucketContainer.textContent).toContain('activities/AWSLogs/123456789012/KiroLogs/');
    expect(promptsContainer.textContent).toContain('prompts/AWSLogs/123456789012/KiroLogs/');
  });

  it('renders a loading indicator in the Prompts Configuration container while the config fetch is pending, instead of a value', async () => {
    let resolveGetConfig: ((response: Response) => void) | null = null;
    installConfigFetchStub(
      () =>
        new Promise<Response>((resolve) => {
          resolveGetConfig = resolve;
        }),
    );

    render(
      <Harness>
        <SettingsPage />
      </Harness>,
    );

    // While the config fetch is pending, the page-level `loading` state is
    // true and `!etlStatus`, so the whole page renders the top-level
    // skeleton loader instead of the `Tabs` — the "data" tab is not yet in
    // the DOM. This is itself consistent with Requirement 2.3 (a loading
    // indicator is shown instead of a value) at the page level; the
    // Prompts Configuration container's own `StatusIndicator type="loading"`
    // branch is reached the moment the tab content is rendered, i.e. as
    // soon as the pending promise resolves and `loading` flips to `false`
    // is the wrong direction — instead, drive a second fetch (triggered by
    // an i18n language change, mirroring the app's real re-render path)
    // while the first load's tab content is already visible.
    await waitFor(() => {
      expect(screen.queryAllByTestId('skeleton-container').length).toBeGreaterThan(0);
    });

    // Resolve the initial pending config fetch so the page settles into the
    // "Data" tab, then trigger a second `GET /api/config` request (via a
    // locale change, which is a `fetchConfig` dependency) and leave THAT one
    // pending — this exercises the Prompts Configuration container's own
    // loading branch with the tab content already mounted.
    const secondFetchResolvers: ((response: Response) => void)[] = [];
    installConfigFetchStub(() => {
      return new Promise<Response>((resolve) => {
        secondFetchResolvers.push(resolve);
      });
    });
    await act(async () => {
      resolveGetConfig?.(
        new Response(
          JSON.stringify({
            bucketName: 'b',
            sourcePrefix: 'sp',
            promptsPrefix: 'initial-prompts-prefix',
            // A non-null `etlStatus` is required here: the page's top-level
            // loading branch is `loading && !etlStatus`, and the second
            // fetch below (triggered by the locale change) sets `loading`
            // back to `true`. Without a persisted `etlStatus`, the whole
            // page would fall back to the top-level skeleton loader again
            // instead of keeping the "Data" tab mounted with the Prompts
            // Configuration container's own loading branch visible.
            etlStatus: { lastExecution: '2024-01-01T00:00:00Z', status: 'success' },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.queryByTestId('data')).toBeInTheDocument();
    });

    await act(async () => {
      await i18n.changeLanguage('pt-BR');
    });

    const dataTab = screen.getByTestId('data');
    fireEvent.click(dataTab);

    const promptsContainer = getContainerContentByHeading(i18n.t('settings.prompts.title'));
    expect(
      within(promptsContainer).getByText(i18n.t('common.loading')),
    ).toBeInTheDocument();
    expect(promptsContainer.textContent).not.toContain('initial-prompts-prefix');

    // Resolve the pending refetch and restore English so later tests in
    // this suite are unaffected.
    secondFetchResolvers.forEach((resolve) =>
      resolve(
        new Response(
          JSON.stringify({ bucketName: 'b', sourcePrefix: 'sp', promptsPrefix: 'initial-prompts-prefix' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );
    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });

  it('renders an error indicator in the Prompts Configuration container (with no prefix text) when the config fetch fails', async () => {
    let requestCount = 0;
    installConfigFetchStub(() => {
      requestCount += 1;
      if (requestCount === 1) {
        return new Response(
          JSON.stringify({
            bucketName: 'b',
            sourcePrefix: 'sp',
            promptsPrefix: 'stale-prompts-prefix',
            etlStatus: null,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      // Every subsequent request (the refetch triggered below) fails.
      return new Response(JSON.stringify({ error: 'ServerError' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    render(
      <Harness>
        <SettingsPage />
      </Harness>,
    );

    await waitFor(() => {
      expect(screen.queryByTestId('data')).toBeInTheDocument();
    });

    // Trigger a refetch (via locale change) that fails, so `error` becomes
    // non-null while a previously loaded `promptsPrefix` value still sits
    // in state — this is exactly the "stale value must not be shown"
    // scenario in Requirement 2.4.
    await act(async () => {
      await i18n.changeLanguage('pt-BR');
    });

    const dataTab = screen.getByTestId('data');
    fireEvent.click(dataTab);

    const promptsContainer = getContainerContentByHeading(i18n.t('settings.prompts.title'));
    await waitFor(() => {
      expect(
        within(promptsContainer).getByText(i18n.t('common.error.loadData')),
      ).toBeInTheDocument();
    });
    expect(promptsContainer.textContent).not.toContain('stale-prompts-prefix');

    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });
});

/**
 * Property 2 (frontend counterpart) — `displayValue` totality over
 * arbitrary strings (Task 5.5, feature `s3-source-config-readonly`).
 *
 * `displayValue` is the one-line pure function backing the read-only
 * "Source Bucket" / "Prompts Configuration" containers' rendering of
 * `bucketName`/`sourcePrefix`/`promptsPrefix`: it is exported from
 * `SettingsPage.tsx` specifically so this property can exercise it
 * directly, per the design document's framing of it as "a one-line pure
 * function... exercised by this same property's frontend counterpart".
 */
describe('SettingsPage — Property 2 (frontend counterpart): displayValue totality (Req 1.1, 1.6, 2.1, 2.2)', () => {
  // Feature: s3-source-config-readonly, Property 2: GET /api/config display
  // fields are total and empty-parameter-tolerant (frontend `displayValue`
  // counterpart)
  it('for any string, displayValue returns the value unchanged when non-blank, or the "—" placeholder when blank', () => {
    fc.assert(
      fc.property(fc.string(), (value) => {
        const result = displayValue(value);
        if (value.trim() === '') {
          return result === '—';
        }
        return result === value;
      }),
      { numRuns: 100 },
    );
  });
});
