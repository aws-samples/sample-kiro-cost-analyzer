# Tasks — ETL Parse Payload Size

Implementation plan. Tasks ordered so each checkpoint leaves the system deployable. Optional tests marked `*`.

Requirements referenced per task using `_Requirements: N.M_`.

---

## Checkpoint 1 — Shared logic and `AnalyticsWriter` contract change

- [ ] **1.1** Remove `_INLINE_THRESHOLD_BYTES` and its size computation from `layers/shared/shared/analytics_writer.py::write_prompt`. Change the signature to accept `content_in_s3: bool` as a required parameter (inserted before `category`). The S3 `put_object` call inside `write_prompt` is deleted — content placement is now the caller's responsibility.
  - _Requirements: 2.3_

- [ ] **1.2** Update `tests/test_analytics_writer.py` (4 occurrences): pass `content_in_s3` explicitly at each `write_prompt` call. Add one test asserting `content_in_s3=True` does NOT call `s3.put_object`, and one asserting `content_in_s3=False` still writes `prompt`/`response` inline (existing behavior, now driven by the parameter instead of internal computation).
  - _Requirements: 2.1, 2.2_

**Validation checkpoint 1**: `python -m pytest tests/test_analytics_writer.py -v` passes. `AnalyticsWriter` no longer compiles without a caller update — this is expected; checkpoint 2 fixes the one call site.

---

## Checkpoint 2 — `Parse` takes over the placement decision

- [ ] **2.1** Add `_INLINE_THRESHOLD_BYTES = 4096` and a `_resolve_content_placement(records, data_bucket, s3_client, logger)` helper to `etl/parse_handler.py`, per design.md. For each prompt record: compute combined UTF-8 size of `prompt`+`response`; if over threshold, `put_object` to `prompts-content/{requestId}.json` (same key/shape as today), set `contentInS3: True`, clear `prompt`/`response` to `""`; else set `contentInS3: False` and leave content untouched.
  - _Requirements: 1.1, 1.2, 1.3_

- [ ] **2.2** Wire a same-account S3 client (NOT `cross_account_client`, which is scoped to the source bucket) into `parse_handler`, read `DATA_BUCKET` from environment, and call `_resolve_content_placement` on `records` immediately after user-name enrichment, only when `file_type == "prompt"`.
  - _Requirements: 1.1, 1.5_

- [ ] **2.3** Confirm no try/except swallows exceptions from `_resolve_content_placement` — a `put_object` failure must propagate so the existing `ParseAndNormalize` `Retry` clause (`Lambda.ServiceException`, `Lambda.TooManyRequestsException`) can retry, consistent with the file's existing error-handling philosophy.
  - _Requirements: 1.1_

- [ ] **2.4** Update `etl/writer_handler.py::_write_prompt_record` to read `content_in_s3 = record.get("contentInS3", False)` and pass it to `writer.write_prompt(...)`. The `False` default handles in-flight Map children still running the previous Parse output during the deploy window.
  - _Requirements: 2.1, 2.2, 2.4_

- [ ] **2.5** Update `tests/test_writer_handler.py`: add `contentInS3` to every prompt-record fixture used across the ~19 existing references; update `write_prompt` call-arg assertions to include the new argument. Add one test for the `contentInS3` key absent → defaults to `False`, writes inline.
  - _Requirements: 2.1, 2.2, 2.4_

**Validation checkpoint 2**: `python -m pytest tests/test_writer_handler.py tests/test_analytics_writer.py -v` passes.

---

## Checkpoint 3 — `Parse` tests, including the incident regression test

- [ ] **3.1** Add to `tests/test_parse_handler.py`: `_resolve_content_placement` writes S3 and clears content when combined size > 4096 bytes, sets `contentInS3: True`. Mock the S3 client; assert exactly one `put_object` call with key `prompts-content/{requestId}.json` and body `{"prompt": ..., "response": ...}`.
  - _Requirements: 1.1, 1.3_

- [ ] **3.2** Add: `_resolve_content_placement` leaves `prompt`/`response` untouched, sets `contentInS3: False`, and does not call `put_object`, when combined size ≤ 4096 bytes.
  - _Requirements: 1.2_

- [ ] **3.3** Add the incident regression test: `parse_handler` invoked end-to-end for `fileType: "prompt"` with a synthetic `.json.gz` fixture whose response body is ~500 KB. Assert (a) `records[0]["contentInS3"] is True`, (b) `records[0]["response"] == ""`, (c) `len(json.dumps(result).encode("utf-8"))` is well under 262144 bytes — directly reproducing and disproving the `States.DataLimitExceeded` failure mode from the incident.
  - _Requirements: 1.4, 5.2_

- [ ] **3.4** Confirm `fileType: "csv"` tests in `test_parse_handler.py` / `test_csv_parser.py` are unaffected (no `_resolve_content_placement` call on that path). No new test needed if existing coverage already exercises the CSV branch; otherwise add one assertion that `_process_csv_file` output has no `contentInS3` key.
  - _Requirements: 1.5_

