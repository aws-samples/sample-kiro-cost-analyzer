# Implementation Plan: Token Configured Indicator on Repos Table

## Overview

Frontend-only (issue #14): one `StatusIndicator` column on the repos table from the existing `tokenConfigured` field, plus 3 i18n keys.

## Tasks

- [x] 1. Add the token status column
  - [x] 1.1 Add the `token` column with `StatusIndicator` to the repos table in `frontend/src/pages/GitSettingsPage.tsx`
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 1.2 Add the 3 i18n keys to `en.json` and `pt-BR.json` (alphabetical, parity)
    - _Requirements: 2.1_
  - [x]* 1.3 Test: Property 1 (Indicator fidelity) in `GitSettingsPage.test.tsx`
    - **Validates: Requirements 1.1, 1.2, 1.3**

- [x] 2. Checkpoint — build, tests, deploy, user validation

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- No backend changes — `tokenConfigured` already ships in the list API
