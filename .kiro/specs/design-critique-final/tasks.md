# Implementation Plan: Design Critique Final (F1, F4, F9)

## Overview

Final critique batch: sidebar section rename (#16), inner-tabs container variant (#19), Churn Risk context Popover with raw counts (#24). Closing these closes the parent tracking issue #15.

## Tasks

- [x] 1. #16 — rename `nav.section.users` to "Analytics"/"Análises" (en + pt-BR)
  - _Requirements: 1.1, 1.2_
- [x] 2. #19 — `variant="container"` on the inner Settings tabs (`SettingsPage.tsx`)
  - _Requirements: 2.1, 2.2_
- [x] 3. #24 — Churn Risk context
  - [x] 3.1 Add `idleCount`, `dormantCount`, `totalUsers` to `derivedMetrics` in `backend/handlers/funnel_calculator.py`; extend the frontend type
    - _Requirements: 3.1_
  - [x] 3.2 Popover on the Churn Risk label in `EngagementFunnelWidget.tsx` (formula + counts + threshold); i18n keys en + pt-BR
    - _Requirements: 3.2, 3.3_
  - [x]* 3.3 Test: Property 1 (count consistency) in `tests/test_funnel_calculator.py`
    - **Validates: Requirements 3.1**
- [x] 4. Checkpoint — pytest + build/tests + full deploy (backend changed) + user validation

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
