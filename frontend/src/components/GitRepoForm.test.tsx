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
