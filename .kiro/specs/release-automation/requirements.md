# Requirements Document — Release Automation and Version Display

## Introduction

This document specifies a lightweight release automation for the project. Today the version exists only as a hand-edited heading in `docs/changelog.md`: there is no single version source, no git tags, no GitHub Releases, and no way to tell which version a deployed frontend is running. The design deliberately preserves the human-curated changelog mandated by steering §8.4 — automation covers the mechanical parts only: version bumping, changelog promotion, tagging, publishing the GitHub Release, and displaying the version in the UI header.

## Glossary

- **VERSION file**: Plain-text file at the repository root holding the current version (e.g. `3.4`), the single source of truth.
- **Promotion**: Rewriting the `## Unreleased` changelog heading into a versioned heading `## vX.Y — Title (YYYY-MM-DD)` and inserting a fresh empty `## Unreleased` above it.
- **Release PR**: A pull request produced by the release workflow containing the VERSION bump and the changelog promotion.
- **Release Publish**: Creating the git tag `vX.Y` and a GitHub Release whose notes are the promoted changelog section.

## Requirements

### Requirement 1: Single version source injected into the build

**User Story:** As a developer, I want one canonical VERSION file consumed by the frontend build, so that the displayed version can never drift from the released version.

#### Acceptance Criteria

1. THE repository SHALL contain a root `VERSION` file holding the current version string.
2. WHEN the frontend is built, THE build SHALL inject the VERSION file content as a compile-time constant (`__APP_VERSION__`).
3. IF the VERSION file is missing at build time, THEN THE build SHALL fail rather than embed a placeholder.

### Requirement 2: Version visible in the UI header

**User Story:** As a user or operator, I want a small version indicator in the header of every page, so that I can tell at a glance which release the deployed app is running.

#### Acceptance Criteria

1. THE TopNavigation header SHALL display the version as a small utility text (`vX.Y`) on both the authenticated and unauthenticated layouts.
2. WHEN the version indicator is clicked, THE app SHALL open the changelog on GitHub in a new tab.
3. THE version string SHALL be locale-neutral (identical in every locale, like brand strings).

### Requirement 3: Release workflow promotes the changelog and opens a Release PR

**User Story:** As a maintainer, I want to trigger a release with one action choosing the bump type, so that version numbering and changelog promotion are mechanical and consistent.

#### Acceptance Criteria

1. THE repository SHALL provide a manually-triggered GitHub Actions workflow accepting a bump type (`major`, `minor`, `patch`) and a release title.
2. WHEN triggered, THE workflow SHALL compute the next version from the VERSION file (e.g. minor: `3.4` → `3.5`; patch: `3.4` → `3.4.1`; major: `3.4` → `4.0`).
3. THE workflow SHALL update the VERSION file, promote the `## Unreleased` section to `## vX.Y — Title (date)`, insert a fresh `## Unreleased` heading, and open a Release PR with these changes.
4. IF the `## Unreleased` section is empty, THEN THE workflow SHALL fail with a clear message instead of producing an empty release.

### Requirement 4: Tag and GitHub Release on merge

**User Story:** As a maintainer, I want the git tag and GitHub Release created automatically when the Release PR merges, so that releases are traceable artifacts and not just markdown headings.

#### Acceptance Criteria

1. WHEN a change to the VERSION file lands on `main`, THE automation SHALL create an annotated git tag `vX.Y` at that commit.
2. THE automation SHALL create a GitHub Release for the tag whose notes are the promoted changelog section for that version.
3. IF the tag already exists, THEN THE automation SHALL skip creation without failing (idempotent re-runs).

### Requirement 5: Conventional PR titles

**User Story:** As a maintainer, I want PR titles validated against conventional-commit prefixes, so that future automation can infer bump types and the history stays consistent.

#### Acceptance Criteria

1. THE repository SHALL validate PR titles against the conventional-commit pattern (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `ci:`, `build:`, `perf:`) via a GitHub Actions check.
2. THE check SHALL be non-blocking for existing PRs opened before its introduction (it evaluates on PR events only).
