/**
 * Tests for `GitMappingForm.tsx`.
 *
 * Scope (Task 15.7, Requirements 9.1, 9.2, 9.7):
 * - The provider `Select` field offers exactly `github` and `gitlab`,
 *   labelled from `git.provider.*`, derived from `buildProviderOptions`
 *   rather than a stale single-entry local literal.
 * - Submitting with a mocked `onSubmit` that resolves with
 *   `replaced: true` and a `previousGitUsername` renders a success
 *   message interpolating both the previous and current usernames, in
 *   both `en` and `pt-BR` (the two catalogs place the placeholders in
 *   different positions).
 * - Submitting with `replaced: false` (no `previousGitUsername`) renders
 *   the plain `gitMappingForm.success` message instead.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SelectProps } from '@cloudscape-design/components/select';
import { I18nProvider } from '../i18n/I18nProvider';
import { i18n } from '../i18n/index';
import GitMappingForm from './GitMappingForm';
import type { GitMappingCreated } from '../types';

const USER_OPTIONS: SelectProps.Option[] = [{ value: 'user-1', label: 'Test User' }];

async function setLocaleFor(locale: 'en' | 'pt-BR'): Promise<void> {
  if (i18n.language !== locale) {
    await act(async () => {
      await i18n.changeLanguage(locale);
    });
  }
}

function renderForm(onSubmit: (data: {
  userId: string;
  provider: string;
  gitUsername: string;
}) => Promise<GitMappingCreated>) {
  return render(
    <I18nProvider>
      <GitMappingForm userOptions={USER_OPTIONS} onSubmit={onSubmit} />
    </I18nProvider>,
  );
}

/**
 * Fills the user select, provider select, and Git username input, then
 * clicks Submit. Returns the current-username value used, so callers can
 * assert it appears in the rendered success message alongside the mocked
 * `previousGitUsername`.
 */
async function fillAndSubmit(currentUsername: string): Promise<void> {
  const user = userEvent.setup();

  const userPlaceholder = i18n.t('gitMappingForm.field.user.placeholder');
  await user.click(screen.getByText(userPlaceholder));
  await user.click(await screen.findByText('Test User'));

  const providerPlaceholder = i18n.t('gitMappingForm.field.provider.placeholder');
  await user.click(screen.getByText(providerPlaceholder));
  await user.click(await screen.findByText(i18n.t('git.provider.gitlab')));

  const usernamePlaceholder = i18n.t('gitMappingForm.field.gitUsername.placeholder');
  const usernameInput = screen.getByPlaceholderText(usernamePlaceholder);
  fireEvent.change(usernameInput, { target: { value: currentUsername } });

  const submitButton = screen.getByRole('button', { name: i18n.t('gitMappingForm.submit') });
  await act(async () => {
    fireEvent.click(submitButton);
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('GitMappingForm provider options', () => {
  it('offers exactly github and gitlab, labelled in the active locale (en)', async () => {
    await setLocaleFor('en');
    renderForm(vi.fn());

    const providerPlaceholder = i18n.t('gitMappingForm.field.provider.placeholder');
    const trigger = screen.getByText(providerPlaceholder);
    const user = userEvent.setup();
    await user.click(trigger);

    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(2);
    expect(options.map((o) => o.querySelector('[data-value]')?.getAttribute('title'))).toEqual([
      i18n.t('git.provider.github'),
      i18n.t('git.provider.gitlab'),
    ]);
  });
});

describe('GitMappingForm success message — replacement', () => {
  it('interpolates both usernames in en when replaced is true', async () => {
    await setLocaleFor('en');
    const currentUsername = 'new-user';
    const previousGitUsername = 'old-user';
    const onSubmit = vi.fn().mockResolvedValue({
      userId: 'user-1',
      provider: 'gitlab',
      gitUsername: currentUsername,
      createdAt: '2024-01-01T00:00:00Z',
      replaced: true,
      previousGitUsername,
    } satisfies GitMappingCreated);

    renderForm(onSubmit);
    await fillAndSubmit(currentUsername);

    expect(onSubmit).toHaveBeenCalledTimes(1);

    const expectedMessage = i18n.t('gitMappingForm.successReplaced', {
      previous: previousGitUsername,
      current: currentUsername,
    });
    expect(await screen.findByText(expectedMessage)).toBeInTheDocument();
    expect(screen.getByText(expectedMessage).textContent).toContain(previousGitUsername);
    expect(screen.getByText(expectedMessage).textContent).toContain(currentUsername);
  });

  it('interpolates both usernames in pt-BR when replaced is true', async () => {
    await setLocaleFor('pt-BR');
    const currentUsername = 'novo-usuario';
    const previousGitUsername = 'usuario-antigo';
    const onSubmit = vi.fn().mockResolvedValue({
      userId: 'user-1',
      provider: 'gitlab',
      gitUsername: currentUsername,
      createdAt: '2024-01-01T00:00:00Z',
      replaced: true,
      previousGitUsername,
    } satisfies GitMappingCreated);

    renderForm(onSubmit);
    await fillAndSubmit(currentUsername);

    expect(onSubmit).toHaveBeenCalledTimes(1);

    const expectedMessage = i18n.t('gitMappingForm.successReplaced', {
      previous: previousGitUsername,
      current: currentUsername,
    });
    expect(await screen.findByText(expectedMessage)).toBeInTheDocument();
    expect(screen.getByText(expectedMessage).textContent).toContain(previousGitUsername);
    expect(screen.getByText(expectedMessage).textContent).toContain(currentUsername);

    // restore default locale for other suites
    await setLocaleFor('en');
  });

  it('renders the plain success message when replaced is false (no previousGitUsername)', async () => {
    await setLocaleFor('en');
    const currentUsername = 'fresh-user';
    const onSubmit = vi.fn().mockResolvedValue({
      userId: 'user-1',
      provider: 'gitlab',
      gitUsername: currentUsername,
      createdAt: '2024-01-01T00:00:00Z',
      replaced: false,
      previousGitUsername: undefined,
    } satisfies GitMappingCreated);

    renderForm(onSubmit);
    await fillAndSubmit(currentUsername);

    expect(onSubmit).toHaveBeenCalledTimes(1);

    const plainMessage = i18n.t('gitMappingForm.success');
    expect(await screen.findByText(plainMessage)).toBeInTheDocument();

    // The "replaced" message must not be rendered instead.
    const replacedTemplate = i18n.t('gitMappingForm.successReplaced', {
      previous: 'anything',
      current: currentUsername,
    });
    expect(screen.queryByText(replacedTemplate)).not.toBeInTheDocument();
  });
});
