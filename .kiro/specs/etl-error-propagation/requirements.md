# Requirements — ETL Error Propagation

Closes issue #5 (post-Map verification) and the broader root cause: ETL child executions currently complete as SUCCEEDED even when the underlying Lambda raises an exception, because `Catch: States.ALL` transitions to a `Pass` state that ends successfully. As a consequence, the Standard parent Map completes green, `RecordStatus` writes `status: "ERROR"` to SSM but never fails the state machine, and operators have no visible signal that files failed to process.

This spec restores honest error signaling end-to-end: fatal errors fail the child execution, are aggregated by `RecordStatus`, and fail the Standard state machine when at least one file could not be processed.

## Glossary

- **Child execution**: an Express workflow run by the `ProcessFiles` Distributed Map, processing a single source file.
- **Transient error**: a retryable service-side error such as `Lambda.ServiceException`, `Lambda.TooManyRequestsException`, or DynamoDB throttling. Existing retry policies already handle these.
- **Fatal error**: any non-transient error surfaced by Parse, Writer, or `MarkFileProcessed` — for example KMS `AccessDenied`, `ValidationException`, `ResourceNotFoundException`, JSON parsing errors, or unexpected Python exceptions.
- **Map manifest**: the JSON object written by the Distributed Map `ResultWriter` at the end of the Map, pointing to `SUCCEEDED` / `FAILED` result files in S3.
- **Standard state machine**: the top-level `EtlStateMachine` (Standard workflow) that orchestrates `ListNewFiles → ProcessFiles (Map) → RecordStatus → Categorization`.

## Requirement 1: Fatal errors in child executions must surface as failures

**User Story.** As an operator, I want ETL child executions to fail when the underlying Lambda raises a non-transient exception, so that errors are never silently converted into successful runs.

### Acceptance Criteria

1.1. WHEN a `ParseAndNormalize`, `WriteToDynamoDB`, or `MarkFileProcessed` task raises a non-transient exception THEN THE child execution SHALL terminate with status `FAILED` and the error SHALL appear under `ResultFiles.FAILED` in the Map manifest.

1.2. WHEN a task fails with a transient error listed in its `Retry` clause (`Lambda.ServiceException`, `Lambda.TooManyRequestsException`, `DynamoDB.ProvisionedThroughputExceededException`) THEN THE existing retry policy SHALL apply, and the child execution SHALL only fail after all retry attempts are exhausted.

1.3. THE `ProcessFiles` Map SHALL NOT contain any `Catch: States.ALL` clause that transitions to a terminal `Pass` state.

1.4. WHEN a child execution fails THEN THE source file key MUST NOT be written to `ProcessedFilesTable`, so the file is picked up again on the next ETL run.

1.5. THE Standard parent state machine SHALL continue executing after the Map completes, regardless of how many child executions failed, so that `RecordStatus` can still aggregate results.

## Requirement 2: RecordStatus must fail the state machine when errors occur

**User Story.** As an operator, I want the Standard ETL state machine to be marked as failed whenever any file fails to process, so that I can detect problems from the Step Functions console alone without inspecting the Map Run manually.

### Acceptance Criteria

2.1. WHEN `RecordStatus` computes `filesFailed > 0` THEN THE state machine SHALL transition to a `Fail` state with `Error: "EtlFilesFailed"` and a `Cause` field summarizing the failure (file count, first error sample, truncated to ≤ 256 characters).

2.2. WHEN `RecordStatus` computes `filesFailed == 0` THEN THE state machine SHALL continue to the categorization phase (`ListUncategorizedPrompts`) as it does today.

2.3. THE `RecordStatus` Lambda SHALL continue to write the execution summary to SSM Parameter Store (`/kiro-cost-analyzer/etl-status`) before the state machine transitions to `Fail`, so that the dashboard reflects the failed execution.

2.4. THE threshold SHALL initially be fixed at `> 0 failed files`. A configurable threshold (SAM parameter) is explicitly out of scope for this spec.

