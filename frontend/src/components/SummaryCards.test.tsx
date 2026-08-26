/**
 * Unit tests for `SummaryCards.tsx` (dashboard-active-user-count spec).
 *
 * The card renders whatever `summary.totalUsers` the backend provides, with
 * no client-side cap. This guards against a regression where the dashboard
 * would truncate the headline count to the 50-row page size.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SummaryCards from './SummaryCards';
import { I18nProvider } from '../i18n/I18nProvider';
import type { UsageSummary } from '../types';

function renderCards(summary: UsageSummary | undefined, loading = false) {
  return render(
    <I18nProvider>
      <SummaryCards summary={summary} loading={loading} />
    </I18nProvider>,
  );
}

describe('SummaryCards', () => {
  it('renders a total user count above 50 unchanged (no client-side cap)', () => {
    const summary: UsageSummary = {
      totalUsers: 127,
      totalCredits: 1000,
      totalOverageCredits: 0,
      averageCreditsPerUser: 7.87,
    };
    renderCards(summary);
    expect(screen.getByText('127')).toBeInTheDocument();
  });

  it('renders a dash placeholder when the summary is undefined', () => {
    renderCards(undefined);
    // The totalUsers slot shows an em-dash when there is no summary.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});
