# Implementation Plan: Summary Card Number Overflow

## Overview

Frontend-only fix for issue #20: abbreviate large KPI values with locale-aware compact notation and prevent mid-number line wraps, via a shared `formatCardValue` utility applied to all five summary-card components.

## Tasks

- [ ] 1. Create the shared formatting utility
  - [ ] 1.1 Create `frontend/src/utils/formatCardValue.ts`
    - `COMPACT_THRESHOLD = 10_000`; compact notation with `maximumFractionDigits: 1` at/above; standard notation with configurable fraction digits below
    - Pure function receiving `formatNumber` from the caller
    - _Requirements: 1.1, 1.2, 1.3, 3.1, 3.2_
  - [ ]* 1.2 Write property tests for the utility
    - **Property 1: Threshold split** — compact iff `|v| >= 10_000` (fast-check, 100+ runs)
    - **Property 2: Locale coherence** — output matches `Intl.NumberFormat` with same options for en and pt-BR
    - Example cases: `10342.18`, `9876.54`, `0`, negatives, integer counts
    - Create `frontend/src/utils/formatCardValue.test.ts`
    - **Validates: Requirements 1.1, 1.2, 1.3**

- [ ] 2. Apply the utility and nowrap to all five components
  - [ ] 2.1 Update `SummaryCards.tsx` (the reported repro)
    - Replace local `fmt` with `formatCardValue`; wrap values in nowrap span; `totalUsers` via `fractionDigits: 0`
    - _Requirements: 1.1, 1.4, 2.1, 2.2_
  - [ ] 2.2 Update `AccountSummaryCards.tsx`, `UserSummaryCards.tsx`, `GitSummaryCards.tsx`, `ProductivitySummaryCards.tsx`
    - Same pattern; counts use `fractionDigits: 0`, credit values default (2)
    - _Requirements: 1.4, 2.1, 2.2_

- [ ] 3. Checkpoint — Verify build and tests
  - Ensure the full build passes (`npm run build`)
  - Ensure tests pass (vitest)
  - Deploy to the live stack and ask the user to validate the Dashboard Users tab card
  - _Requirements: all_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- No i18n keys needed — compact suffixes come from `Intl.NumberFormat` itself