## Requirement 3: Manifest read failures must not be silently swallowed

**User Story.** As an operator, I want the ETL to fail loudly when `RecordStatus` cannot read the Map manifest from S3, so that a corrupted or unreachable manifest is not misreported as a successful run.

### Acceptance Criteria

3.1. WHEN `_read_map_results_from_s3` fails to fetch or parse the manifest THEN THE function SHALL raise the underlying exception rather than returning an empty list.

3.2. WHEN `_read_map_results_from_s3` fails to fetch or parse an individual result file referenced by the manifest THEN THE `RecordStatus` Lambda SHALL log the failure with file key and error type, count the affected child result as an error in the summary, and continue processing the remaining files.

3.3. WHEN `RecordStatus` cannot read the manifest (per 3.1) THEN THE Lambda SHALL raise, the state machine SHALL transition to a `Fail` state, and SSM SHALL NOT be updated with a false-positive SUCCESS status.

3.4. THE fallback that uses `listResult.newFilesCount` as `filesSuccess` when `map_results` is empty SHALL be removed, because it masks genuine read failures.

## Requirement 4: Summary must distinguish real successes from error payloads

**User Story.** As an operator, I want `_compute_summary` to accurately count successes and failures, so that the SSM payload and dashboard reflect reality.

### Acceptance Criteria

4.1. WHEN a child result is in the manifest's `SUCCEEDED` group AND contains no `error` field THEN IT SHALL be counted as a successful file.

4.2. WHEN a child result is in the manifest's `FAILED` group OR contains an `error` field OR carries `status: "ERROR"` THEN IT SHALL be counted as a failed file and its error MUST be included in the `errors` list (truncated to the existing 200-character limit, first 10 only).

4.3. THE summary SHALL remain backward-compatible with the existing SSM payload schema (`lastExecution`, `status`, `filesProcessed`, `recordsWritten`, `errors`) so the dashboard does not need changes.

4.4. THE `status` field written to SSM SHALL be `"ERROR"` WHEN `filesFailed > 0`, and `"SUCCESS"` otherwise.

## Requirement 5: Categorization Map behavior is unchanged

**User Story.** As a maintainer, I want the categorization Map (post-ETL) to retain its current error-propagation behavior, so that this spec does not regress work done in v2.3.

### Acceptance Criteria

5.1. THE `CategorizePrompts` Map SHALL retain its current definition (retries on transient Bedrock errors only, no `Catch: States.ALL`). This spec MUST NOT modify the categorization phase.

5.2. Fatal errors in `CategorizeOnePrompt` (permission denied, validation exceptions, etc.) SHALL continue to propagate to the Standard state machine as they already do.

## Requirement 6: Observability

**User Story.** As an operator, I want structured log messages that make it easy to locate failures, so that I can debug without correlating manually across executions.

### Acceptance Criteria

6.1. WHEN `RecordStatus` reports `filesFailed > 0` THEN IT SHALL emit a single structured log entry at level `ERROR` with fields `filesFailed`, `filesSuccess`, `errorSample` (first error, truncated), and `correlationId`.

6.2. WHEN a manifest read fails (per 3.1 or 3.2) THEN `RecordStatus` SHALL emit a structured log entry at level `ERROR` with fields `errorType`, `errorMessage`, `manifestBucket`, `manifestKey`, and `stackTrace`.

6.3. Existing `INFO`-level logs (`Computing execution summary`, `Map results loaded`, `Execution status recorded`) SHALL be preserved.

## Out of scope

- Configurable error thresholds (percentage or absolute). Defer until a concrete use case appears.
- Retrying fatal-error files automatically inside the same execution. Re-runs through the scheduler remain the recovery mechanism (file stays out of `ProcessedFilesTable`).
- SNS / CloudWatch alarms. The Step Functions `FAILED` state is the intended operator-facing signal.
- Changes to the categorization Map (see Requirement 5).
