# Implementation Plan: User Engagement Segmentation

## Overview

This plan implements the engagement segmentation feature incrementally: starting with the pure backend logic (segmentation engine + funnel calculator), then the API handler and routing, followed by the frontend components (pie chart widget, D3 funnel chart, derived metrics), and finally internationalization and integration wiring.

## Tasks

- [x] 1. Implement the segmentation engine (pure logic)
  - [x] 1.1 Create `backend/handlers/segmentation_engine.py` with `Thresholds` dataclass, `UserActivity` dataclass, `EngagementCategory` type alias, `classify_user()`, `classify_users()`, `validate_thresholds()`, and `parse_thresholds()` functions
    - Use `from dataclasses import dataclass` and `from typing import Literal`
    - `classify_user` implements OR-logic with priority order: power > active > light > idle
    - `validate_thresholds` checks positive integers and power > active for both dimensions
    - `parse_thresholds` parses JSON string into `Thresholds`, returns defaults on failure
    - Use try/except import pattern for compatibility with Lambda and test environments
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.2, 2.5, 2.6_

  - [x]* 1.2 Write property tests for classification completeness and mutual exclusivity
    - **Property 1: Classification completeness and mutual exclusivity**
    - Use Hypothesis with `st.integers(min_value=0, max_value=10000)` for messages/conversations
    - Generate valid `Thresholds` where power > active > 0
    - Assert exactly one category returned for every input combination
    - Assert priority order is respected (power > active > light > idle)
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**

  - [x]* 1.3 Write property test for threshold validation correctness
    - **Property 2: Threshold validation correctness**
    - Generate arbitrary dicts with positive/negative/zero/non-integer values
    - Assert `validate_thresholds` returns `(True, "")` iff all values are positive integers AND power > active
    - Assert error message is non-empty when validation fails
    - **Validates: Requirements 2.5, 2.6**

  - [x]* 1.4 Write property test for classification determinism and threshold monotonicity
    - **Property 6: Classification is deterministic and threshold-monotonic**
    - Generate two valid threshold configs T1 (lenient) and T2 (strict) where T1 <= T2
    - Assert: if user is "power" under T2, they are also "power" under T1
    - **Validates: Requirements 1.1, 2.5**

- [x] 2. Implement the funnel calculator (pure logic)
  - [x] 2.1 Create `backend/handlers/funnel_calculator.py` with `FunnelStage` dataclass, `compute_funnel()`, and `compute_derived_metrics()` functions
    - `compute_funnel` produces 5 stages: allUsers, sentMessages, hadConversations, activeUsers, powerUsers
    - Conversion rate = (current_count / previous_count) * 100; 0.0 if previous is 0; first stage is 100.0
    - `compute_derived_metrics` returns powerUserPercentage, activationRate, idleRate (1 decimal place)
    - Use try/except import pattern for `segmentation_engine` types
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 7.1, 7.2, 7.3_

  - [x]* 2.2 Write property test for funnel stage count consistency
    - **Property 3: Funnel stage counts are consistent with classifications**
    - Generate lists of `UserActivity` (0–200 items) and classify them
    - Assert 5 stages produced, counts match expected definitions
    - Assert monotonically non-increasing stage counts
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

  - [x]* 2.3 Write property test for funnel conversion rate correctness
    - **Property 4: Funnel conversion rates are mathematically correct**
    - For any computed funnel, assert each stage's conversion rate equals `(count / prev_count) * 100` or 0.0 when prev is 0
    - Assert first stage conversion rate is always 100.0
    - **Validates: Requirements 3.7, 3.8**

  - [x]* 2.4 Write property test for derived metrics consistency
    - **Property 5: Derived metrics are consistent with segmentation**
    - Generate classified user sets with total_users > 0
    - Assert powerUserPercentage + idleRate <= 100.0
    - Assert activationRate + idleRate == 100.0 (within floating point tolerance)
    - Assert each metric is rounded to 1 decimal place
    - **Validates: Requirements 4.4, 7.1, 7.2, 7.3**

