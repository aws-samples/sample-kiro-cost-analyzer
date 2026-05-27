# Implementation Plan: Dormant User Detection

## Overview

This plan implements activity frequency awareness in the Kiro Cost Analyzer's engagement segmentation system. It adds a pre-computed Activity_Summary DynamoDB item per user (upserted during ETL), a "dormant" classification for long-idle users, frequency badges in the Users table, updated segmentation/funnel widgets, a configurable dormant threshold, and a Settings UI for threshold management. The implementation is incremental: backend data layer first, then classification logic, then API integration, then frontend.

## Tasks

- [x] 1. Extend segmentation engine and threshold validation
  - [x] 1.1 Add `dormant_days_threshold` to `Thresholds` dataclass and extend `EngagementCategory` type
    - In `backend/handlers/segmentation_engine.py`:
      - Add `dormant_days_threshold: int = 30` field to the `Thresholds` dataclass
      - Update `EngagementCategory` type to `Literal["power", "active", "light", "idle", "dormant"]`
    - _Requirements: 3.1, 3.5_

  - [x] 1.2 Extend `validate_thresholds` to accept optional `dormantDaysThreshold`
    - In `backend/handlers/segmentation_engine.py`:
      - Accept optional `dormantDaysThreshold` field in the config dict
      - Validate it is a positive integer when present
      - Return `(False, error_message)` for zero, negative, float, string, or boolean values
      - Continue to pass validation when the field is absent
    - _Requirements: 4.3_

  - [x] 1.3 Extend `parse_thresholds` to extract `dormantDaysThreshold`
    - In `backend/handlers/segmentation_engine.py`:
      - Extract `dormantDaysThreshold` from parsed JSON when present
      - Populate the new `Thresholds.dormant_days_threshold` field
      - Fall back to default (30) when field is absent or invalid
    - _Requirements: 4.1, 4.2_

  - [x] 1.4 Implement `reclassify_dormant` pure function
    - In `backend/handlers/segmentation_engine.py`:
      - Add `reclassify_dormant(classifications, frequency_data, dormant_days_threshold)` function
      - Reclassify "idle" users to "dormant" when `daysSinceLastActive` is not None and >= threshold
      - Leave all other classifications unchanged (power, active, light, idle without data)
    - _Requirements: 3.2, 3.3, 3.4, 11.1, 11.3_

  - [ ]* 1.5 Write property test for dormant reclassification correctness
    - **Property 3: Dormant reclassification correctness**
    - **Validates: Requirements 3.2, 3.3, 3.4, 11.1, 11.3**

  - [ ]* 1.6 Write property test for threshold validation with dormantDaysThreshold
    - **Property 4: Threshold validation accepts valid dormantDaysThreshold**
    - **Validates: Requirements 4.3**

  - [ ]* 1.7 Write unit tests for extended segmentation engine
    - Test `reclassify_dormant` with specific examples: idle→dormant, idle→idle (below threshold), idle→idle (no data), power/active/light unchanged
    - Test `validate_thresholds` with and without `dormantDaysThreshold`
    - Test `parse_thresholds` with and without `dormantDaysThreshold`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.3_

