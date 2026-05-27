# Implementation Plan: CSV Model Distribution & Schema Validation

## Overview

This plan implements CSV schema validation and model message extraction across the ETL pipeline. Tasks are ordered to build foundational modules first (schema validator, normalizer changes), then wire them through the pipeline (parser, processor, writer), and finally ensure the backend exposes the new data. Each task builds incrementally on the previous ones.

## Tasks

- [ ] 1. Create CSV Schema Validator module
  - [ ] 1.1 Create `etl/csv_schema_validator.py` with `SchemaValidationResult` dataclass and `validate_schema` function
    - Define `USER_REPORT_REQUIRED_COLUMNS`, `USER_REPORT_CRITICAL_COLUMNS`, `USER_REPORT_OPTIONAL_COLUMNS`, and `LEGACY_REQUIRED_COLUMNS` constants
    - Implement `_validate_user_report` that checks critical columns first (reject if missing), then non-critical (warn), then unexpected columns (warn)
    - Implement `_validate_legacy` that checks only `Date` and `UserId` presence
    - Dynamic model message columns matching `*_messages` (excluding `Total_Messages`) are recognized as valid
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 8.1, 8.2, 8.3_

  - [ ]* 1.2 Write property test for schema validation idempotence
    - **Property 1: Schema Validation Idempotence**
    - For any valid CSV header list H and format type F, `validate_schema(H, F)` called twice produces equivalent results
    - **Validates: Requirements 8.4**

  - [ ]* 1.3 Write unit tests for CSV Schema Validator
    - Test valid `user_report` with all required columns present
    - Test rejection when critical columns (`UserId`, `Date`, `Credits_Used`) are missing
    - Test warning when non-critical columns are missing
    - Test that dynamic `*_messages` columns are recognized as valid
    - Test warning for unexpected columns
    - Test valid `by_user_analytic` with `Date` and `UserId`
    - Test rejection of `by_user_analytic` missing `Date` or `UserId`
    - Test unknown format type returns invalid result
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 8.1, 8.2, 8.3_

- [ ] 2. Integrate schema validation into CSV Parser
  - [ ] 2.1 Modify `etl/csv_parser.py` to invoke `validate_schema` after reading headers
    - Import `validate_schema` from `csv_schema_validator` (with try/except fallback pattern)
    - Determine format type from path context (default to `"user_report"`)
    - Call `validate_schema(header_columns, format_type)` before iterating rows
    - If validation fails, log structured error with `StructuredLogger` and return empty list
    - If validation has warnings, log structured warning and continue processing
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 5.6_

  - [ ]* 2.2 Write unit tests for CSV Parser schema validation integration
    - Test that a CSV missing critical columns returns empty list
    - Test that a CSV with all columns parses normally
    - Test that warnings are logged but parsing continues
    - _Requirements: 7.1, 7.2, 7.3_

- [ ] 3. Checkpoint - Ensure schema validation tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Extend Normalizer with model messages and newUser fields
  - [ ] 4.1 Modify `etl/normalizer.py` to extract model message columns and `New_User`
    - Add `modelMessages: dict[str, int]` and `newUser: bool` fields to `UserActivityRecord` dataclass (with `field(default_factory=dict)` and `False` defaults)
    - In `normalize_records`, iterate raw row columns to find `*_messages` (excluding `Total_Messages`), extract model name by removing `_messages` suffix, parse value with `_safe_int`
    - Only include model entries where count > 0
    - Extract `New_User` using `_safe_bool` (handles `true`, `1`, `yes` case-insensitive)
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2_

  - [ ]* 4.2 Write property test for model messages completeness
    - **Property 2: Model Messages Completeness**
    - For any CSV row with N columns matching `*_messages` (excluding `Total_Messages`) where value > 0, the resulting `modelMessages` dict has exactly N entries
    - **Validates: Requirements 1.1, 1.2, 1.3**

  - [ ]* 4.3 Write unit tests for normalizer model messages and newUser extraction
    - Test extraction of multiple model message columns
    - Test that `Total_Messages` is excluded
    - Test non-integer and empty values treated as zero (not included in dict)
    - Test empty model messages when no matching columns exist
    - Test `New_User` with values `true`, `1`, `yes` (case-insensitive) → `True`
    - Test `New_User` with other values or absent → `False`
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2_

