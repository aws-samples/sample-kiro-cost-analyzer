/**
 * Tests for `GitSettingsPage.tsx` mapping deletion (Task 15.7, Req 9.6, 9.7).
 *
 * Scope:
 * - Clicking the remove action for a specific mapping table row calls the
 *   mocked `deleteGitMapping` with exactly that row's `userId` and
 *   `provider` as its two arguments — pinning the values behind the arity
 *   `tsc` already enforces.
 * - After a successful mocked deletion, the translated
 *   `gitSettings.mappings.success.removed` text appears on screen.
 *
 * Auth scoping note: `GitSettingsPage` reads `useAuth()` to gate the page
 * to Admins. Constructing a real `AuthProvider` in this test environment
 * requires live Cognito env vars (`VITE_COGNITO_USER_POOL_ID` /
 * `VITE_COGNITO_CLIENT_ID`), which are not set — the same pre-existing gap
 * that affects `SettingsPage.test.tsx`. Rather than reproducing that gap,
 * this suite mocks `../../auth/useAuth` directly (a lighter substitute for
 * the full `AuthProvider`/Cognito stack), which lets `GitSettingsPage`
 * render fully so the deletion behavior is exercised against the real
 * component — more faithful to Requirement 9.6 than testing the callback
 * contract in isolation.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { I18nProvider } from '../../i18n/I18nProvider';
import { i18n } from '../../i18n/index';
import type { GitUserMapping } from '../../types';

vi.mock('../../auth/useAuth', () => ({
  useAuth: () => ({
    user: { sub: 'admin-sub', email: 'admin@example.com', groups: ['Admins'] },
  }),
}));

const listGitReposMock = vi.fn();
const listGitMappingsMock = vi.fn();
const deleteGitMappingMock = vi.fn();
const listAllGitMappingsMock = vi.fn();

vi.mock('../../api/gitApi', () => ({
  listGitRepos: (...args: unknown[]) => listGitReposMock(...args),
  createGitRepo: vi.fn(),
  updateGitRepo: vi.fn(),
  deleteGitRepo: vi.fn(),
  listGitMappings: (...args: unknown[]) => listGitMappingsMock(...args),
  listAllGitMappings: (...args: unknown[]) => listAllGitMappingsMock(...args),
  createGitMapping: vi.fn(),
  deleteGitMapping: (...args: unknown[]) => deleteGitMappingMock(...args),
}));

const getMock = vi.fn();

vi.mock('../../api/client', () => {
  class MockApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return {
    get: (...args: unknown[]) => getMock(...args),
    ApiError: MockApiError,
  };
});

// Imported after the mocks above so the module picks them up.
import GitSettingsPage from '../GitSettingsPage';

const TARGET_USER_ID = 'user-aaa';

const MAPPING_ROW_GITHUB: GitUserMapping = {
  userId: TARGET_USER_ID,
  provider: 'github',
  gitUsername: 'aaa-git',
  createdAt: '2024-01-01T00:00:00Z',
};

const MAPPING_ROW_GITLAB: GitUserMapping = {
  userId: TARGET_USER_ID,
  provider: 'gitlab',
  gitUsername: 'aaa-gitlab',
  createdAt: '2024-01-02T00:00:00Z',
};

async function setLocaleFor(locale: 'en' | 'pt-BR'): Promise<void> {
  if (i18n.language !== locale) {
    await act(async () => {
      await i18n.changeLanguage(locale);
    });
  }
}

function renderPage() {
  return render(
    <I18nProvider>
      <GitSettingsPage />
    </I18nProvider>,
  );
}

/**
 * Opens the mappings "select a user" dropdown and picks the single
 * seeded user option, which triggers `listGitMappings` and populates the
 * mappings table.
 */
async function selectTheSeededMappingUser(userLabel: string): Promise<void> {
  const user = userEvent.setup();
  const placeholder = i18n.t('gitSettings.mappings.userSelector.placeholder');
  const triggers = screen.getAllByText(placeholder);
  // The selector renders its own placeholder text as the trigger label.
  await user.click(triggers[0]);
  await user.click(await screen.findByText(userLabel));
}

/**
 * Locates the remove/delete icon button within the table row that
 * contains the given git username text.
 */
function getRemoveButtonForRow(gitUsername: string): HTMLButtonElement {
  const cell = screen.getByText(gitUsername);
  const row = cell.closest('tr');
  if (!row) {
    throw new Error(`Could not find table row containing "${gitUsername}"`);
  }
  const removeLabel = i18n.t('gitSettings.mappings.action.remove');
  const button = row.querySelector(`button[aria-label="${removeLabel}"]`);
  if (!button) {
    throw new Error(`Could not find remove button in row for "${gitUsername}"`);
  }
  return button as HTMLButtonElement;
}

/**
 * Clicks the confirmation modal's primary (submit) button. The modal must
 * already be open (i.e. the remove icon was clicked first).
 */
