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

  it('shows both GitHub token-type remediations, with colons slugified into keys', () => {
    render(<GitTokenValidationModal result={build()} onDismiss={() => {}} />);

    expect(screen.getByText('gitTokenValidation.remediation.github.fineGrained')).toBeTruthy();
    // A user holding a classic PAT cannot act on fine-grained instructions,
    // so both paths must always be present.
    expect(screen.getByText('gitTokenValidation.remediation.github.classic')).toBeTruthy();
    // "contents:read" must become "contents_read" — i18next would otherwise
    // read the colon as a namespace separator.
    expect(screen.getByText('gitTokenValidation.permission.contents_read')).toBeTruthy();
    expect(screen.getByText('gitTokenValidation.permission.pull_requests_read')).toBeTruthy();
  });

  it('shows the GitLab scope remediation instead for a GitLab repository', () => {
    const result = build({
      provider: 'gitlab',
      overall: 'failed',
      checks: [
        { id: 'repo_access', status: 'forbidden', httpStatus: 403 },
        { id: 'commits', status: 'forbidden', httpStatus: 403 },
        { id: 'pull_requests', status: 'forbidden', httpStatus: 403 },
      ],
      requiredPermissions: ['read_api'],
    });
    render(<GitTokenValidationModal result={result} onDismiss={() => {}} />);

    expect(screen.getByText('gitTokenValidation.remediation.gitlab')).toBeTruthy();
    expect(screen.queryByText('gitTokenValidation.remediation.github.fineGrained')).toBeNull();
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
