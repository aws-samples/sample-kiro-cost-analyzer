# Implementation Plan: Release Automation and Version Display

## Overview

VERSION file as single source, injected into the frontend header; workflow_dispatch release flow (bump + changelog promotion + Release PR); tag + GitHub Release on merge; PR-title lint; retroactive v3.4 tag.

## Tasks

- [ ] 1. VERSION file + frontend injection
  - [ ] 1.1 Create root `VERSION` (3.4); inject `__APP_VERSION__` in `frontend/vite.config.ts` (define, fail-loud read) including the vitest config block; declare the global type
    - _Requirements: 1.1, 1.2, 1.3_
  - [ ] 1.2 Add the version utility to both `TopNavigation` instances in `App.tsx` (links to the changelog on GitHub); add `nav.versionAriaLabel` key (en + pt-BR)
    - _Requirements: 2.1, 2.2, 2.3_

- [ ] 2. Promotion script
  - [ ] 2.1 Create `scripts/promote_changelog.py` (bump/promote/extract modes, dry-run, fail on empty Unreleased)
    - _Requirements: 3.2, 3.3, 3.4_
  - [ ]* 2.2 Write pytest for the script
    - **Property 1: Bump arithmetic** / **Property 2: Changelog conservation** / **Property 3: Empty-release refusal**
    - Create `tests/test_promote_changelog.py`
    - **Validates: Requirements 3.2, 3.3, 3.4**

- [ ] 3. Workflows
  - [ ] 3.1 `.github/workflows/release.yml` — workflow_dispatch (bump, title) → script → Release PR
    - _Requirements: 3.1, 3.3_
  - [ ] 3.2 `.github/workflows/publish-release.yml` — push to main touching VERSION → idempotent tag + GitHub Release with the version's changelog section
    - _Requirements: 4.1, 4.2, 4.3_
  - [ ] 3.3 `.github/workflows/pr-title.yml` — semantic PR title check
    - _Requirements: 5.1, 5.2_

- [ ] 4. Checkpoint — verify, document, release
  - Frontend build + tests pass; script pytest passes
  - Update steering §8.4 with the new release flow; changelog entry
  - Deploy frontend and ask the user to validate the header badge
  - After merge: create the retroactive `v3.4` tag + Release
  - _Requirements: all_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- The changelog content itself stays human-written (steering §8.4) — automation is mechanical only
