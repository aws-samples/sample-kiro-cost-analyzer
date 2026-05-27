# Design — ETL Error Propagation

## Overview

This design closes issue #5 and fixes the underlying root cause that makes ETL child executions silently succeed when a Lambda raises an exception. The fix is scoped to two files: the `ProcessFiles` Distributed Map definition in `template.yaml`, and the `RecordStatus` Lambda (`etl/record_status_handler.py`). No changes to data contracts, DynamoDB schema, SSM payload, or the dashboard.

The design follows three principles:

1. **Fail fast, fail loud.** Fatal exceptions propagate from Lambda → child execution → Map manifest → `RecordStatus` → Standard state machine, with no silent intermediate conversion to success.
2. **Transient retries untouched.** Existing `Retry` clauses for `Lambda.ServiceException`, `Lambda.TooManyRequestsException`, and DynamoDB throttling remain the sole retry mechanism. Removing `Catch: States.ALL` does not affect transient-error handling.
3. **Minimal blast radius.** Only the two files above change. `ProcessedFilesTable` behavior, categorization Map, and the SSM payload schema are preserved.

## Current behavior (for reference)

```
ParseAndNormalize ─[exception]→ Catch States.ALL ─→ RecordFileError (Pass, End) ─→ child SUCCEEDED
                                                          │
                                                          └─→ result written to ResultWriter S3
                                                              under SUCCEEDED group, payload
                                                              {status: "ERROR", key, error}

RecordStatus reads manifest → counts errors → writes status="ERROR" to SSM → returns normally
                                                                                     │
                                                                                     └─→ state machine continues
                                                                                         Next: ListUncategorizedPrompts
                                                                                         Final state: SUCCEEDED (green)
```

## Target behavior

```
ParseAndNormalize ─[fatal exception]→ (no catch) ─→ child FAILED
                                                           │
                                                           └─→ result in ResultWriter S3 under FAILED group

ParseAndNormalize ─[transient, after retries exhausted]→ (no catch) ─→ child FAILED (same path)

RecordStatus reads manifest → counts FAILED + success-group-error payloads
                           → writes status="ERROR" to SSM
                           → returns {status: "ERROR", filesFailed: N, ...}

Choice CheckEtlErrors: if filesFailed > 0 → Fail state "EtlFilesFailed"
                      else               → ListUncategorizedPrompts (existing flow)
```

## Changes to `template.yaml`

### A. Remove `Catch: States.ALL` from the `ProcessFiles` Map and set `ToleratedFailurePercentage: 100`

Three states currently have a `Catch: States.ALL` that routes to `RecordFileError`:

- `ParseAndNormalize`
- `WriteToDynamoDB`
- `MarkFileProcessed`

All three `Catch` blocks are removed. The terminal `RecordFileError` `Pass` state is also removed — it has no remaining inbound transition. Existing `Retry` clauses are unchanged.

After removal, a child execution terminates as FAILED the moment any state raises an unretried exception. The Distributed Map ResultWriter places the failure in `ResultFiles.FAILED` of the manifest, where `RecordStatus` reads it.

Additionally, the Map declares `ToleratedFailurePercentage: 100`. Without this, the Distributed Map defaults to failing the Map (and the parent state machine) the moment the first child fails, bypassing the `RecordStatus` / `CheckEtlErrors` / `EtlFilesFailed` path designed below. With `100%`, the Map always completes, every child runs (successes persist their data normally, failures land in `ResultFiles.FAILED`), and the operator-facing failure signal comes from our own `EtlFilesFailed` state with a descriptive cause. This was discovered during Checkpoint 3 fault injection: a single poison file caused the Map to fail with `States.ExceedToleratedFailureThreshold` and the state machine never reached `RecordStatus`, leaving the SSM payload stale.

`MarkFileProcessed` keeps `End: true` (unchanged).

### B. Add a `Fail` state triggered by `RecordStatus` result

Current flow: `RecordStatus → ListUncategorizedPrompts`.

New flow:

```
RecordStatus (ResultPath: $.recordStatusResult)
    │
    ▼
CheckEtlErrors (Choice)
    ├─ $.recordStatusResult.filesFailed > 0 ─→ EtlFilesFailed (Fail)
    └─ default                                ─→ ListUncategorizedPrompts
```

New states:

```yaml
CheckEtlErrors:
  Type: Choice
  Choices:
    - Variable: "$.recordStatusResult.filesFailed"
      NumericGreaterThan: 0
      Next: EtlFilesFailed
  Default: ListUncategorizedPrompts

EtlFilesFailed:
  Type: Fail
  Error: "EtlFilesFailed"
  CausePath: "States.Format('{} file(s) failed during ETL. First error: {}', $.recordStatusResult.filesFailed, States.ArrayGetItem($.recordStatusResult.errors, 0))"
```

`CausePath` uses Step Functions intrinsic functions to build a dynamic cause string (requires the State Language update that supports `CausePath`, which is available in Standard workflows). The `errors` array is already truncated to 10 entries of ≤200 chars each by `RecordStatus`, so the generated cause stays well within Step Functions' limits.

