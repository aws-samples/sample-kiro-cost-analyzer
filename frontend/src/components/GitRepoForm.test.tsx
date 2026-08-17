/**
 * Tests for `GitRepoForm.tsx`.
 *
 * Scope (Task 15.7, Requirements 9.1, 9.2):
 * - The provider `Select` field offers exactly the two options `github`
 *   and `gitlab`, labelled from the `git.provider.*` translation keys,
 *   proving the options come from `buildProviderOptions` (constants/
 *   gitProviders.ts) rather than a stale single-entry local literal.
 */

import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n/I18nProvider';
import { i18n } from '../i18n/index';
import GitRepoForm from './GitRepoForm';

async function setLocaleFor(locale: 'en' | 'pt-BR'): Promise<void> {
  if (i18n.language !== locale) {
    await act(async () => {
      await i18n.changeLanguage(locale);
    });
  }
}

function renderForm() {
  return render(
    <I18nProvider>
      <GitRepoForm visible onDismiss={vi.fn()} onSubmit={vi.fn().mockResolvedValue(undefined)} />
    </I18nProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('GitRepoForm provider options', () => {
  it('offers exactly github and gitlab, labelled in the active locale (en)', async () => {
    await setLocaleFor('en');
    renderForm();

    const providerLabel = i18n.t('gitRepoForm.field.provider.label');
    const providerPlaceholder = i18n.t('gitRepoForm.field.provider.placeholder');
    expect(screen.getByText(providerLabel)).toBeInTheDocument();

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

  it('offers exactly github and gitlab, labelled in pt-BR', async () => {
    await setLocaleFor('pt-BR');
    renderForm();

    const providerPlaceholder = i18n.t('gitRepoForm.field.provider.placeholder');
    const trigger = screen.getByText(providerPlaceholder);
    const user = userEvent.setup();
    await user.click(trigger);

    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(2);
    expect(options.map((o) => o.querySelector('[data-value]')?.getAttribute('title'))).toEqual([
      i18n.t('git.provider.github'),
      i18n.t('git.provider.gitlab'),
    ]);

    // restore default locale for other suites
    await setLocaleFor('en');
  });
});

describe('GitRepoForm edit mode (Feature: git-repo-edit-token-rotation)', () => {
  const EDIT_TARGET = {
    repoId: 'abc12345',
    name: 'existing-repo',
    url: 'https://github.com/org/existing-repo',
    provider: 'github' as const,
    tokenConfigured: true,
    status: 'ACTIVE' as const,
    lastSyncAt: null,
    createdAt: '2026-06-01T00:00:00+00:00',
  };

  function renderEditForm(onSubmit = vi.fn().mockResolvedValue(undefined)) {
    const utils = render(
      <I18nProvider>
        <GitRepoForm visible onDismiss={vi.fn()} onSubmit={onSubmit} editTarget={EDIT_TARGET} />
      </I18nProvider>,
    );
    return { ...utils, onSubmit };
  }

  it('prefills name and url and uses edit-mode strings', async () => {
    await setLocaleFor('en');
    renderEditForm();

    expect(screen.getByDisplayValue(EDIT_TARGET.name)).toBeInTheDocument();
    expect(screen.getByDisplayValue(EDIT_TARGET.url)).toBeInTheDocument();
    expect(screen.getByText(i18n.t('gitRepoForm.editTitle'))).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: i18n.t('gitRepoForm.submitEdit') }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(i18n.t('gitRepoForm.field.token.editDescription')),
    ).toBeInTheDocument();
  });

  it('submits with a blank token (token optional in edit mode)', async () => {
    await setLocaleFor('en');
    const { onSubmit } = renderEditForm();
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: i18n.t('gitRepoForm.submitEdit') }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      name: EDIT_TARGET.name,
      url: EDIT_TARGET.url,
      provider: EDIT_TARGET.provider,
      accessToken: '',
    });
  });
});
