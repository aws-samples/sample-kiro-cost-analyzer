# Requirements — ETL Parse Payload Size

Fixes a production incident: the ETL Standard state machine has failed on every scheduled run since 2026-08-21 (6 consecutive `FAILED` executions, most recently 2026-08-23T03:44 UTC) with `Error: EtlFilesFailed`. All files in the affected batches fail identically with `Error: States.DataLimitExceeded` on the `ParseAndNormalize` task:

> The state/task 'arn:aws:lambda:sa-east-1:433939225102:function:kiro-cost-analyzer-parse' returned a result with a size exceeding the maximum number of bytes service limit.

Root cause: `Parse` returns the full `prompt` and `response` text inline in its Step Functions Task output (`$.parseResult.records[].prompt` / `.response`). AWS Step Functions caps Task input/output at 256 KB. Kiro conversation logs (`GenerateAssistantResponse`) that include a long generated response — common during extended coding sessions — produce a `Parse` output larger than this limit, and the child execution fails before `WriteToDynamoDB` ever runs.

This is exposed now, not newly introduced, by the `etl-error-propagation` spec (v2.7): child executions that previously converted an unretried exception into a silent `SUCCEEDED`-with-error-payload now correctly fail loud. The size limit itself pre-dates that change.

The project already has a working pattern for this exact constraint:
- `list_uncategorized_handler` writes its list to S3 explicitly "to avoid the 256KB Step Functions payload limit" and returns only the S3 location.
- `AnalyticsWriter.write_prompt` already stores `prompt`/`response` in `prompts-content/{requestId}.json` in the data bucket, inline in DynamoDB only when combined size is ≤ 4 KB (`_INLINE_THRESHOLD_BYTES`).
- `categorize_prompt_handler` already reads prompt content from either DynamoDB or `prompts-content/{requestId}.json`, driven by a `contentInS3` flag.

This spec moves the existing inline/S3 decision earlier in the pipeline — into `Parse`, before the Step Functions Task output is constructed — instead of introducing a new storage mechanism.

## Glossary

- **Parse**: the `kiro-cost-analyzer-parse` Lambda (`etl/parse_handler.py`), the `ParseAndNormalize` Task in the `ProcessFiles` Distributed Map.
- **Writer**: the `kiro-cost-analyzer-writer` Lambda (`etl/writer_handler.py`), the `WriteToDynamoDB` Task.
- **Task payload limit**: the AWS Step Functions hard limit of 256 KB (262,144 bytes) on the combined input+output of any state. Not configurable.
- **Inline threshold**: the existing 4 KB (`_INLINE_THRESHOLD_BYTES`) combined-size cutoff above which `prompt`+`response` are stored in S3 rather than in the DynamoDB item.
- **Content reference**: the `{contentInS3: bool, prompt: str, response: str}` shape a prompt record carries once content placement has been decided. When `contentInS3` is `true`, `prompt`/`response` are empty strings and the content lives at `prompts-content/{requestId}.json`.

## Requirement 1: Parse must never return an oversized Task payload

**User Story.** As an operator, I want the ETL pipeline to process files with large prompt/response content without failing on the Step Functions payload limit, so that scheduled ETL runs stay green regardless of conversation length.

### Acceptance Criteria

1.1. WHEN `Parse` processes a `fileType: "prompt"` file THEN, for every record whose combined `prompt`+`response` UTF-8 byte size exceeds the existing 4 KB inline threshold, THE `Parse` Lambda SHALL write the content to `prompts-content/{requestId}.json` in the data bucket and SHALL return that record with `contentInS3: true` and empty `prompt`/`response` fields in its Task output.

1.2. WHEN a record's combined `prompt`+`response` size is at or below the 4 KB inline threshold THEN `Parse` SHALL return the record with `contentInS3: false` and the content inline, unchanged from current behavior.

1.3. THE `prompts-content/{requestId}.json` object SHALL use the same key format and JSON shape (`{"prompt": ..., "response": ...}`) already produced by `AnalyticsWriter.write_prompt`, so `categorize_prompt_handler` requires no changes.

1.4. THE `Parse` Task output (`$.parseResult`) SHALL stay under the 256 KB Step Functions limit for any realistic batch of records extracted from a single `.json.gz` file, given 1.1.

1.5. `fileType: "csv"` records SHALL be unaffected: `Parse` SHALL NOT alter CSV record handling in any way.