- [x] 2. Implement Activity Summary in ETL layer
  - [x] 2.1 Add `upsert_activity_summary` method to `AnalyticsWriter`
    - In `layers/shared/shared/analytics_writer.py`:
      - Add `upsert_activity_summary(self, user_id: str, date: str) -> None`
      - Use `SET firstActiveDate = if_not_exists(firstActiveDate, :date)` for first-write-wins
      - Use `ADD activeDays :one` for atomic counter
      - Use a separate conditional update for `lastActiveDate` (only if newer)
      - Catch `ConditionalCheckFailedException` silently for out-of-order writes
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 2.2 Integrate `upsert_activity_summary` into writer_handler
    - In `etl/writer_handler.py`:
      - Call `writer.upsert_activity_summary(user_id, date)` in `_write_csv_record()` after writing daily stats
      - Call `writer.upsert_activity_summary(user_id, date)` in `_write_prompt_record()` after writing prompt data
      - Increment `items` counter accordingly
    - _Requirements: 1.1, 14.1_

  - [ ]* 2.3 Write property test for Activity_Summary date invariants
    - **Property 1: Activity_Summary date invariants**
    - **Validates: Requirements 1.2, 1.3, 1.4**

  - [ ]* 2.4 Write unit tests for `upsert_activity_summary`
    - Test with moto-mocked DynamoDB: first write creates item, subsequent writes update correctly
    - Test out-of-order dates: firstActiveDate stays as minimum, lastActiveDate stays as maximum
    - Test activeDays increments on each call
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement Activity Summary read access and engagement handler integration
  - [x] 4.1 Add `get_activity_summary` and `batch_get_activity_summaries` to `AnalyticsRepository`
    - In `backend/repository/analytics_repository.py`:
      - Add `get_activity_summary(self, user_id: str) -> dict | None`
      - Add `batch_get_activity_summaries(self, user_ids: list[str]) -> dict[str, dict]`
      - Process in chunks of 100 (DynamoDB BatchGetItem limit)
      - Handle `UnprocessedKeys` with retry loop
      - Return `None` / absent key for users without Activity_Summary
    - _Requirements: 2.1, 2.2, 2.3, 14.2, 14.3_

  - [ ]* 4.2 Write property test for batch retrieval completeness
    - **Property 8: Batch retrieval completeness**
    - **Validates: Requirements 2.2, 2.3**

  - [x] 4.3 Update `engagement_handler.py` to integrate Activity_Summary and dormant reclassification
    - In `backend/handlers/engagement_handler.py`:
      - After classifying users, extract user IDs and call `repo.batch_get_activity_summaries()`
      - Compute `daysSinceLastActive` for each user from `lastActiveDate` and current date
      - Call `reclassify_dormant()` with the frequency data and `thresholds.dormant_days_threshold`
      - Update `category_counts` dict to include "dormant" key
      - Update segmentation iteration to include "dormant" category
      - Import `reclassify_dormant` from segmentation_engine
    - _Requirements: 2.4, 3.2, 4.1, 4.2, 11.1, 11.3, 14.3_

  - [ ]* 4.4 Write property test for daysSinceLastActive computation
    - **Property 2: daysSinceLastActive computation**
    - **Validates: Requirements 2.4**

  - [ ]* 4.5 Write unit tests for Activity_Summary repository methods
    - Test `get_activity_summary` with moto: existing item returns dict, missing item returns None
    - Test `batch_get_activity_summaries` with moto: multiple users, partial results, empty input
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 5. Update funnel calculator and derived metrics
  - [x] 5.1 Update `compute_derived_metrics` to include `dormantRate` and `churnRiskRate`
    - In `backend/handlers/funnel_calculator.py`:
      - Add `dormantRate` computation: `round((dormant_count / total_users) * 100, 1)`
      - Add `churnRiskRate` computation: `round(((idle_count + dormant_count) / total_users) * 100, 1)`
      - Update `idle_count` calculation to exclude dormant users (they are separate)
      - Handle `total_users == 0` case (return 0.0 for both)
    - _Requirements: 5.3, 6.1_

  - [ ]* 5.2 Write property test for derived metrics computation
    - **Property 5: Derived metrics computation**
    - **Validates: Requirements 5.3, 6.1**

  - [ ]* 5.3 Write unit tests for updated funnel calculator
    - Test `compute_derived_metrics` with 5-category classifications
    - Test edge cases: all dormant, no dormant, zero users
    - _Requirements: 5.3, 6.1_

- [x] 6. Update usage handler to include frequency data
  - [x] 6.1 Extend `usage_handler.py` to include `lastActiveDate` and `daysSinceLastActive`
    - In `backend/handlers/usage_handler.py`:
      - After building user list, batch-fetch Activity_Summary items for all user IDs
      - Compute `daysSinceLastActive` from `lastActiveDate` and current date
      - Add `lastActiveDate` and `daysSinceLastActive` fields to each user object in `_format_user()`
      - Return `null` for users without Activity_Summary
    - _Requirements: 7.4, 2.4_

  - [ ]* 6.2 Write unit tests for usage handler frequency data
    - Test user objects include `lastActiveDate` and `daysSinceLastActive`
    - Test users without Activity_Summary get `null` values
    - _Requirements: 7.4_

