# Design — ETL Parse Payload Size

## Overview

This design closes the production incident where the ETL Standard state machine has failed on every run since 2026-08-21 with `States.DataLimitExceeded` on `ParseAndNormalize`. The fix relocates the existing inline-vs-S3 decision for prompt/response content from `Writer` (where it happens too late, after the oversized payload has already round-tripped through the Step Functions Task boundary) to `Parse` (where it can prevent the oversized payload from ever being constructed).

The change is scoped to three files:
- `etl/parse_handler.py` / `etl/processors/prompt_processor.py` — decide and act on content placement.
- `layers/shared/shared/analytics_writer.py` — stop recomputing the decision; take it as given.
- `etl/writer_handler.py` — pass the already-known `contentInS3` flag through.
- `template.yaml` — grant `Parse` the S3 write permission and `DATA_BUCKET` env var it needs.

No DynamoDB schema change, no Step Functions state-graph change, no change to `CategorizePrompts` or any dashboard-facing contract.

## Current behavior (for reference)

```
Parse (ParseAndNormalize)
  reads .json.gz → parse_prompt_file → normalize_prompt_records
  → _to_dynamo_record includes full prompt + response text
  → returns {"records": [...], "key", "fileType", "recordCount"}
      ⚠ Task output size = Σ(prompt + response) across all records in the file.
        No cap. A single record with a long generated response can exceed
        256 KB alone.

Step Functions: $.parseResult ← Parse output   (FAILS HERE if > 256 KB)

Writer (WriteToDynamoDB)
  receives event["records"] (each with inline prompt/response)
  _write_prompt_record → writer.write_prompt(user_id, record, prompt, response, category)
  AnalyticsWriter.write_prompt:
    combined_size = len(prompt) + len(response)
    content_in_s3 = combined_size > 4096          ← decision made HERE, too late
    if content_in_s3: s3.put_object(prompts-content/{requestId}.json, {prompt, response})
    else: item["prompt"] = prompt; item["response"] = response
    table.put_item(item)
```

The 256 KB ceiling is on the `ParseAndNormalize` Task's own output, which is constructed and handed to Step Functions **before** `Writer` (and therefore before `AnalyticsWriter.write_prompt`) ever runs. Moving the S3 write into `Writer` was never late in terms of correctness — the DynamoDB item ends up correct — but it is late in terms of the Step Functions payload boundary that fails first.

## Target behavior

```
Parse (ParseAndNormalize)
  reads .json.gz → parse_prompt_file → normalize_prompt_records
  → _to_dynamo_record includes full prompt + response text (unchanged so far)
  → NEW: _resolve_content_placement(records) for fileType == "prompt":
        for each record:
          combined_size = utf8_len(record["prompt"]) + utf8_len(record["response"])
          if combined_size > INLINE_THRESHOLD_BYTES (4096):
              s3.put_object(data_bucket, f"prompts-content/{record['requestId']}.json",
                             {"prompt": record["prompt"], "response": record["response"]})
              record["contentInS3"] = True
              record["prompt"] = ""
              record["response"] = ""
          else:
              record["contentInS3"] = False
  → returns {"records": [...], "key", "fileType", "recordCount"}
      ✅ Task output size = only inline (≤4KB each) prompt/response content.
        Bounded per record; matches the size discipline the categorization
        Map's ItemReader/ResultWriter pattern already relies on.

Step Functions: $.parseResult ← Parse output   (stays within limit)

Writer (WriteToDynamoDB)
  receives event["records"] (each already carrying contentInS3, and prompt/response
    populated only when contentInS3 is False)
  _write_prompt_record → writer.write_prompt(user_id, record, category=...)
  AnalyticsWriter.write_prompt:
    content_in_s3 = record["contentInS3"]        ← decision READ, not computed
    if content_in_s3: item["prompt"], item["response"] left unset (object already in S3)
    else: item["prompt"] = record["prompt"]; item["response"] = record["response"]
    table.put_item(item)
```

`categorize_prompt_handler` is untouched: it already reads `prompts-content/{requestId}.json` when `contentInS3` is `true` on the DynamoDB item it scans, and that item's `contentInS3`/key format do not change.

## Changes to `etl/processors/prompt_processor.py`