- [x] 3. Checkpoint — Verify backend pure logic
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement the engagement API handler and route registration
  - [x] 4.1 Create `backend/handlers/engagement_handler.py` with `handle_engagement()`, `handle_get_thresholds()`, and `handle_put_thresholds()` functions
    - Follow the same pattern as `usage_handler.py` (dependency injection for `dynamodb_resource`, `ssm_client`)
    - `handle_engagement` reads thresholds from SSM (fallback to defaults), calls `AnalyticsRepository.scan_user_stats()`, classifies users, computes funnel and derived metrics
    - `handle_get_thresholds` reads from SSM and returns current config
    - `handle_put_thresholds` validates via `validate_thresholds()`, writes to SSM on success
    - SSM parameter path: `/kiro-cost-analyzer/engagement-thresholds`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 4.2 Register routes in `backend/handler.py`
    - Add `GET /api/usage/engagement` → `engagement_handler.handle_engagement(query_params)` (public endpoint)
    - Add `GET /api/config/engagement-thresholds` → `engagement_handler.handle_get_thresholds()` (public endpoint)
    - Add `PUT /api/config/engagement-thresholds` → `engagement_handler.handle_put_thresholds(body)` (admin-only)
    - Import `engagement_handler` in the imports section
    - _Requirements: 4.1, 2.4_

  - [ ]* 4.3 Write unit tests for `engagement_handler.py`
    - Use moto `@mock_aws` to mock DynamoDB and SSM
    - Test: correct response structure with segmentation, funnel, derivedMetrics, period
    - Test: SSM fallback to defaults when parameter missing
    - Test: threshold CRUD (get, put valid, put invalid)
    - Test: date filtering passes through to repository
    - _Requirements: 2.1, 2.2, 2.4, 2.6, 4.1, 4.5, 4.6_

- [x] 5. Checkpoint — Verify backend API integration
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Add frontend types and API client method
  - [x] 6.1 Add TypeScript interfaces to `frontend/src/types/index.ts`
    - Add `EngagementSegmentation`, `FunnelStage`, `DerivedEngagementMetrics`, and `EngagementResponse` interfaces
    - Match the backend API response schema exactly
    - _Requirements: 4.2, 4.3, 4.4_

  - [x] 6.2 Add API call in the frontend (inline `get()` usage in widgets)
    - No separate API module needed — widgets will call `get<EngagementResponse>('/api/usage/engagement', dateParams)` directly using the existing `api/client.ts`
    - _Requirements: 4.1_

- [x] 7. Implement the D3 funnel chart component
  - [x] 7.1 Install D3 dependencies: `d3-selection`, `d3-scale`, `d3-shape` (and their `@types/` packages)
    - Add to `frontend/package.json`
    - _Requirements: 6.1_

  - [x] 7.2 Create `frontend/src/components/charts/D3FunnelChart.tsx`
    - Implement `D3FunnelChartProps` interface with `data`, `width`, `height`, `colors`, `showConversionRates`
    - Use `useRef` + `useEffect` for D3 rendering into an SVG element
    - Render trapezoid shapes (wider at top, narrower at bottom) using `d3-shape` path generation
    - Display stage name + count on each segment
    - Display conversion rate labels between segments when `showConversionRates` is true
    - Handle empty data gracefully (render nothing or a placeholder)
    - Use CSS custom properties compatible with Cloudscape's visual context
    - Make responsive via ResizeObserver or container query
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ]* 7.3 Write render tests for `D3FunnelChart`
    - Test correct number of SVG path segments rendered
    - Test labels match provided data
    - Test empty data renders gracefully
    - _Requirements: 6.1_

