# Design — ETL Execution History

## 1. Where the data comes from

No single store holds everything the history table needs, so the design joins two sources that each hold half of it.

| Field | Source | Why |
|---|---|---|
| execution name, start date, stop date, status | Step Functions `ListExecutions` | The state machine is `STANDARD`, so Step Functions retains 90 days of execution history. This is authoritative for timing and outcome, and it is available **retroactively** — the history table has content the moment the feature deploys. |
| files processed, records written | DynamoDB `PK=ETL_STATUS`, `SK=EXEC#{executionName}` | Step Functions does not know these numbers; they are computed by the `RecordStatus` Lambda from the Distributed Map manifest. |

Elapsed time is derived (`stopDate - startDate`), not stored.

The alternative — persisting a complete history record per run and reading only DynamoDB — was rejected because it would leave the table empty until the first run after deploy, and because it would duplicate timing data that Step Functions already keeps correctly, including for runs that crashed before reaching `RecordStatus`.

### 1.1 The gap being closed

Today the `EXEC#` item is written **only** by the `RecordStatusNoFiles` state, via a direct Step Functions `dynamodb:putItem` integration on the "zero new files" path. The `RecordStatus` Lambda — the path taken whenever files *were* processed — writes only to SSM. So the one partition that looks like an execution history contains exclusively the runs that did nothing.

Requirement 2 closes that asymmetry by having the Lambda write the same item shape. After deploy, both paths produce an `EXEC#` record, and the two counter columns fill in for every new run.

Executions that predate the deploy have no record. They still appear in the table — with real dates, elapsed time and status from Step Functions — and their counter cells render as unknown. Requirement 3.7 is why `filesProcessed` is `null` rather than `0`: a run that legitimately processed zero files must not look identical to a run whose counters were never captured.

## 2. Backend

### 2.1 New handler — `backend/handlers/etl_executions_handler.py`

```python
def handle_etl_executions(query_params: dict, sfn_client=None, dynamodb_resource=None) -> dict
```

Returns:

```json
{
  "days": 5,
  "executions": [
    {
      "executionName": "a1b2c3d4-...",
      "startDate": "2026-08-24T23:59:03.412000+00:00",
      "stopDate": "2026-08-25T00:04:41.887000+00:00",
      "elapsedSeconds": 338,
      "status": "SUCCEEDED",
      "filesProcessed": 118,
      "recordsWritten": 4217
    }
  ]
}
```

Algorithm:

1. Resolve `STATE_MACHINE_ARN`. Empty → return `{"days": n, "executions": []}` (Req 3.9).
2. Parse `days`: integer, default 5, clamped to 1..30; a non-numeric value falls back to the default (Req 3.2, 3.3).
3. Compute `cutoff = now(UTC) - days`.
4. Page `list_executions(stateMachineArn=...)` with a paginator. Step Functions returns executions **most recent first**, so paging stops at the first execution whose `startDate` is older than the cutoff — the whole 90-day history is never walked (Req 3.4).
5. One `Query` on `PK=ETL_STATUS` builds a `{executionName: record}` map, then executions are enriched from it in memory (Req 3.8). The partition holds one small item per run, so a single unfiltered query is cheaper and simpler than a filtered one and stays correct as the window changes.
6. `elapsedSeconds` = `int((stopDate - startDate).total_seconds())` when `stopDate` is present, else `None` (Req 3.6).

`ClientError` is not caught here: it propagates to the router's existing throttling/error mapping (Req 3.10). Status values pass through as Step Functions slugs — `SUCCEEDED`, `FAILED`, `RUNNING`, `ABORTED`, `TIMED_OUT` — which the frontend maps to translated labels (Req 3.11).

### 2.2 Routing — `backend/handler.py`

`GET /api/etl/executions` behind the existing `_is_admin(claims)` guard, alongside `POST /api/etl/trigger`.

### 2.3 IAM and environment

`BackendFunction` gains `states:ListExecutions` on `!Ref EtlStateMachine`, added to the existing `StepFunctionsAccess` statement (Req 5.1). `ANALYTICS_TABLE` and the DynamoDB read policy are already present.

`RecordStatusFunction` gains `ANALYTICS_TABLE` as an environment variable, a `dynamodb:PutItem` statement scoped to `!GetAtt AnalyticsTable.Arn`, and the `KMSForDynamoDB` statement (`kms:Decrypt`, `kms:GenerateDataKey`, `kms:DescribeKey` on `KCAEncryptionKey`) that every other writer to that table already carries (Req 5.2). The analytics table is encrypted with a customer-managed key, so `PutItem` alone is refused with a KMS `AccessDeniedException`.

