# Requirements Document

## Introduction

This feature extends the Kiro Cost Analyzer ETL pipeline to ingest dynamic model message columns from Kiro's CSV activity reports into the existing DynamoDB daily stats items, and introduces CSV schema validation for both the current `user_report` format and the legacy `by_user_analytic` format. The goal is to enable per-day model distribution data directly on daily stats (reducing DynamoDB reads) and to add structural validation that catches malformed CSVs early while gracefully degrading when Kiro adds new upstream columns.

## Glossary

- **CSV_Parser**: The module (`etl/csv_parser.py`) responsible for reading raw CSV content and producing a list of row dictionaries.
- **CSV_Schema_Validator**: A new module responsible for validating CSV column structure against expected schemas before processing.
- **Normalizer**: The module (`etl/normalizer.py`) that converts raw CSV row dictionaries into `UserActivityRecord` dataclass instances.
- **CSV_Processor**: The module (`etl/processors/csv_processor.py`) that orchestrates parsing, normalization, and conversion to DynamoDB-ready records.
- **Analytics_Writer**: The shared module (`layers/shared/shared/analytics_writer.py`) that performs DynamoDB write operations for the Analytics_Table.
- **Analytics_Repository**: The backend module (`backend/repository/analytics_repository.py`) that performs DynamoDB read operations for the Analytics_Table.
- **Daily_Stats_Item**: A DynamoDB item with PK `USER#{userId}` and SK `STATS#DAILY#{date}` storing aggregated daily activity metrics.
- **Model_Message_Column**: A CSV column whose name matches the pattern `{model_name}_messages` (excluding `Total_Messages`) representing the message count for a specific model on that day.
- **user_report**: The current CSV format produced by Kiro, identified by the `user_report/` path prefix.
- **by_user_analytic**: The legacy CSV format previously produced by Kiro, identified by the `by_user_analytic/` path prefix.
- **Structured_Logger**: The project's JSON logging utility (`shared/structured_logger.py`) used for consistent, queryable log output.

## Requirements

### Requirement 1: Extract Model Message Columns During CSV Parsing

**User Story:** As a KCA administrator, I want the ETL pipeline to extract per-model message counts from the CSV, so that model distribution data is available without separate DynamoDB items per model.

#### Acceptance Criteria

1. WHEN a CSV row contains columns matching the pattern `{name}_messages` (case-sensitive) where the column name is NOT `Total_Messages`, THE CSV_Processor SHALL extract each matching column name and its integer value into a dictionary keyed by the column name without the `_messages` suffix.
2. WHEN a model message column contains a non-integer value or is empty, THE CSV_Processor SHALL treat the value as zero.
3. WHEN a CSV row contains no model message columns, THE CSV_Processor SHALL produce an empty model messages dictionary for that row.
4. THE CSV_Processor SHALL pass the extracted model messages dictionary through to the DynamoDB-ready record as a `modelMessages` field.

### Requirement 2: Extract New_User Column During CSV Parsing

**User Story:** As a KCA administrator, I want the ETL pipeline to extract the `New_User` flag from the CSV, so that I can identify when users first activated their subscription.

#### Acceptance Criteria

1. WHEN a CSV row contains a `New_User` column with a value of `true`, `1`, or `yes` (case-insensitive), THE CSV_Processor SHALL set the `newUser` field to `true` in the DynamoDB-ready record.
2. WHEN a CSV row contains a `New_User` column with any other value or the column is absent, THE CSV_Processor SHALL set the `newUser` field to `false` in the DynamoDB-ready record.

### Requirement 3: Persist Model Messages to DynamoDB Daily Stats

**User Story:** As a KCA administrator, I want model message counts stored on the daily stats item, so that the frontend can compute model distribution by summing maps across days without querying N separate `STATS#MODEL#` items.

#### Acceptance Criteria

1. WHEN the Writer Lambda receives a CSV record containing a non-empty `modelMessages` dictionary, THE Analytics_Writer SHALL store it as a DynamoDB Map attribute named `modelMessages` on the `STATS#DAILY#{date}` item using a SET expression.
2. WHEN the Writer Lambda receives a CSV record containing a `newUser` field set to `true`, THE Analytics_Writer SHALL store a boolean attribute `newUser` with value `true` on the `STATS#DAILY#{date}` item.
3. WHEN the Writer Lambda receives a CSV record containing a `newUser` field set to `false`, THE Analytics_Writer SHALL NOT write a `newUser` attribute (to avoid overwriting a previously-set `true` value from an earlier file for the same day).
4. THE Analytics_Writer SHALL use a SET expression for `modelMessages` that overwrites any previous value for the same date, since the CSV represents the complete model distribution for that day.