The `RecordStatus` task's existing `ResultPath: "$.recordStatusResult"` is preserved so the Choice can inspect the return value.

### C. No other state changes

- `RecordStatusNoFiles` (zero-files path) is unchanged — zero files is not an error.
- `ListUncategorizedPrompts` and below are unchanged (Requirement 5).
- `Retry` clauses on `ParseAndNormalize` and `WriteToDynamoDB` are unchanged.
- `ProcessedFilesTable` writes remain inside `MarkFileProcessed`, which only executes on the success path. A failed file is automatically eligible for reprocessing on the next ETL run (Requirement 1.4).

## Changes to `etl/record_status_handler.py`

### D. `_read_map_results_from_s3` — propagate manifest read failures

Current code swallows all exceptions when fetching the manifest or individual result files (`except Exception: return []` or `continue`). This is replaced by:

- **Manifest fetch failure**: re-raise. The Lambda fails → state machine transitions to `FAILED` → `EtlFilesFailed` is not reached, but the execution is still red (which is the goal). The SSM write that normally precedes the raise is skipped because the exception happens before any data is available.
- **Individual result file failure**: log at ERROR (file key, error type, stack trace) and count as one failed file in the summary. The manifest was readable, so we have partial information; it is better to proceed and report what we can than to abort entirely.

Pseudocode sketch:

```python
def _read_map_results_from_s3(bucket, key, logger):
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)  # raises → handler raises
    manifest = json.loads(resp["Body"].read().decode("utf-8"))

    results = []
    read_failures = 0

    for group in ("SUCCEEDED", "FAILED"):
        for item in manifest.get("ResultFiles", {}).get(group, []):
            try:
                child = json.loads(
                    s3.get_object(Bucket=bucket, Key=item["Key"])["Body"].read()
                )
            except Exception as exc:
                logger.error(
                    "Failed to read child result file",
                    resultKey=item.get("Key"),
                    errorType=type(exc).__name__,
                    errorMessage=str(exc),
                )
                read_failures += 1
                continue

            items = child if isinstance(child, list) else [child]
            if group == "FAILED":
                for r in items:
                    r.setdefault("status", "ERROR")
            results.extend(items)

    return results, read_failures
```

The function signature changes from returning `list[dict]` to returning `(list[dict], int)`. The caller treats `read_failures` as additional failed files added to `filesFailed`.

### D'. Normalize Distributed Map FAILED entries (discovered in Checkpoint 3)

AWS Step Functions writes child-execution failures in a shape that does not match the success-path payloads. A FAILED result file looks like:

```json
{
  "Cause": "{\"errorMessage\": \"...\", \"errorType\": \"UnicodeDecodeError\", \"stackTrace\": [...]}",
  "Error": "UnicodeDecodeError",
  "Input": "{\"key\": \"path/to/file.csv\", \"fileType\": \"csv\"}",
  "ExecutionArn": "...",
  "Status": "FAILED"
}
```

The `Input` field is a JSON-encoded string carrying the child-execution input (including the file `key`), and `Cause` is itself a JSON-encoded Lambda error payload with `errorMessage`, `errorType`, and `stackTrace`.

A helper `_normalize_failed_item` converts this to the internal shape `{status: "ERROR", key, error: {Cause, Error}}` so that `_compute_summary` and `_format_error` work transparently for both success-path error payloads (legacy) and FAILED-group entries (new). `_format_error` in turn unwraps the Lambda `Cause` JSON to surface `errorType: errorMessage` without the stack trace, keeping SSM entries compact and the `EtlFilesFailed` cause human-readable.

This normalization was added during Checkpoint 3 when the first end-to-end fault-injection test produced `"Error processing unknown: {}"` instead of the expected `"Error processing <file>: UnicodeDecodeError: ..."`.

### E. `_compute_summary` — recognize all error shapes

Today a child result is counted as an error only when `result.get("status") == "ERROR"`. After change (D), results in the `FAILED` group also have `status: "ERROR"` injected at read time, so no logic change is required for them. However, to be robust against residual payloads from the old design and future changes, the function SHALL treat a result as an error when **any** of the following is true:

- `result.get("status") == "ERROR"`
- `"error" in result` (the `ResultPath: "$.error"` artifact from the old design, still possible during rollout)

A result is counted as a success only when neither condition holds and the result originated from the `SUCCEEDED` manifest group.

This is a defensive, no-op change for the new steady state, and protects against mis-counting during the deploy window where in-flight executions from the previous template version may still land.

### F. `record_status_handler` — remove the `newFilesCount` fallback, fail loudly, log failure

Current fallback:

```python
if not map_results:
    summary["filesSuccess"] = list_result.get("newFilesCount", 0)
```