## Requirement 2: Writer must not re-decide or re-write content placement

**User Story.** As a maintainer, I want a single source of truth for the inline-vs-S3 decision, so the codebase does not carry two independent implementations of the same threshold that can silently diverge.

### Acceptance Criteria

2.1. WHEN `Writer` receives a prompt record with `contentInS3: true` THEN IT SHALL write the DynamoDB item with `contentInS3: true` and SHALL NOT write to `prompts-content/{requestId}.json` again (the object already exists from Parse).

2.2. WHEN `Writer` receives a prompt record with `contentInS3: false` THEN IT SHALL write `prompt`/`response` inline into the DynamoDB item, unchanged from current behavior.

2.3. `AnalyticsWriter.write_prompt` SHALL take the placement decision (`contentInS3`) as already made by the caller rather than recomputing it from `prompt_content`/`response_content` byte length. The 4 KB `_INLINE_THRESHOLD_BYTES` constant and its size computation move to `Parse` (or a shared helper both `Parse` and any future caller can import) and are removed from `AnalyticsWriter`.

2.4. THE public signature change to `AnalyticsWriter.write_prompt` SHALL be updated at its one call site (`etl/writer_handler.py::_write_prompt_record`) in the same change.

## Requirement 3: No change to any other consumer or contract

**User Story.** As a maintainer, I want this fix scoped tightly to the two Lambdas involved, so unrelated pipeline stages (categorization, dashboard API) carry zero regression risk.

### Acceptance Criteria

3.1. `categorize_prompt_handler`, `prompts_handler` (dashboard `GET /prompts`), and any other reader of `contentInS3` / `prompts-content/{requestId}.json` SHALL require no code changes, because the object key format and JSON shape are unchanged (Requirement 1.3).

3.2. THE `CategorizePrompts` Map, `ListUncategorizedPrompts`, and every state after `RecordStatus` in `template.yaml` SHALL NOT be modified by this spec.

3.3. THE `ProcessedFilesTable`, `AnalyticsTable` schema, and SSM `/kiro-cost-analyzer/etl-status` payload SHALL be unchanged.

3.4. THE `etl-error-propagation` behavior (child execution fails loud, `EtlFilesFailed` Fail state, `ToleratedFailurePercentage: 100`) SHALL be preserved as-is; this spec fixes the underlying cause of the failures that behavior correctly surfaced, not the propagation mechanism itself.

## Requirement 4: Infrastructure permissions

**User Story.** As an operator, I want `Parse` to have exactly the permissions it needs to write prompt content to the data bucket, so the fix does not silently fail on `AccessDenied` after deploy.

### Acceptance Criteria

4.1. THE `ParseFunction` resource in `template.yaml` SHALL gain an `s3:PutObject` policy statement scoped to `arn:aws:s3:::${DataBucket}/*`, following the existing pattern of `WriteDataBucket` on `WriterFunction`.

4.2. THE `ParseFunction` resource SHALL gain a `DATA_BUCKET` environment variable set to `!Ref DataBucket`, following the existing pattern on `WriterFunction`.

4.3. No other IAM statement on `ParseFunction` (source bucket read, KMS, Identity Store, SSM, cross-account assume-role) SHALL be modified.

## Requirement 5: Recovery of the currently-failed batches

**User Story.** As an operator, I want the files that failed during the incident window to be processed once the fix is deployed, so no data is permanently lost.

### Acceptance Criteria

5.1. Because failed child executions never write to `ProcessedFilesTable` (existing `etl-error-propagation` behavior), files from the 6 failed executions (2026-08-21T15:14 UTC through 2026-08-23T03:44 UTC) SHALL be automatically reprocessed on the next successful ETL run after deploy, with no manual intervention or backfill script required.

5.2. THE fix SHALL be verified against at least one real record known to have caused `States.DataLimitExceeded` before being considered complete (see test plan in design.md).

## Out of scope

- Changing the 4 KB inline threshold value itself.
- Any change to how large *CSV* activity records are handled (none are known to approach the limit; no evidence of CSV-driven failures in the incident).
- Retroactively backfilling `prompts-content/` for prompt records already written inline in DynamoDB below today's incident window.
- Alerting/notification on ETL failure (e.g., SNS on `EtlFilesFailed`) — separate concern from this spec.
