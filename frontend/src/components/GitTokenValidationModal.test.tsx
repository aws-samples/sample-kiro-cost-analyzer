import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import GitTokenValidationModal from './GitTokenValidationModal';
import type { GitTokenValidation } from '../types';

// The modal's whole job is turning slugs into actionable prose, so the test
// resolves keys to the keys themselves — asserting WHICH string was chosen
// rather than its English wording, which the catalog owns.
vi.mock('../i18n/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

function build(overrides: Partial<GitTokenValidation> = {}): GitTokenValidation {
  return {
    provider: 'github',
    overall: 'partial',
    tokenMissing: false,
    checks: [
      { id: 'repo_access', status: 'ok', httpStatus: 200 },
      { id: 'commits', status: 'forbidden', httpStatus: 403 },
      { id: 'pull_requests', status: 'forbidden', httpStatus: 403 },
    ],
    requiredPermissions: ['contents:read', 'pull_requests:read'],
    ...overrides,
  };
}

describe('GitTokenValidationModal', () => {
  it('renders nothing when there is no result', () => {
    const { container } = render(
      <GitTokenValidationModal result={null} onDismiss={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('lists every check with its status and observed HTTP code', () => {
    render(<GitTokenValidationModal result={build()} onDismiss={() => {}} />);

    expect(screen.getByText(/gitTokenValidation\.check\.repo_access/)).toBeTruthy();
    expect(screen.getByText(/gitTokenValidation\.check\.commits/)).toBeTruthy();
    expect(screen.getByText(/gitTokenValidation\.check\.pull_requests/)).toBeTruthy();
    expect(screen.getAllByText(/HTTP 403/).length).toBe(2);
  });

  it('surfaces the partial verdict for a token that authenticates but lacks scope', () => {
    render(<GitTokenValidationModal result={build()} onDismiss={() => {}} />);
    expect(screen.getByText('gitTokenValidation.summary.partial')).toBeTruthy();
  });

  it('surfaces the failed verdict when nothing passed', () => {
    const result = build({
      overall: 'failed',
      checks: [
        { id: 'repo_access', status: 'unauthorized', httpStatus: 401 },
        { id: 'commits', status: 'unauthorized', httpStatus: 401 },
        { id: 'pull_requests', status: 'unauthorized', httpStatus: 401 },
      ],
      requiredPermissions: ['metadata:read', 'contents:read', 'pull_requests:read'],
    });
    render(<GitTokenValidationModal result={result} onDismiss={() => {}} />);

    expect(screen.getByText('gitTokenValidation.summary.failed')).toBeTruthy();
  });

  it('distinguishes a missing token from a rejected one', () => {
    const result = build({
      overall: 'failed',
      tokenMissing: true,
      checks: [
        { id: 'repo_access', status: 'unauthorized', httpStatus: null },
        { id: 'commits', status: 'unauthorized', httpStatus: null },
        { id: 'pull_requests', status: 'unauthorized', httpStatus: null },
      ],
      requiredPermissions: ['metadata:read', 'contents:read', 'pull_requests:read'],
    });
    render(<GitTokenValidationModal result={result} onDismiss={() => {}} />);

    expect(screen.getByText('gitTokenValidation.summary.tokenMissing')).toBeTruthy();
    expect(screen.queryByText('gitTokenValidation.summary.failed')).toBeNull();
    expect(screen.queryByText(/HTTP/)).toBeNull();
  });

  it('renders the same remediation shape for GitHub, with name and level split', () => {
    render(<GitTokenValidationModal result={build()} onDismiss={() => {}} />);

    expect(screen.getByText('gitTokenValidation.remediation.intro.github')).toBeTruthy();
    // "contents:read" must become "contents_read" — i18next would otherwise
    // read the colon as a namespace separator.
    expect(screen.getByText('gitTokenValidation.permission.contents_read.name')).toBeTruthy();
    expect(screen.getByText('gitTokenValidation.permission.pull_requests_read.name')).toBeTruthy();
    // The level is emphasised separately from the identifier.
    expect(
      screen.getAllByText('gitTokenValidation.permission.contents_read.level').length,
    ).toBeGreaterThan(0);
    // A user holding a classic PAT cannot act on fine-grained instructions,
    // so the alternative is always present.
    expect(screen.getByText('gitTokenValidation.remediation.note.github.term')).toBeTruthy();
  });

  it('renders that identical shape for GitLab too, not a wall of prose', () => {
    const result = build({
      provider: 'gitlab',
      overall: 'failed',
      checks: [
        { id: 'repo_access', status: 'forbidden', httpStatus: 403 },
        { id: 'commits', status: 'forbidden', httpStatus: 403 },
        { id: 'pull_requests', status: 'ok', httpStatus: 200 },
      ],
      requiredPermissions: ['read_api', 'read_repository'],
    });
    render(<GitTokenValidationModal result={result} onDismiss={() => {}} />);

    expect(screen.getByText('gitTokenValidation.remediation.intro.gitlab')).toBeTruthy();
    // The permission list is present for GitLab as well — the earlier
    // revision collapsed GitLab into a single paragraph with no list,
    // which is what made the two providers look like different features.
    expect(screen.getByText('gitTokenValidation.permission.read_api.name')).toBeTruthy();
    expect(screen.getByText('gitTokenValidation.permission.read_repository.name')).toBeTruthy();
    expect(screen.getByText('gitTokenValidation.remediation.note.gitlab.term')).toBeTruthy();
    expect(screen.queryByText('gitTokenValidation.remediation.intro.github')).toBeNull();
  });

  it('renders GitHub permissions as list rows, not prose', () => {
    render(<GitTokenValidationModal result={build()} onDismiss={() => {}} />);

    // Cloudscape renders Modal into a portal, so query by role rather than
    // through the render container.
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('renders GitLab permissions as list rows too, with the same structure', () => {
    render(
      <GitTokenValidationModal
        result={build({ provider: 'gitlab', requiredPermissions: ['read_api'] })}
        onDismiss={() => {}}
      />,
    );

    // The earlier revision collapsed GitLab into a single paragraph with no
    // list, which is what made the two providers look like different
    // features. One row per permission, same as GitHub.
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it('omits the remediation block entirely when nothing needs granting', () => {
    const result = build({
      overall: 'ok',
      checks: [
        { id: 'repo_access', status: 'ok', httpStatus: 200 },
        { id: 'commits', status: 'ok', httpStatus: 200 },
        { id: 'pull_requests', status: 'ok', httpStatus: 200 },
      ],
      requiredPermissions: [],
    });
    render(<GitTokenValidationModal result={result} onDismiss={() => {}} />);

    expect(screen.queryByText('gitTokenValidation.remediation.title')).toBeNull();
  });
});