### Requirement 4: Expose Model Messages in Backend API Response

**User Story:** As a frontend developer, I want the daily stats API response to include model message data, so that I can render model distribution charts without additional API calls.

#### Acceptance Criteria

1. WHEN the Analytics_Repository retrieves daily stats items that contain a `modelMessages` attribute, THE Analytics_Repository SHALL include the `modelMessages` map in the returned item dictionary.
2. WHEN the Analytics_Repository retrieves daily stats items that contain a `newUser` attribute, THE Analytics_Repository SHALL include the `newUser` boolean in the returned item dictionary.
3. THE Analytics_Repository SHALL convert Decimal values within the `modelMessages` map to integers using the existing `_convert_decimals` helper.

### Requirement 5: Validate CSV Schema for user_report Format

**User Story:** As a KCA administrator, I want the ETL pipeline to validate CSV structure before processing, so that malformed files are detected early and processing failures are easier to diagnose.

#### Acceptance Criteria

1. WHEN a `user_report` CSV is received, THE CSV_Schema_Validator SHALL verify that the following required columns are present: `Date`, `UserId`, `Client_Type`, `Chat_Conversations`, `Credits_Used`, `Overage_Cap`, `Overage_Credits_Used`, `Overage_Enabled`, `ProfileId`, `Subscription_Tier`, `Total_Messages`.
2. WHEN a `user_report` CSV is missing any of the critical columns (`UserId`, `Date`, `Credits_Used`), THE CSV_Schema_Validator SHALL reject the file by returning a validation error result containing the list of missing critical columns.
3. WHEN a `user_report` CSV is missing non-critical required columns (any required column other than `UserId`, `Date`, `Credits_Used`), THE CSV_Schema_Validator SHALL log a warning via Structured_Logger and allow processing to continue.
4. WHEN a `user_report` CSV contains columns ending in `_messages` that are NOT `Total_Messages`, THE CSV_Schema_Validator SHALL recognize them as valid dynamic model message columns.
5. WHEN a `user_report` CSV contains columns that are neither in the required set nor match the `_messages` pattern nor equal `New_User`, THE CSV_Schema_Validator SHALL log a warning identifying the unexpected columns and allow processing to continue.
6. IF the CSV_Schema_Validator rejects a file, THEN THE CSV_Parser SHALL return an empty list and log a structured error with the validation failure details.

### Requirement 6: Validate CSV Schema for by_user_analytic Format

**User Story:** As a KCA administrator, I want minimal validation on legacy format files, so that if the legacy format is re-enabled the pipeline handles it safely.

#### Acceptance Criteria

1. WHEN a `by_user_analytic` CSV is received, THE CSV_Schema_Validator SHALL verify that the columns `Date` and `UserId` are present.
2. WHEN a `by_user_analytic` CSV is missing `Date` or `UserId`, THE CSV_Schema_Validator SHALL reject the file by returning a validation error result containing the list of missing columns.
3. WHEN a `by_user_analytic` CSV passes validation, THE CSV_Schema_Validator SHALL allow processing to continue without further column checks.

### Requirement 7: Schema Validation Integration with CSV Parser

**User Story:** As a KCA developer, I want schema validation to be invoked automatically during CSV parsing, so that no code path can bypass validation.

#### Acceptance Criteria

1. THE CSV_Parser SHALL invoke the CSV_Schema_Validator after reading the CSV header and before iterating over data rows.
2. WHEN the CSV_Schema_Validator returns a rejection result, THE CSV_Parser SHALL return an empty list without processing any data rows.
3. WHEN the CSV_Schema_Validator returns a success result (with or without warnings), THE CSV_Parser SHALL proceed to parse all data rows normally.
4. THE CSV_Parser SHALL pass the detected format type (`user_report` or `by_user_analytic`) to the CSV_Schema_Validator so that the correct schema is applied.

### Requirement 8: Validation Result Structure

**User Story:** As a KCA developer, I want validation results to follow a consistent structure, so that callers can programmatically determine whether to proceed or abort.

#### Acceptance Criteria

1. THE CSV_Schema_Validator SHALL return a result object containing: a boolean `valid` field, a list of `errors` (missing critical columns), and a list of `warnings` (missing non-critical columns, unexpected columns).
2. WHEN `valid` is `false`, THE result SHALL contain at least one entry in the `errors` list.
3. WHEN `valid` is `true` and warnings exist, THE result SHALL contain entries in the `warnings` list describing each non-critical issue.
4. FOR ALL inputs to the CSV_Schema_Validator, parsing the result and then re-validating the same header SHALL produce an equivalent result (idempotence property).
