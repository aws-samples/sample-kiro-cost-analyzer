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

vi.mock('../../api/gitApi', () => ({
  listGitRepos: (...args: unknown[]) => listGitReposMock(...args),
  createGitRepo: vi.fn(),
  deleteGitRepo: vi.fn(),
  listGitMappings: (...args: unknown[]) => listGitMappingsMock(...args),
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

beforeEach(() => {
  vi.clearAllMocks();
  listGitReposMock.mockResolvedValue({ repositories: [] });
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
      await Promise.resolve();
    });

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
      await Promise.resolve();
    });

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

    const successText = i18n.t('gitSettings.mappings.success.removed');
    expect(await screen.findByText(successText)).toBeInTheDocument();
  });
});
