# Implementation Plan: Dashboard Active User Count

## Overview

This plan corrects the `/api/usage` Summary_Block so that `totalUsers` and the credit/overage totals reflect the entire filtered population of active users, not the first 50-row page. The aggregation already happens in `Analytics_Repository.scan_user_stats`; the change surfaces the aggregated summary and consumes it in the handler. The paginated `users` list, the response schema, and the frontend are unchanged. Work is incremental: repository first, then handler, then verification. Tests marked with `*` are optional for a fast MVP.

## Tasks

- [x] 1. Compute and return the aggregated summary in the repository
  - [x] 1.1 Add summary computation to `scan_user_stats`
    - In `backend/repository/analytics_repository.py`:
      - After the optional `subscription_tier` filter is applied and before the page slice, compute a `summary` dict over the full `users` list: `totalUsers = len(users)`, `totalCredits = round(sum(u["totalCredits"] for u in users), 2)`, `totalOverageCredits = round(sum(u["overageCredits"] for u in users), 2)`, and `averageCreditsPerUser = round(totalCredits / totalUsers, 2)` guarded to 0 when `totalUsers == 0`.
      - Add the `summary` key to the returned dict alongside `users`, `nextToken`, and `scannedCount`.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 5.1, 5.2_

  - [x]* 1.2 Write unit tests for the repository summary
    - In `tests/`:
      - Seed the Analytics_Table (moto) with more than 50 distinct users, each with one or more `STATS#DAILY#` items.
      - Assert `result["summary"]["totalUsers"]` equals the seeded distinct-user count and `len(result["users"]) == 50` with a non-null `nextToken`.
      - Assert credit and overage sums equal the full seeded totals, not the page totals.
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 4.1, 4.2_

- [x] 2. Consume the repository summary in the handler
  - [x] 2.1 Use `result["summary"]` in `handle_usage`
    - In `backend/handlers/usage_handler.py`:
      - Forward `start_date=query_params.get("startDate")` and `end_date=query_params.get("endDate")` to `scan_user_stats` so the summary respects the date window.
      - Set the response summary from `result.get("summary")`, falling back to `_compute_summary(users)` when the key is absent (defensive back-compat for test doubles).
      - Leave per-page enrichment (names, tombstone, activity summary) and the `nextToken`/`period` blocks unchanged.
    - _Requirements: 1.1, 2.5, 3.1, 3.2, 3.3, 4.3, 4.4, 4.5_

  - [x]* 2.2 Write handler tests for count accuracy and invariance
    - In `tests/`:
      - Assert that with 60 seeded active users, `summary.totalUsers == 60` while `len(response["users"]) == 50`.
      - Assert the Summary_Block is identical when fetching page 1 and the page reached via `nextToken` (pagination invariance).
      - Assert the single-user (`userId`) path is unchanged.
    - _Requirements: 1.2, 2.5, 4.5_

- [x] 3. Filter-scoped summary correctness
  - [x] 3.1 Verify tier and date-range scoping
    - Confirm (and adjust if needed) that the summary is computed after the `subscription_tier` filter and within the date-range `FilterExpression`, so `summary.totalUsers` counts only the filtered population.
    - _Requirements: 3.1, 3.2, 3.3_

  - [x]* 3.2 Write property-based tests (Hypothesis, 100+ iterations)
    - Implement the correctness properties from the design:
      - **Property 1 — Count totality** (Validates 1.1, 1.2, 1.3, 1.4)
      - **Property 2 — Summary pagination invariance** (Validates 2.5)
      - **Property 3 — Total conservation across all pages** (Validates 2.1, 2.2, 3.3)
      - **Property 4 — Average coherence** (Validates 2.3, 2.4)
      - **Property 5 — Tier filter soundness** (Validates 3.1, 3.3)
    - _Requirements: 1.1, 2.1, 2.3, 2.4, 2.5, 3.1, 3.3_

- [x] 4. Frontend verification (no code change expected)
  - [x] 4.1 Confirm the card reflects the backend value
    - Confirm `SummaryCards.tsx` renders `summary.totalUsers` with no client-side cap and that `DashboardPage.fetchUsers` needs no change.
    - _Requirements: 1.1, 4.3_

  - [x]* 4.2 Add/adjust a frontend test
    - In `frontend/src/`:
      - Add a test asserting the card renders a backend-provided total greater than 50 unchanged.
    - _Requirements: 1.2_

- [x] 5. Verification checkpoint
  - [x] 5.1 Run backend and frontend builds and tests
    - Run the Python test suite (`pytest`) and the frontend build/tests (`npm run build`, `npm run test`). Fix any failures before completion.
    - _Requirements: all_

  - [x] 5.2 Update documentation and changelog
    - Add an entry under `Unreleased` in `docs/changelog.md` describing the corrected "Total Users"/summary metric.
    - Update any README/dashboard doc that describes the summary if it implies the count is capped.
    - _Requirements: all_

## Notes

- The "total licenses" metric (e.g. 127) and never-active seat detection are **out of scope** (see `requirements.md` Out of Scope). They require ingesting the Kiro subscription roster, for which the application has no data source today.