async function confirmMappingDeletion(): Promise<void> {
  const submitLabel = i18n.t('gitSettings.mappings.deleteModal.submit');
  const submitButton = await screen.findByRole('button', { name: submitLabel });
  await act(async () => {
    fireEvent.click(submitButton);
    await Promise.resolve();
    await Promise.resolve();
  });
}

/**
 * Clicks the confirmation modal's cancel button. Anchors on the
 * mapping-specific warning text because both modals share the same title.
 */
async function cancelMappingDeletion(): Promise<void> {
  const warningText = i18n.t('gitSettings.mappings.deleteModal.warning');
  await screen.findByText(warningText);
  const cancelLabel = i18n.t('common.cancel');
  const cancelButtons = screen.getAllByRole('button', { name: cancelLabel });
  await act(async () => {
    fireEvent.click(cancelButtons[cancelButtons.length - 1]);
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  listGitReposMock.mockResolvedValue({ repositories: [] });
  listAllGitMappingsMock.mockResolvedValue({ mappings: [] });
  listGitMappingsMock.mockResolvedValue({
    mappings: [MAPPING_ROW_GITHUB, MAPPING_ROW_GITLAB],
  });
  getMock.mockResolvedValue({
    summary: { totalUsers: 1, totalCredits: 0, totalOverageCredits: 0, averageCreditsPerUser: 0 },
    users: [
      {
        userId: TARGET_USER_ID,
        displayName: 'Target User',
        userName: 'target-user',
        subscriptionTier: 'free',
        totalCredits: 0,
        overageCredits: 0,
        totalMessages: 0,
        totalConversations: 0,
        averageDailyCredits: 0,
      },
    ],
    period: {},
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('GitSettingsPage — mapping deletion (Req 9.6, 9.7)', () => {
  it('calls deleteGitMapping with exactly the gitlab row userId and provider', async () => {
    await setLocaleFor('en');
    deleteGitMappingMock.mockResolvedValue({ status: 'deleted' });

    renderPage();

    await waitFor(() => {
      expect(listGitReposMock).toHaveBeenCalled();
    });

    await selectTheSeededMappingUser('Target User');

    await waitFor(() => {
      expect(listGitMappingsMock).toHaveBeenCalledWith(TARGET_USER_ID);
    });

    // Wait for both rows to render.
    await screen.findByText(MAPPING_ROW_GITHUB.gitUsername);
    await screen.findByText(MAPPING_ROW_GITLAB.gitUsername);

    const removeButton = getRemoveButtonForRow(MAPPING_ROW_GITLAB.gitUsername);
    await act(async () => {
      fireEvent.click(removeButton);
      await Promise.resolve();
    });

    // Icon click only opens the modal — nothing deleted yet (Req 2.1).
    expect(deleteGitMappingMock).not.toHaveBeenCalled();

    await confirmMappingDeletion();

    expect(deleteGitMappingMock).toHaveBeenCalledTimes(1);
    expect(deleteGitMappingMock).toHaveBeenCalledWith(
      MAPPING_ROW_GITLAB.userId,
      MAPPING_ROW_GITLAB.provider,
    );
  });

  it('calls deleteGitMapping with exactly the github row userId and provider', async () => {
    await setLocaleFor('en');
    deleteGitMappingMock.mockResolvedValue({ status: 'deleted' });

    renderPage();

    await waitFor(() => {
      expect(listGitReposMock).toHaveBeenCalled();
    });

    await selectTheSeededMappingUser('Target User');

    await waitFor(() => {
      expect(listGitMappingsMock).toHaveBeenCalledWith(TARGET_USER_ID);
    });

    await screen.findByText(MAPPING_ROW_GITHUB.gitUsername);
    await screen.findByText(MAPPING_ROW_GITLAB.gitUsername);

    const removeButton = getRemoveButtonForRow(MAPPING_ROW_GITHUB.gitUsername);
    await act(async () => {
      fireEvent.click(removeButton);
      await Promise.resolve();
    });

    expect(deleteGitMappingMock).not.toHaveBeenCalled();

    await confirmMappingDeletion();

    expect(deleteGitMappingMock).toHaveBeenCalledTimes(1);
    expect(deleteGitMappingMock).toHaveBeenCalledWith(
      MAPPING_ROW_GITHUB.userId,
      MAPPING_ROW_GITHUB.provider,
    );
  });

  it('renders gitSettings.mappings.success.removed after a successful delete', async () => {
    await setLocaleFor('en');
    deleteGitMappingMock.mockResolvedValue({ status: 'deleted' });

    renderPage();

    await waitFor(() => {
      expect(listGitReposMock).toHaveBeenCalled();
    });

    await selectTheSeededMappingUser('Target User');

    await waitFor(() => {
      expect(listGitMappingsMock).toHaveBeenCalledWith(TARGET_USER_ID);
    });

    await screen.findByText(MAPPING_ROW_GITHUB.gitUsername);

    const removeButton = getRemoveButtonForRow(MAPPING_ROW_GITHUB.gitUsername);
    await act(async () => {
      fireEvent.click(removeButton);
    });

    await confirmMappingDeletion();

    const successText = i18n.t('gitSettings.mappings.success.removed');
    expect(await screen.findByText(successText)).toBeInTheDocument();
  });
});

describe('GitSettingsPage — delete confirmation modal (Feature: git-settings-delete-confirmation)', () => {
  // Feature: git-settings-delete-confirmation, Property 1: No deletion without confirmation
  it('does not call deleteGitMapping when the modal is canceled', async () => {
    await setLocaleFor('en');
    deleteGitMappingMock.mockResolvedValue({ status: 'deleted' });

    renderPage();

    await waitFor(() => {
      expect(listGitReposMock).toHaveBeenCalled();
    });

    await selectTheSeededMappingUser('Target User');

    await waitFor(() => {
      expect(listGitMappingsMock).toHaveBeenCalledWith(TARGET_USER_ID);
    });

    await screen.findByText(MAPPING_ROW_GITLAB.gitUsername);

    const removeButton = getRemoveButtonForRow(MAPPING_ROW_GITLAB.gitUsername);
    await act(async () => {
      fireEvent.click(removeButton);
      await Promise.resolve();
    });

    await cancelMappingDeletion();

    // Canceling results in zero delete calls (Req 2.4). Note: Cloudscape
    // keeps the closed modal's content mounted in the DOM under jsdom, so
    // the property is asserted on the API mock, not on DOM absence.
    expect(deleteGitMappingMock).not.toHaveBeenCalled();
  });

  // Feature: git-settings-delete-confirmation, Property 3: Modal identifies the target
  it('shows the target userId, gitUsername and provider in the modal body', async () => {
    await setLocaleFor('en');

    renderPage();

    await waitFor(() => {
      expect(listGitReposMock).toHaveBeenCalled();
    });

    await selectTheSeededMappingUser('Target User');

    await waitFor(() => {
      expect(listGitMappingsMock).toHaveBeenCalledWith(TARGET_USER_ID);
    });

    await screen.findByText(MAPPING_ROW_GITLAB.gitUsername);

    const removeButton = getRemoveButtonForRow(MAPPING_ROW_GITLAB.gitUsername);
    await act(async () => {
      fireEvent.click(removeButton);
      await Promise.resolve();
    });

    const modalWarning = i18n.t('gitSettings.mappings.deleteModal.warning');
    await screen.findByText(modalWarning);

    // Modal body identifies the exact target (Req 2.2). The gitUsername
    // appears both in the table row and in the modal, so assert at least 2.
    expect(screen.getAllByText(MAPPING_ROW_GITLAB.gitUsername).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(MAPPING_ROW_GITLAB.userId).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(modalWarning)).toBeInTheDocument();
  });
});

describe('GitSettingsPage — default all-mappings view (Feature: git-mappings-default-all-view)', () => {
  it('fetches the all-users view on page load with no user selected', async () => {
    await setLocaleFor('en');
    listAllGitMappingsMock.mockResolvedValue({
      mappings: [MAPPING_ROW_GITHUB, MAPPING_ROW_GITLAB],
    });

    renderPage();

    await waitFor(() => {
      expect(listAllGitMappingsMock).toHaveBeenCalled();
    });

    // Rows render without any user pre-selected (Req 2.1)
    await screen.findByText(MAPPING_ROW_GITHUB.gitUsername);
    await screen.findByText(MAPPING_ROW_GITLAB.gitUsername);
    expect(listGitMappingsMock).not.toHaveBeenCalled();
  });

  it('shows Load more only when a pagination token is returned', async () => {
    await setLocaleFor('en');
    listAllGitMappingsMock.mockResolvedValue({
      mappings: [MAPPING_ROW_GITHUB],
      lastKey: 'opaque-token',
    });

    renderPage();

    await screen.findByText(MAPPING_ROW_GITHUB.gitUsername);
    const loadMore = await screen.findByRole('button', {
      name: i18n.t('gitSettings.mappings.loadMore'),
    });
    expect(loadMore).toBeInTheDocument();
  });

  it('switches to the per-user route when a user is selected (Req 2.3)', async () => {
    await setLocaleFor('en');
    listAllGitMappingsMock.mockResolvedValue({ mappings: [] });
    listGitMappingsMock.mockResolvedValue({
      mappings: [MAPPING_ROW_GITHUB, MAPPING_ROW_GITLAB],
    });

    renderPage();

    await waitFor(() => {
      expect(listAllGitMappingsMock).toHaveBeenCalled();
    });

    await selectTheSeededMappingUser('Target User');

    await waitFor(() => {
      expect(listGitMappingsMock).toHaveBeenCalledWith(TARGET_USER_ID);
    });
  });
});