## 3. ETL change — `etl/record_status_handler.py`

A new private helper, called after the SSM write succeeds:

```python
def _write_execution_record(execution_id, status, files_processed, records_written, logger, dynamodb_resource=None) -> None
```

- Execution name = `execution_id.rsplit(":", 1)[-1]`. Absent ARN, or an ARN with no `:`, means no name can be derived: log and return (Req 2.3, 2.4).
- Item shape matches what `RecordStatusNoFiles` already writes, so both paths produce one comparable record: `PK`, `SK`, `status`, `filesProcessed`, `recordsWritten`, `timestamp`, `executionArn` (Req 2.2).
- The whole body is wrapped in `try/except Exception` that logs and returns (Req 2.5). This is deliberate, and it is the one place in this ETL where an exception is swallowed rather than re-raised: the ETL's job is to load analytics data, and it has already succeeded by this point. Failing the run because a history row could not be written would turn a cosmetic problem into a data-freshness incident. The failure is still visible in the structured logs.

Ordering matters: the SSM write stays first and unchanged, so the aggregate status card cannot regress (Req 2.6).

## 4. Frontend

### 4.1 New component — `frontend/src/components/EtlExecutionHistory.tsx`

A Cloudscape `Table` in a `Container`, following the repos-table pattern in `GitSettingsPage`.

| Column | Cell |
|---|---|
| Start date | `formatDateTime(startDate)` |
| End date | `formatDateTime(stopDate)`, em dash when null |
| Elapsed | `formatElapsed(elapsedSeconds)`, em dash when null |
| Files | `formatNumber(filesProcessed)`, em dash when null |
| Status | `<StatusIndicator>` + translated label |

`formatElapsed` is a local pure function producing `42s`, `5m 38s`, `1h 04m`. The units are symbols rather than words, so the result needs no catalog entry and reads the same in both locales (Req 4.7). It is a total function: negative or non-finite input yields an em dash.

Status mapping (Req 4.8):

| Step Functions status | Indicator | Label key |
|---|---|---|
| `SUCCEEDED` | `success` | `settings.etl.history.status.succeeded` |
| `FAILED` | `error` | `settings.etl.history.status.failed` |
| `RUNNING` | `in-progress` | `settings.etl.history.status.running` |
| `ABORTED` | `stopped` | `settings.etl.history.status.aborted` |
| `TIMED_OUT` | `warning` | `settings.etl.history.status.timedOut` |
| anything else | `pending` | raw value |

The unknown branch keeps the component total against a status Step Functions might add later.

### 4.2 `SettingsPage.tsx`

The history fetch is a separate `useEffect` from the config fetch, so a slow or failing `ListExecutions` call cannot delay or break the status card (Req 4.4). `handleTriggerEtl` calls the history reload on success (Req 4.10).

### 4.3 Types — `frontend/src/types/index.ts`

```ts
export interface EtlExecution {
  executionName: string;
  startDate: string | null;
  stopDate: string | null;
  elapsedSeconds: number | null;
  status: string;
  filesProcessed: number | null;
  recordsWritten: number | null;
}

export interface EtlExecutionsResponse {
  days: number;
  executions: EtlExecution[];
}
```

### 4.4 Catalogs

New `settings.etl.history.*` keys in both catalogs, inserted in alphabetical position. `settings.success.etlTriggered` and `settings.etl.noExecution` are reworded to "start" vocabulary in both locales (Req 1.1–1.3).

## 5. Correctness properties

| # | Property | Validated by |
|---|---|---|
| P1 | `days` parsing is total: any string, absent, or malformed value yields an integer in 1..30. | Hypothesis over arbitrary text |
| P2 | Every execution returned has `startDate >= cutoff`. | Hypothesis over generated execution lists |
| P3 | `elapsedSeconds` is `None` exactly when `stopDate` is `None`, and is otherwise non-negative. | Hypothesis |
| P4 | Enrichment never invents counters: a returned execution has non-null counters only if a matching `EXEC#` record existed. | Unit + Hypothesis |
| P5 | `_write_execution_record` never raises, for any input. | Hypothesis over arbitrary ARNs and counters |
| P6 | `formatElapsed` is total and monotonic in its input. | fast-check |
| P7 | Catalog key parity and alphabetical order hold. | `scripts/check-locales.ts` in the build |

## 6. Out of scope

- Backfilling counters for executions that ran before this deploy. Step Functions still supplies their timing and status; the counters stay unknown.
- Drilling into a single execution's per-file errors. The aggregate card already surfaces the latest run's error list.
- A TTL on `EXEC#` items. One small item per run is a negligible growth rate; pruning can be added if it ever matters.
