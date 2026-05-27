# Tasks — ETL Error Propagation

Implementation plan. Tasks are ordered so that each checkpoint leaves the system in a deployable state. Optional tests are marked with `*`.

Requirements are referenced per task using `_Requirements: N.M_`.

---

## Checkpoint 1 — `RecordStatus` handler refactor (no infra change yet)

The handler changes are safe to ship before the Step Functions changes, because the new behavior is backward-compatible with the current Map (failed child executions still land in SUCCEEDED group with `status: "ERROR"`).

- [ ] **1.1** Refactor `_read_map_results_from_s3` to return `(results, read_failures)` and raise on manifest fetch failure.
  - Replace `except Exception: return []` around the manifest `get_object` with a re-raise.
  - Wrap each child-file `get_object` in a try/except that logs at ERROR with `resultKey`, `errorType`, `errorMessage`, increments `read_failures`, and continues.
  - Update the single caller inside `record_status_handler` to the new tuple return.
  - _Requirements: 3.1, 3.2, 6.2_

- [ ] **1.2** Harden `_compute_summary` to treat `status == "ERROR"` OR presence of `error` key as a failure signal (defensive; no-op for new results).
  - _Requirements: 4.1, 4.2, 5.1_

- [ ] **1.3** Remove the `newFilesCount` fallback in `record_status_handler` and fold `read_failures` into `filesFailed`.
  - _Requirements: 3.4, 4.3_

- [ ] **1.4** Emit a structured ERROR log when `filesFailed > 0`, with `filesFailed`, `filesSuccess`, `errorSample` (first entry of `errors`, may be empty string), and `correlationId`. Preserve existing INFO logs.
  - _Requirements: 6.1, 6.3_

- [ ] **1.5** Update `tests/test_record_status_handler.py`:
  - Fix the `TestRecordStatusHandlerHappyPath` mock of `_read_map_results_from_s3` to return the new `(list, int)` tuple.
  - Add unit test: manifest fetch raises `ClientError` → `_read_map_results_from_s3` raises the same exception.
  - Add unit test: one child-file fetch raises → function returns `(partial_results, read_failures=1)` and logs the failure.
  - Add unit test: `record_status_handler` propagates the manifest-read exception and does NOT call `ssm.put_parameter`.
  - Add unit test: ERROR log is emitted when `filesFailed > 0`.
  - _Requirements: 3.1, 3.2, 3.3, 6.1_

- [ ] **1.6 \*** Add property-based tests (Hypothesis) in `tests/test_record_status_handler.py`:
  - Property 1 (success totality): `filesSuccess + filesFailed == len(results)` for arbitrary lists of result dicts.
  - Property 3 (status determinism): `summary["status"] == "ERROR"` ⇔ `filesFailed > 0`.
  - Property 5 (legacy compatibility): given a legacy payload `{status: "ERROR", key, error}`, it is always classified as failed.
  - _Requirements: 4.1, 4.2, 4.4_

**Validation checkpoint 1**: `python -m pytest tests/test_record_status_handler.py -v` passes. System is deployable; behavior unchanged from the operator's point of view because the `Catch` in the Map still routes errors into SUCCEEDED-group payloads, which the updated summary classifies identically.

---

## Checkpoint 2 — Step Functions definition changes

These are the behavior-changing edits. After this checkpoint, the state machine will actually go red when files fail.

- [ ] **2.1** Remove `Catch: States.ALL` from `ParseAndNormalize` in `template.yaml`. Keep the `Retry` clause as-is.
  - _Requirements: 1.1, 1.2, 1.3_

- [ ] **2.2** Remove `Catch: States.ALL` from `WriteToDynamoDB`. Keep the `Retry` clause as-is.
  - _Requirements: 1.1, 1.2, 1.3_

- [ ] **2.3** Remove `Catch: States.ALL` from `MarkFileProcessed`.
  - _Requirements: 1.1, 1.3, 1.4_

- [ ] **2.4** Remove the now-orphan `RecordFileError` `Pass` state.
  - _Requirements: 1.3_

- [ ] **2.5** Insert a new `CheckEtlErrors` `Choice` state between `RecordStatus` and `ListUncategorizedPrompts`.
  - Reads `$.recordStatusResult.filesFailed`.
  - When `NumericGreaterThan: 0` → `EtlFilesFailed`.
  - Default → `ListUncategorizedPrompts` (existing transition).
  - Update `RecordStatus.Next` to point at `CheckEtlErrors`.
  - _Requirements: 2.1, 2.2, 2.3_

- [ ] **2.6** Add the `EtlFilesFailed` `Fail` state with `Error: "EtlFilesFailed"` and `CausePath` using intrinsic `States.Format` / `States.ArrayGetItem` to interpolate `filesFailed` and the first error. Verify `CausePath` is supported by the target `StateMachineType: STANDARD` deployment.
  - _Requirements: 2.1_