- [ ] 5. Pass model messages through CSV Processor to DynamoDB record
  - [ ] 5.1 Modify `etl/processors/csv_processor.py` `_to_dynamo_record` to include `modelMessages` and `newUser`
    - Add `modelMessages` to the output dict only when non-empty
    - Always include `newUser` field from the record
    - _Requirements: 1.4, 2.1, 2.2_

  - [ ]* 5.2 Write unit tests for CSV Processor with model messages
    - Test end-to-end CSV → DynamoDB record includes `modelMessages` dict
    - Test that `newUser` field is present in output
    - Test that empty `modelMessages` is not included in output
    - _Requirements: 1.4, 2.1, 2.2_

- [ ] 6. Persist model messages and newUser in Analytics Writer
  - [ ] 6.1 Add `set_daily_stats_metadata` method to `layers/shared/shared/analytics_writer.py`
    - Implement SET expression for `modelMessages` map attribute (overwrites per day)
    - Only SET `newUser = true` when value is `true` (avoid overwriting previous `true` with `false`)
    - Skip DynamoDB call entirely when no clauses to set
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [ ]* 6.2 Write unit tests for `set_daily_stats_metadata`
    - Test that `modelMessages` is written as a Map attribute
    - Test that `newUser` is written only when `true`
    - Test that `newUser=false` does not produce a write for that attribute
    - Test that empty `modelMessages` and `newUser=false` skips the DynamoDB call
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 7. Wire writer handler to call `set_daily_stats_metadata`
  - [ ] 7.1 Modify `etl/writer_handler.py` `_write_csv_record` to invoke `set_daily_stats_metadata`
    - Extract `modelMessages` and `newUser` from the record dict
    - Call `writer.set_daily_stats_metadata(user_id, date, model_messages, new_user)` when either field has data
    - Wrap in try/except for best-effort (same pattern as `upsert_activity_summary`)
    - Increment items counter on success
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 7.2 Write unit tests for writer handler model messages flow
    - Test that `set_daily_stats_metadata` is called when `modelMessages` is present
    - Test that `set_daily_stats_metadata` is not called when both fields are empty/false
    - Test best-effort error handling (failure does not fail the record)
    - _Requirements: 3.1, 3.2, 3.3_

- [ ] 8. Checkpoint - Ensure all ETL pipeline tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Expose model messages in backend API response
  - [ ] 9.1 Verify `backend/repository/analytics_repository.py` returns `modelMessages` and `newUser` attributes
    - Confirm that the existing `_convert_decimals` helper converts Decimal values within `modelMessages` map to integers
    - If `_convert_decimals` does not handle nested maps, extend it to recursively convert Map values
    - No new endpoint needed — existing daily stats query already returns all item attributes
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 9.2 Write property test for backward compatibility
    - **Property 3: Backward Compatibility Invariant**
    - For any `STATS#DAILY#` item without `modelMessages`, the API response does not inject a `modelMessages` key
    - **Validates: Requirements 4.1, 4.2**

  - [ ]* 9.3 Write property test for critical column rejection totality
    - **Property 4: Critical Column Rejection Totality**
    - For any CSV header set missing at least one of {UserId, Date, Credits_Used}, `validate_schema` returns `valid=False` with at least one error
    - **Validates: Requirements 5.2, 6.2**

- [ ] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The backend repository likely needs no code change (already returns all DynamoDB attributes), but the `_convert_decimals` helper must handle nested maps for `modelMessages`
- All new code follows the project's try/except import pattern, dependency injection, and structured logging conventions

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "4.2", "4.3", "5.1"] },
    { "id": 3, "tasks": ["5.2", "6.1"] },
    { "id": 4, "tasks": ["6.2", "7.1"] },
    { "id": 5, "tasks": ["7.2", "9.1"] },
    { "id": 6, "tasks": ["9.2", "9.3"] }
  ]
}
```