- [x] 7. Update engagement threshold PUT handler
  - [x] 7.1 Extend `handle_put_thresholds` to persist `dormantDaysThreshold`
    - In `backend/handlers/engagement_handler.py`:
      - Ensure `dormantDaysThreshold` is included in the JSON written to SSM when present in the request body
      - The existing `validate_thresholds` (updated in task 1.2) handles validation
    - _Requirements: 4.4_

  - [ ]* 7.2 Write unit tests for threshold PUT with dormantDaysThreshold
    - Test PUT with `dormantDaysThreshold` persists to SSM
    - Test PUT without `dormantDaysThreshold` still works (backward compatible)
    - _Requirements: 4.4, 4.2_

- [x] 8. Checkpoint — Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Frontend: Update TypeScript interfaces and i18n keys
  - [x] 9.1 Extend TypeScript interfaces in `frontend/src/types/index.ts`
    - Add `lastActiveDate?: string | null` and `daysSinceLastActive?: number | null` to `UserUsage`
    - Add `dormantRate: number` and `churnRiskRate: number` to `DerivedEngagementMetrics`
    - _Requirements: 5.3, 6.1, 7.4_

  - [x] 9.2 Add i18n keys to `en.json` and `pt-BR.json`
    - In `frontend/src/locales/en.json`: add keys for "Active", "Recent", "Inactive", "Dormant", "Last Active", "Days Ago", "Churn Risk", "Dormant Rate", frequency filter labels, engagement settings help text
    - In `frontend/src/locales/pt-BR.json`: add corresponding Portuguese translations ("Ativo", "Recente", "Inativo", "Adormecido", "Última Atividade", "Dias Atrás", "Risco de Churn", "Taxa de Adormecidos")
    - Ensure keys are alphabetically sorted in both files
    - _Requirements: 10.1, 10.2, 10.3_

- [x] 10. Frontend: Update EngagementSegmentationWidget
  - [x] 10.1 Add "dormant" category to `EngagementSegmentationWidget`
    - In `frontend/src/components/EngagementSegmentationWidget.tsx`:
      - Add `dormant: '#8b0000'` to `CATEGORY_COLORS`
      - Add "dormant" to category iteration
      - Display `dormantRate` metric in the ColumnLayout (expand to 4 columns)
      - Use `t()` for all new labels
    - _Requirements: 5.1, 5.2, 5.4_

  - [ ]* 10.2 Write unit tests for EngagementSegmentationWidget
    - Verify 5 segments render including dormant
    - Verify dormant color is `#8b0000`
    - Verify `dormantRate` metric displays
    - _Requirements: 5.1, 5.2, 5.4_

- [x] 11. Frontend: Update EngagementFunnelWidget
  - [x] 11.1 Add `churnRiskRate` display to `EngagementFunnelWidget`
    - In `frontend/src/components/EngagementFunnelWidget.tsx`:
      - Display `churnRiskRate` as a supplementary metric below the funnel chart
      - Apply warning color (`color-text-status-error`) when `churnRiskRate > 50%`
      - Use `t()` for the "Churn Risk" label
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ]* 11.2 Write unit tests for EngagementFunnelWidget churn risk
    - Verify `churnRiskRate` displays
    - Verify warning color applied when > 50%
    - Verify normal color when <= 50%
    - _Requirements: 6.2, 6.3_

