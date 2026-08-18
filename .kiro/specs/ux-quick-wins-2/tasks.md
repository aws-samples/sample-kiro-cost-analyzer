# Implementation Plan: UX Quick Wins 2 (F2, F8, F10)

## Overview

Frontend-only batch: Productivity ranking table (#17), login hero cap (#23), settings gear relabel (#25 — relabel approved over hiding, preserving Req 3.1).

## Tasks

- [x] 1. #17 — Productivity ranking table
  - [x] 1.1 Replace the empty state in `frontend/src/pages/ProductivityPage.tsx` with a top-10 ranking table (sorted by totalCredits desc, rows linking to the user's productivity tab); add `productivity.ranking.*` i18n keys
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [ ]* 1.2 Test: Property 1 (ranking order and size)
    - **Validates: Requirements 1.1**

- [x] 2. #23 — Login hero cap
  - [x] 2.1 Cap hero at 180px, drop `scale(1.5)` in `frontend/src/pages/LoginPage.tsx`
    - _Requirements: 2.1, 2.2_

- [x] 3. #25 — Gear relabel
  - [x] 3.1 Change `userSettings.openAriaLabel` to "Language & theme" / "Idioma e tema"; close #25 documenting the Req 3.1 conflict
    - _Requirements: 3.1, 3.2_

- [x] 4. Checkpoint — build, tests, deploy-frontend, user validation

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Frontend-only — `make deploy-frontend` suffices