`process_prompts` currently returns plain dicts with full `prompt`/`response` via `_to_dynamo_record`. This module does not have S3 access today and should not gain it — placement decision belongs in `parse_handler.py`, which already owns the S3/cross-account client wiring. No change to this file.

## Changes to `etl/parse_handler.py`

Add a new step after `_process_prompt_file` returns and before the function returns its result, only for `file_type == "prompt"`:

```python
# New: shared threshold constant (also imported by analytics_writer's caller
# expectations doc, but defined once here since Parse now owns the decision)
_INLINE_THRESHOLD_BYTES = 4096  # moved from shared/analytics_writer.py


def _resolve_content_placement(
    records: list[dict], data_bucket: str, s3_client, logger: StructuredLogger
) -> None:
    """Decide inline vs S3 storage for each prompt record's content, in place.

    Mirrors the threshold previously applied in AnalyticsWriter.write_prompt,
    but runs before the Step Functions Task output is constructed so an
    oversized combined prompt+response never crosses the 256KB Task payload
    limit between Parse and Writer.
    """
    client = s3_client or boto3.client("s3")
    for record in records:
        prompt = record.get("prompt", "")
        response = record.get("response", "")
        combined_size = len(prompt.encode("utf-8")) + len(response.encode("utf-8"))
        content_in_s3 = combined_size > _INLINE_THRESHOLD_BYTES
        record["contentInS3"] = content_in_s3
        if content_in_s3:
            request_id = record["requestId"]
            client.put_object(
                Bucket=data_bucket,
                Key=f"prompts-content/{request_id}.json",
                Body=json.dumps(
                    {"prompt": prompt, "response": response}, ensure_ascii=False
                ).encode("utf-8"),
                ContentType="application/json",
            )
            record["prompt"] = ""
            record["response"] = ""
```

Call site in `parse_handler`, immediately after the existing name-enrichment block:

```python
if file_type == "prompt":
    data_bucket = os.environ.get("DATA_BUCKET", "")
    _resolve_content_placement(records, data_bucket, cross_account_client_for_data_bucket, logger)
```

Important: the S3 client used for this write is **not** `cross_account_client` (that one is scoped to the source bucket, possibly in another account, and only has `s3:GetObject` there). It must be a plain same-account `boto3.client("s3")` against the ETL stack's own `DataBucket`, matching what `Writer` uses today. `parse_handler.py` does not currently construct such a client — add one (module-level lazy singleton, same pattern as `_get_categorizer` in `categorize_prompt_handler.py`, or a simple `boto3.client("s3")` call since Parse doesn't need to mock it per-file).

Error handling: `s3.put_object` failures propagate (no try/except swallow) — same principle already documented in this file for cross-account reads ("Let it raise so Step Functions retries the task with backoff"). A transient S3 error should retry via the existing `ParseAndNormalize` `Retry` clause (`Lambda.ServiceException`, `Lambda.TooManyRequestsException`) rather than silently drop content.

Retry idempotency: if `ParseAndNormalize` retries after a partial failure (e.g., record 3 of 5 already wrote its S3 object, then the Lambda times out), the retry re-runs `_resolve_content_placement` from scratch. The S3 `put_object` calls are overwrites of the same deterministic key (`prompts-content/{requestId}.json`), so a repeated write is a no-op in effect, not a duplicate.

## Changes to `layers/shared/shared/analytics_writer.py`

Remove the threshold constant and the size computation; accept the decision as a parameter.

```python
# REMOVED: _INLINE_THRESHOLD_BYTES = 4096  (moved to etl/parse_handler.py)

def write_prompt(
    self,
    user_id: str,
    prompt_record: dict,
    prompt_content: str,
    response_content: str,
    content_in_s3: bool,
    category: str = "",
) -> None:
    """PutItem for prompt metadata.

    ``content_in_s3`` reflects a placement decision already made upstream
    (by Parse). When True, the S3 object at prompts-content/{requestId}.json
    is assumed to already exist and is NOT written again here — Writer only
    records the flag on the DynamoDB item.
    """
    request_id = prompt_record["requestId"]
    timestamp = prompt_record["timestamp"]

    item = {
        "PK": f"USER#{user_id}",
        "SK": f"PROMPT#{timestamp}#{request_id}",
        "requestId": request_id,
        "modelId": prompt_record.get("modelId", ""),
        "triggerType": prompt_record.get("triggerType", ""),
        "promptLength": prompt_record.get("promptLength", 0),
        "responseLength": prompt_record.get("responseLength", 0),
        "displayName": prompt_record.get("displayName", ""),
        "userName": prompt_record.get("userName", ""),
        "region": prompt_record.get("region", ""),
        "accountId": prompt_record.get("accountId", ""),
        "conversationId": prompt_record.get("conversationId", ""),
        "utteranceId": prompt_record.get("utteranceId", ""),
        "customizationArn": prompt_record.get("customizationArn", ""),
        "contentInS3": content_in_s3,
        "category": category,
    }

    if not content_in_s3:
        item["prompt"] = prompt_content
        item["response"] = response_content

    self._table.put_item(Item=item)
```