- [x] 8. Implement the Engagement Funnel Widget
  - [x] 8.1 Create `frontend/src/components/EngagementFunnelWidget.tsx`
    - Accept `dateParams: Record<string, string>` prop
    - Fetch data from `/api/usage/engagement` using the shared `get()` client
    - Show `SkeletonLoader` during loading
    - Show Cloudscape `Alert` with retry button on error
    - Render `D3FunnelChart` with funnel stage data
    - Use `useI18n()` for all labels (stage names, conversion rate labels)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 8.2_

- [x] 9. Implement the Engagement Segmentation Widget
  - [x] 9.1 Create `frontend/src/components/EngagementSegmentationWidget.tsx`
    - Accept `dateParams: Record<string, string>` prop
    - Fetch data from `/api/usage/engagement` using the shared `get()` client
    - Show `SkeletonLoader` during loading
    - Show Cloudscape `Alert` with retry button on error
    - Render Cloudscape `PieChart` with segmentation data
    - Use 4 distinct colors for categories — NO emojis in labels
    - Display derived metrics (powerUserPercentage, activationRate, idleRate) using Cloudscape `Box` components
    - Format percentages with 1 decimal place using `formatNumber` from `useI18n()`
    - Use `useI18n()` for all labels and metric descriptions
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.1, 7.2, 7.3, 8.1, 8.4_

- [x] 10. Integrate widgets into the Dashboard page
  - [x] 10.1 Add `EngagementSegmentationWidget` and `EngagementFunnelWidget` to the overview tab in `DashboardPage.tsx`
    - Place after the existing `BreakdownCharts` component
    - Pass `dateParams` derived from the shared `dateRange` state (using the existing `getDateParams` helper)
    - Widgets re-fetch when date range changes (via prop change triggering useEffect)
    - _Requirements: 5.4, 6.4_

- [x] 11. Add internationalization keys
  - [x] 11.1 Add all `engagement.*` keys to `frontend/src/locales/en.json`
    - Add keys for: header title, category names (power, active, light, idle), funnel title, funnel stage names, conversion rate label, metric names and descriptions, loading, error, retry
    - Maintain alphabetical sort order
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 11.2 Add all `engagement.*` keys to `frontend/src/locales/pt-BR.json`
    - Translate all keys added in 11.1 to Brazilian Portuguese
    - Maintain identical key set and alphabetical sort order
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 11.3 Regenerate `frontend/src/locales/keys.d.ts` by running the locale check script
    - Run `npx ts-node scripts/check-locales.ts` (or equivalent build step)
    - Verify both catalogs pass parity check
    - _Requirements: 8.3_

- [x] 12. Checkpoint — Verify full integration
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 13. Write frontend component tests
  - [ ]* 13.1 Write tests for `EngagementSegmentationWidget`
    - Test loading skeleton display
    - Test error alert with retry button
    - Test correct pie chart data rendering
    - Test no emojis in category labels
    - Test i18n key usage (all text via `t()`)
    - _Requirements: 5.1, 5.2, 5.5, 5.6, 8.1_

  - [ ]* 13.2 Write tests for `EngagementFunnelWidget`
    - Test loading skeleton display
    - Test error alert with retry button
    - Test correct stage ordering
    - Test conversion rate labels rendered
    - Test SVG element rendered (D3 integration)
    - _Requirements: 6.1, 6.2, 6.5, 6.6, 8.2_

  - [ ]* 13.3 Write fast-check property tests for frontend percentage formatting
    - Test: segmentation percentages sum to approximately 100% for any valid response data
    - Test: percentage formatting always produces one decimal place
    - _Requirements: 7.3, 8.4_

- [x] 14. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests (Hypothesis) validate the 6 correctness properties defined in the design
- The segmentation engine and funnel calculator are pure functions with no I/O, enabling comprehensive property-based testing
- D3.js is used directly (d3-selection, d3-scale, d3-shape) — no wrapper libraries
- The Cloudscape PieChart is used for segmentation; D3 is used only for the funnel
- All UI strings go through `useI18n()` — no hardcoded text
- Category labels use distinct colors only — NO emojis