- [ ] **2.7** Run `sam validate` and `sam build` to confirm the template is syntactically correct. Fix any schema issues (commonly: `CausePath` only accepted when State Language revision supports it — fall back to `Cause` static string if needed).
  - _Requirements: (infrastructure smoke test)_

**Validation checkpoint 2**: Template compiles, `sam build` succeeds. Still not deployed.

---

## Checkpoint 3 — Deploy and verify on the live pipeline

- [ ] **3.1** `sam deploy` to the target account / region.
  - _Requirements: (deployment)_

- [ ] **3.2** Smoke test: trigger the ETL manually (Settings page "Run ETL" or `aws stepfunctions start-execution`). Happy path — all files succeed.
  - Expected: state machine SUCCEEDED. SSM `status: "SUCCESS"`. `filesFailed: 0`. `ListUncategorizedPrompts` runs normally.
  - _Requirements: 2.2_

- [ ] **3.3** Fault-injection test: temporarily break access to force one file to fail.
  - Option A: add an object to the source prefix whose KMS key the ETL role can't decrypt.
  - Option B (lower risk, reversible): stage a malformed CSV or truncated `.json.gz` that triggers a parse error in `Parse`.
  - Expected observations:
    - Child execution of the offending file shows `FAILED` in the Map Run console.
    - The file's entry appears under `ResultFiles.FAILED` in the manifest JSON in the DataBucket.
    - `RecordStatus` completes, writes SSM with `status: "ERROR"` and `filesFailed: 1`, logs an ERROR entry with `errorSample`.
    - State machine terminates at `EtlFilesFailed` with `Cause` containing the error sample.
    - The source file key is NOT in `ProcessedFilesTable` afterward.
  - Clean up the staged failure after verification.
  - _Requirements: 1.1, 1.4, 2.1, 2.3, 6.1_

- [ ] **3.4** Verify the dashboard reflects the failed execution: ETL status card on the Dashboard header and Settings page shows the failure with timestamp and error sample. (No code change expected; this is a regression check that the SSM payload shape still parses on the frontend.)
  - _Requirements: 4.3_

- [ ] **3.5** Re-run the ETL after cleaning up the injected failure. Expect: state machine SUCCEEDED, the file that previously failed is re-processed (it was still absent from `ProcessedFilesTable`).
  - _Requirements: 1.4_

**Validation checkpoint 3**: End-to-end behavior matches the design's target-state diagram. Issue #5 is closed.

---

## Checkpoint 4 — Documentation

- [ ] **4.1** Update `README.md` Changelog with a new entry (next minor version, e.g., v2.7) summarizing the fix: removal of the swallowing `Catch: States.ALL`, addition of `CheckEtlErrors` / `EtlFilesFailed`, and `_read_map_results_from_s3` hardening. Link to issue #5.
  - _Requirements: (documentation)_

- [ ] **4.2** Update `README.pt-BR.md` Changelog with the Portuguese equivalent entry (pt-BR parity is a project invariant per steering).
  - _Requirements: (documentation)_

- [ ] **4.3** Close issue #5 on GitHub with a pointer to the merged PR.
  - _Requirements: (issue closure)_

---

## Task → Requirement traceability matrix

| Task | Requirements covered |
|---|---|
| 1.1 | 3.1, 3.2, 6.2 |
| 1.2 | 4.1, 4.2, 5.1 |
| 1.3 | 3.4, 4.3 |
| 1.4 | 6.1, 6.3 |
| 1.5 | 3.1, 3.2, 3.3, 6.1 |
| 1.6 \* | 4.1, 4.2, 4.4 |
| 2.1 | 1.1, 1.2, 1.3 |
| 2.2 | 1.1, 1.2, 1.3 |
| 2.3 | 1.1, 1.3, 1.4 |
| 2.4 | 1.3 |
| 2.5 | 2.1, 2.2, 2.3 |
| 2.6 | 2.1 |
| 3.2 | 2.2 |
| 3.3 | 1.1, 1.4, 2.1, 2.3, 6.1 |
| 3.4 | 4.3 |
| 3.5 | 1.4 |

Requirement 1.5 (Standard state machine continues executing after the Map) is enforced by the `ToleratedFailurePercentage: 100` attribute added to the `ProcessFiles` Map (see task 2.1). Without it, the Distributed Map defaults to failing the state machine on the first child failure, bypassing `RecordStatus`. Verified behaviorally in task 3.3. Requirement 2.4 (fixed `> 0` threshold) is enforced by the static `NumericGreaterThan: 0` in task 2.5. Requirements 5.1 and 5.2 are enforced by not modifying the categorization states (no task touches them).