The S3 `put_object` call that used to live here is deleted entirely — that write now happens once, in `Parse`, not twice.

## Changes to `etl/writer_handler.py`

`_write_prompt_record` currently does:

```python
prompt = record.get("prompt", "")
response = record.get("response", "")
...
writer.write_prompt(user_id, record, prompt, response, category=CATEGORY_NOT_CATEGORIZED)
```

New:

```python
prompt = record.get("prompt", "")
response = record.get("response", "")
content_in_s3 = record.get("contentInS3", False)
...
writer.write_prompt(
    user_id, record, prompt, response, content_in_s3, category=CATEGORY_NOT_CATEGORIZED
)
```

When `content_in_s3` is `True`, `prompt`/`response` on the record are already empty strings (set by Parse), so passing them through is harmless — `write_prompt` ignores them in that branch.

Backward-compatibility note: `record.get("contentInS3", False)` defaults to `False` so that any in-flight Map child execution still running against the *old* Parse output (started before this deploy) degrades to "treat as inline" rather than crashing on a missing key. Since old Parse output always has real inline content in `prompt`/`response` (the old code path never set `contentInS3`), this default is safe and matches actual behavior of those in-flight executions.

## Changes to `template.yaml`

On `ParseFunction`:

```yaml
Environment:
  Variables:
    SSM_BUCKET_NAME: /kiro-cost-analyzer/bucket-name
    SSM_SOURCE_PREFIX: /kiro-cost-analyzer/source-prefix
    SSM_PROMPTS_PREFIX: /kiro-cost-analyzer/prompts-prefix
    SSM_IDENTITY_STORE_ID: /kiro-cost-analyzer/identity-store-id
    SSM_SOURCE_BUCKET_ROLE_ARN: /kiro-cost-analyzer/source-bucket-role-arn
    SSM_IDENTITY_STORE_ROLE_ARN: /kiro-cost-analyzer/identity-store-role-arn
    USER_NAMES_TABLE: !Ref UserNamesTable
    DATA_BUCKET: !Ref DataBucket          # NEW
Policies:
  - Statement:
      - Sid: ReadSourceBucket
        ...                               # unchanged
      - Sid: WriteDataBucket              # NEW — mirrors WriterFunction's WriteDataBucket
        Effect: Allow
        Action:
          - s3:PutObject
        Resource:
          - !Sub "arn:aws:s3:::${DataBucket}/*"
      - Sid: KMSDecrypt
        ...                               # unchanged, all other statements unchanged
```

No other statement on `ParseFunction` changes. `WriterFunction`'s existing `WriteDataBucket` statement and `DATA_BUCKET` env var are untouched (Writer no longer writes `prompts-content/*` itself, but it retains the permission — harmless, and removing it is not required by any acceptance criterion; keeping it avoids a second template diff for a permission that costs nothing idle).

## Data / State Contracts