This is removed (Requirement 3.4). An empty `map_results` combined with a non-zero `newFilesCount` now produces `filesSuccess=0`, `filesFailed=0` (no evidence of failure yet — the manifest said nothing), `status="SUCCESS"`, **and** a WARN log entry. But because the preceding manifest read would have raised on any real error (change D), reaching this code path with empty results means the Map genuinely produced zero items, which only happens if `newFilesCount` was zero in the first place (the `CheckNewFiles` Choice already handles that case separately).

New summary-level logic additionally:

- Adds `read_failures` (from change D) to `filesFailed`.
- Emits a structured ERROR log whenever `filesFailed > 0`, including `errorSample` (first entry of `errors`), `filesFailed`, `filesSuccess`, and `correlationId` (Requirement 6.1).

### G. Handler return shape is preserved

The return dict keeps the same keys (`status`, `filesProcessed`, `filesFailed`, `recordsWritten`, `errors`) and the SSM payload shape is unchanged (Requirement 4.3). The new `CheckEtlErrors` Choice reads `$.recordStatusResult.filesFailed`, which already exists in the return value today.

## Data / State Contracts

| Contract | Status |
|---|---|
| `ProcessedFilesTable` entries | Unchanged. Only successful files are marked. |
| SSM `/kiro-cost-analyzer/etl-status` payload | Unchanged (same keys, same truncation rules). |
| Map manifest shape | Produced by Step Functions — unchanged. |
| `RecordStatus` return value | Unchanged keys. `filesFailed` now reflects FAILED-group children + SUCCEEDED-group error payloads + read failures. |
| Dashboard API | Unchanged. Reads SSM as today. |

## Error Handling Matrix

| Failure source | Before | After |
|---|---|---|
| Parse Lambda raises (KMS AccessDenied, ValidationException, parser bug, …) | Child SUCCEEDED, file counted as ERROR in SSM, state machine green | Child FAILED, file in manifest FAILED group, state machine fails via `EtlFilesFailed` |
| Writer Lambda raises (ValidationException, bug, …) | Same as above | Same as above |
| `MarkFileProcessed` DynamoDB call fails (non-throttle) | Same as above | Same as above |
| Parse / Writer transient (`Lambda.ServiceException`, etc.) | Retry (3×), then child SUCCEEDED with error payload | Retry (3×), then child FAILED — state machine fails |
| DynamoDB throttling on Writer | Retry (3×), then child SUCCEEDED with error payload | Retry (3×), then child FAILED — state machine fails |
| `RecordStatus` cannot read manifest | Returns "SUCCESS" via `newFilesCount` fallback, state machine green | Lambda raises, state machine fails at `RecordStatus` step |
| `RecordStatus` cannot read one child result file | Skipped silently | Logged at ERROR, counted as 1 failed file |
| `filesFailed > 0` overall | SSM reports ERROR, state machine green | SSM reports ERROR, state machine fails at `EtlFilesFailed` |
| Zero input files | `RecordStatusNoFiles` path, SUCCESS | Unchanged |

## Correctness Properties

Property-based tests (Hypothesis) validate the following invariants on `_compute_summary` and the combined `_read_map_results_from_s3` + `_compute_summary` pipeline with synthesized manifests.

1. **Success totality**: for every list of result dicts, `filesSuccess + filesFailed == len(results) + read_failures`. No result is dropped or double-counted.
2. **Error preservation**: every result classified as an error contributes at most one entry to `summary["errors"]`, capped at 10 entries, each ≤ 200 characters.
3. **Status determinism**: `summary["status"] == "ERROR"` if and only if `filesFailed > 0`. Equivalent formulation: for all inputs, `filesFailed == 0 ⇔ status == "SUCCESS"`.
4. **SSM payload bounded**: the serialized SSM value is always ≤ 4000 characters, regardless of input size (existing truncation path).
5. **Backward compatibility**: given a legacy SUCCEEDED-group payload `{status: "ERROR", key, error}`, `_compute_summary` still classifies it as failed (Requirement 4.2).
6. **Manifest read propagation**: if `s3.get_object(manifest_key)` raises, `_read_map_results_from_s3` raises with the same exception class. If an individual child result raises, it is counted as one `read_failure` and does not abort the function.

Existing tests in `tests/test_record_status_handler.py` (4 unit tests on `_compute_summary`, 5 on `_format_error`, plus `TestRecordStatusHandlerHappyPath`) remain valid after the minor signature change on `_read_map_results_from_s3` — they mock it directly, so only the tests that assert `return []` on read failure need to be updated (there are none today; the current behavior is untested).

## Rollout considerations

- **In-flight executions during deploy**: the new Standard definition only applies to new executions. Any execution that started under the old template keeps running under its old definition. No cross-version concern.
- **First post-deploy execution is more honest**: if the system has been masking errors, the first run after this change may fail. That is the point. The SSM payload already showed this state; the change is only that the state machine is now red too.
- **Operator playbook** (informational, not part of this spec): a red ETL state machine + SSM `status: "ERROR"` + `errors` array identifies the failing file keys. Files not in `ProcessedFilesTable` are retried automatically on the next schedule; operator action is needed only for persistent failures (corrupted files, permission changes).