**Validation checkpoint 3**: `python -m pytest tests/test_parse_handler.py -v` passes, including the new regression test.

---

## Checkpoint 4 — Infrastructure

- [ ] **4.1** In `template.yaml`, add `DATA_BUCKET: !Ref DataBucket` to `ParseFunction`'s `Environment.Variables`.
  - _Requirements: 4.2_

- [ ] **4.2** In `template.yaml`, add a `WriteDataBucket` statement to `ParseFunction`'s `Policies` (mirrors `WriterFunction`'s existing statement): `s3:PutObject` on `arn:aws:s3:::${DataBucket}/*`.
  - _Requirements: 4.1_

- [ ] **4.3** Confirm no other `ParseFunction` statement (`ReadSourceBucket`, `KMSDecrypt`, `UserNamesTableAccess`, `KMSForDynamoDB`, `IdentityCenterAccess`, `SSMAccess`, conditional assume-role statements) is touched. Run `sam validate` / `make deploy` dry-run (or `sam build`) to confirm the template is syntactically correct.
  - _Requirements: 4.3_

**Validation checkpoint 4**: `sam build` succeeds. Full test suite green: `python -m pytest tests/ -v`.

---

## Checkpoint 5 — Deploy and verify against the live incident

- [ ] **5.1** `make deploy` (per project convention — never bypass the Makefile).
  - _Requirements: (deployment)_

- [ ] **5.2** Manually trigger the ETL (Settings → "Run ETL" or `aws stepfunctions start-execution --profile kca --region sa-east-1`) to reprocess the backlog that has failed since 2026-08-21T15:14 UTC (those files were never marked in `ProcessedFilesTable`, so they are picked up automatically — no backfill script).
  - _Requirements: 5.1_

- [ ] **5.3** Verify via `aws stepfunctions describe-execution` / `get-execution-history`: state machine `SUCCEEDED`, no `States.DataLimitExceeded`. Verify SSM `/kiro-cost-analyzer/etl-status` shows `status: "SUCCESS"`, `filesFailed: 0`.
  - _Requirements: 5.1, 5.2_

- [ ] **5.4** Spot-check one recovered large-response record directly in DynamoDB (`aws dynamodb get-item`) and in S3 (`aws s3 cp s3://.../prompts-content/{requestId}.json -`): confirm `contentInS3: true`, `prompt`/`response` absent from the DynamoDB item, full text present in the S3 object.
  - _Requirements: 1.3, 3.1_

- [ ] **5.5** Load the dashboard's prompt detail view for the recovered record (exercises `categorize_prompt_handler` / `prompts_handler` unchanged S3-read path end-to-end) and confirm it renders the full prompt/response.
  - _Requirements: 3.1_

**Validation checkpoint 5**: The specific incident (6 consecutive `FAILED` ETL executions since 2026-08-21) is resolved; scheduled runs are green going forward.

---

## Checkpoint 6 — Documentation

- [ ] **6.1** Add a `README.md` Changelog entry for the next version summarizing the fix: `Parse` now decides prompt/response inline-vs-S3 placement before returning its Step Functions Task output, preventing `States.DataLimitExceeded` on long conversation logs.
  - _Requirements: (documentation)_

- [ ] **6.2** Add the pt-BR equivalent entry to `README.pt-BR.md` (project invariant: bilingual changelog parity).
  - _Requirements: (documentation)_

---

## Task → Requirement traceability matrix

| Task | Requirements covered |
|---|---|
| 1.1 | 2.3 |
| 1.2 | 2.1, 2.2 |
| 2.1 | 1.1, 1.2, 1.3 |
| 2.2 | 1.1, 1.5 |
| 2.3 | 1.1 |
| 2.4 | 2.1, 2.2, 2.4 |
| 2.5 | 2.1, 2.2, 2.4 |
| 3.1 | 1.1, 1.3 |
| 3.2 | 1.2 |
| 3.3 | 1.4, 5.2 |
| 3.4 | 1.5 |
| 4.1 | 4.2 |
| 4.2 | 4.1 |
| 4.3 | 4.3 |
| 5.2 | 5.1 |
| 5.3 | 5.1, 5.2 |
| 5.4 | 1.3, 3.1 |
| 5.5 | 3.1 |

Requirement 3.2 (categorization Map / states after `RecordStatus` untouched) and 3.3 (`ProcessedFilesTable`/`AnalyticsTable`/SSM schema unchanged) and 3.4 (`etl-error-propagation` behavior preserved) are enforced by omission — no task in this plan touches `template.yaml` states, DynamoDB schema, or the Map's `Catch`/`ToleratedFailurePercentage` configuration. Requirement 4.3 is verified explicitly by task 4.3.