- [x] 12. Frontend: Update UsageTable with frequency columns, badge, and filter
  - [x] 12.1 Add "Last Active" and "Days Ago" columns to `UsageTable`
    - In `frontend/src/components/UsageTable.tsx`:
      - Add "Last Active" column showing `lastActiveDate` formatted via `formatDate()`
      - Add "Days Ago" column showing `daysSinceLastActive` as a number
      - Display "—" for users with `null` values
      - Use `t()` for column headers
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 12.2 Add frequency status badge component
    - In `frontend/src/components/UsageTable.tsx` (or a new `FrequencyBadge` component):
      - Implement badge logic: 0–3 days → Active (green), 4–14 → Recent (amber), 15–29 → Inactive (red), 30+ → Dormant (dark)
      - Display no badge for users with `null` daysSinceLastActive
      - Use `t()` for badge labels
    - _Requirements: 8.1, 8.2_

  - [x] 12.3 Add client-side frequency filter to `UsageTable`
    - In `frontend/src/components/UsageTable.tsx`:
      - Add filter control above the table with options: "All", "Active", "Recent", "Inactive", "Dormant"
      - Filter users client-side based on their computed frequency status
      - Default selection is "All" (no filtering)
      - Use `t()` for filter labels
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 12.4 Write property test for frequency badge mapping
    - **Property 6: Frequency badge mapping**
    - **Validates: Requirements 8.1**

  - [ ]* 12.5 Write property test for frequency filter correctness
    - **Property 7: Frequency filter correctness**
    - **Validates: Requirements 9.2**

  - [ ]* 12.6 Write unit tests for UsageTable frequency features
    - Verify new columns render with correct data
    - Verify "—" for missing data
    - Verify badge colors match thresholds
    - Verify filter functionality
    - _Requirements: 7.1, 7.2, 7.3, 8.1, 9.2_

- [x] 13. Frontend: Add Engagement thresholds configuration tab in Settings
  - [x] 13.1 Implement Engagement tab in SettingsPage
    - In `frontend/src/pages/SettingsPage.tsx` (or a new `EngagementSettingsTab` component):
      - Add "Engagement" tab displaying current thresholds: power messages, power days active, active messages, active days active, dormant days threshold
      - Add editable form fields with validation (positive integers, power > active)
      - Add help text section explaining classification logic (volume-based + frequency-based)
      - On save, call PUT `/api/config/engagement-thresholds`
      - Display inline error messages on validation failure
      - Use `t()` for all labels and help text
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

  - [ ]* 13.2 Write unit tests for Engagement settings tab
    - Verify form renders with current values
    - Verify validation errors display
    - Verify save calls PUT endpoint
    - _Requirements: 13.3, 13.4, 13.5_

- [x] 14. Checkpoint — Ensure all frontend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Integration verification and backward compatibility
  - [x] 15.1 Write integration test for full engagement endpoint flow
    - In `tests/`:
      - Test engagement endpoint with Activity_Summary items present → dormant users classified correctly
      - Test engagement endpoint with NO Activity_Summary items → zero dormant, all idle remain idle (backward compatibility)
      - Test engagement endpoint with partial Activity_Summary → only users with data get reclassified
      - Test SSM threshold read/write with `dormantDaysThreshold`
    - _Requirements: 11.1, 11.2, 11.3_

  - [x] 15.2 Run build-time locale check
    - Run `scripts/check-locales.ts` to verify key parity between `en.json` and `pt-BR.json`
    - Ensure no empty values and alphabetical sorting
    - _Requirements: 10.3_

- [x] 16. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties defined in the design document
- Unit tests validate specific examples and edge cases
- The backend uses Python (pytest + moto + hypothesis); the frontend uses TypeScript (vitest + testing-library + fast-check)
- Backward compatibility is verified in task 15.1: the system works correctly when Activity_Summary items are absent

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "9.1", "9.2"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["1.5", "1.6", "1.7", "2.2", "5.1"] },
    { "id": 3, "tasks": ["2.3", "2.4", "4.1", "5.2", "5.3"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.5", "6.1"] },
    { "id": 5, "tasks": ["4.4", "6.2", "7.1", "10.1", "11.1"] },
    { "id": 6, "tasks": ["7.2", "10.2", "11.2", "12.1", "12.2"] },
    { "id": 7, "tasks": ["12.3", "12.4", "12.5", "13.1"] },
    { "id": 8, "tasks": ["12.6", "13.2", "15.1", "15.2"] }
  ]
}
```