| Contract | Status |
|---|---|
| `prompts-content/{requestId}.json` key format and JSON shape | Unchanged — same key, same `{"prompt", "response"}` shape. `categorize_prompt_handler._read_prompt_from_s3` requires no change. |
| DynamoDB `PROMPT#` item shape (`contentInS3`, `prompt`, `response` presence) | Unchanged — same fields, same semantics, just decided one hop earlier. |
| `Parse` Task output shape (`records`, `key`, `fileType`, `recordCount`) | Unchanged keys. Each prompt record gains `contentInS3` (previously absent from Parse's output, present only after Writer ran). `prompt`/`response` become empty strings instead of full text when `contentInS3` is true. |
| `Writer` Task input/output shape | Unchanged keys (`recordCount`, `itemsWritten`, `durationMs`). |
| SSM `/kiro-cost-analyzer/etl-status` payload | Unchanged. |
| Dashboard `GET /prompts` API | Unchanged — reads the DynamoDB item and resolves `prompts-content/` exactly as today. |

## Size Analysis

Why 4 KB inline / S3 above that is still sufficient to stay under 256 KB per Task:

- A single `.json.gz` file corresponds to one `GenerateAssistantResponse` API call batch; observed `recordCount` in production logs for this account is consistently `1` per file (one prompt/response pair per log file).
- Worst case with the fix: 1 record × (up to 4 KB inline content + ~1 KB of other fields) ≈ 5 KB Task output. Even a pathological batch of 40 records (well above observed volume) stays at ≈ 200 KB, under the 256 KB ceiling with margin.
- Confirmed directly by the incident: `States.DataLimitExceeded` fired on a single-record file, `recordCount: 1`, per the CloudWatch evidence gathered during investigation. The fix clears both `prompt` and `response` to `""` on the returned record when content moves to S3 — the pair is stored together at `prompts-content/{requestId}.json`, mirroring the combined-object shape `AnalyticsWriter.write_prompt` originally produced.

## Test Plan

`tests/test_parse_handler.py`:
- New test: `_resolve_content_placement` writes to S3 and clears `prompt`/`response` when combined size > 4096 bytes; sets `contentInS3: True`.
- New test: `_resolve_content_placement` leaves `prompt`/`response` untouched and sets `contentInS3: False` when combined size ≤ 4096 bytes.
- New test: `parse_handler` end-to-end for `fileType: "prompt"` with a synthetic response body > 4KB — asserts the returned `records[0]["contentInS3"] is True` and `records[0]["response"] == ""`, and that the mocked S3 client received exactly one `put_object` call with the expected key and body.
- New test: verifies the returned dict's JSON-serialized size (`json.dumps(result)`) stays under 256 KB for a record with a 500 KB synthetic response (i.e., the regression the incident exhibited is directly reproduced and shown fixed).
- Existing `TestExtractPromptPathMetadata` / `TestCollectUserIds` tests are unaffected (different code paths).

`tests/test_analytics_writer.py`:
- Update the `write_prompt` call signature in all 4 existing occurrences to pass `content_in_s3` explicitly.
- New test: `content_in_s3=True` does NOT call `s3.put_object` (this is the behavior change from today, where `write_prompt` computed and wrote itself).
- New test: `content_in_s3=False` writes `prompt`/`response` inline, unchanged from today's assertion.

`tests/test_writer_handler.py`:
- Update all `records` fixtures used by prompt-record tests to include `contentInS3` (both `True` and `False` cases).
- Update assertions on `writer.write_prompt` call args across the ~19 existing references to include the new `content_in_s3` positional/keyword argument.
- New test: a record with `contentInS3` absent (simulating an in-flight old-Parse-output execution) defaults to `False` and writes inline, per the backward-compatibility note above.

## Rollout

1. Deploy via `make deploy` (SAM changeset touches `ParseFunction` IAM/env, `WriterFunction` code only — no DynamoDB/Step Functions state graph change, so this is a Lambda-only changeset plus one IAM policy attachment).
2. Manually trigger the ETL once after deploy (Settings → "Run ETL" or `aws stepfunctions start-execution`) against the actual backlog that has been failing since 2026-08-21 — those files were never marked in `ProcessedFilesTable`, so this run reprocesses them automatically (Requirement 5.1).
3. Verify: state machine `SUCCEEDED`, SSM `status: "SUCCESS"`, `filesFailed: 0`. Confirm via `aws stepfunctions get-execution-history` that no `States.DataLimitExceeded` recurs on the previously-failing files.
4. Spot-check one recovered record with a large response in DynamoDB: `contentInS3: true`, `prompt`/`response` absent from the item, and `prompts-content/{requestId}.json` present in the data bucket with the full text. Confirm the dashboard's prompt detail view still renders it (exercises `categorize_prompt_handler`/`prompts_handler` unchanged path).
5. No feature flag / gradual rollout needed — this is a bug fix with no behavior change for any record that was already working (≤4KB combined content keeps flowing inline exactly as before).
