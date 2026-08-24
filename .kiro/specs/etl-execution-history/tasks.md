# Tasks — ETL Execution History

Implementation plan. Tasks ordered so each checkpoint leaves the system deployable. Optional tests marked `*`.

Requirements referenced per task using `_Requirements: N.M_`.

---

## Checkpoint 1 — Wording

- [x] **1.1** Reword `settings.success.etlTriggered` in `en.json` and `pt-BR.json` to say the execution started and is in progress. Remove "disparado" from the pt-BR value.
  - _Requirements: 1.1, 1.2_

- [x] **1.2** Reword `settings.etl.noExecution` in both catalogs to use the same "start" vocabulary.
  - _Requirements: 1.3_

**Validation checkpoint 1**: `cd frontend && npm run check:locales` passes (key parity, sorting, non-empty values).

---

## Checkpoint 2 — Persist per-execution counters

- [x] **2.1** Add `_write_execution_record` to `etl/record_status_handler.py`: derive the execution name from the ARN, write `PK=ETL_STATUS` / `SK=EXEC#{name}` with `status`, `filesProcessed`, `recordsWritten`, `timestamp`, `executionArn`.
  - _Requirements: 2.1, 2.2, 2.3_

- [x] **2.2** Make the helper non-raising: skip on absent/malformed ARN, swallow and log any write failure. Call it after the SSM write so the aggregate payload is unaffected.
  - _Requirements: 2.4, 2.5, 2.6_

- [x] **2.3** In `template.yaml`, add `ANALYTICS_TABLE` to `RecordStatusFunction` environment and a `dynamodb:PutItem` statement scoped to the analytics table.
  - _Requirements: 5.2_

- [x] **2.4** Extend `tests/test_record_status_handler.py`: record written on success, ARN missing → skipped, `put_item` raising → handler still returns normally, SSM payload unchanged.
  - _Requirements: 2.1, 2.4, 2.5, 2.6_

- [x] **2.5*** Hypothesis property: `_write_execution_record` never raises for arbitrary ARNs and counters (P5).
  - _Requirements: 2.4, 2.5_

**Validation checkpoint 2**: `python -m pytest tests/test_record_status_handler.py -v` passes.

---

## Checkpoint 3 — Execution history endpoint

- [x] **3.1** Create `backend/handlers/etl_executions_handler.py` with `handle_etl_executions(query_params, sfn_client=None, dynamodb_resource=None)`: parse and clamp `days`, page `ListExecutions` stopping at the cutoff, single `Query` on `PK=ETL_STATUS` for enrichment, derive `elapsedSeconds`.
  - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] **3.2** Return an empty list when `STATE_MACHINE_ARN` is unset; let `ClientError` propagate.
  - _Requirements: 3.9, 3.10_

- [x] **3.3** Route `GET /api/etl/executions` in `backend/handler.py` behind the `Admins` guard.
  - _Requirements: 3.1_

- [x] **3.4** In `template.yaml`, add `states:ListExecutions` on the ETL state machine to the `BackendFunction` `StepFunctionsAccess` statement.
  - _Requirements: 5.1_

- [x] **3.5** Create `tests/test_etl_executions_handler.py`: happy path with enrichment, running execution, execution with no record, window filtering, missing ARN, `days` clamping, English-only response fields.
  - _Requirements: 3.2–3.11_

- [x] **3.6** Add a router test asserting a non-admin caller gets 403 on the new route.
  - _Requirements: 3.1_

- [x] **3.7*** Hypothesis properties P1 (days totality), P2 (window bound), P3 (elapsed nullity), P4 (no invented counters).
  - _Requirements: 3.3, 3.4, 3.6, 3.7_

**Validation checkpoint 3**: `python -m pytest tests/test_etl_executions_handler.py tests/test_backend_handler.py -v` passes.

---

## Checkpoint 4 — Frontend history table

- [x] **4.1** Add `EtlExecution` and `EtlExecutionsResponse` to `frontend/src/types/index.ts`.
  - _Requirements: 4.2_

- [x] **4.2** Add the `settings.etl.history.*` keys to both catalogs in alphabetical position: title, column headers, loading text, empty title/description, and the five status labels.
  - _Requirements: 4.8, 4.11, 1.4_

- [x] **4.3** Create `frontend/src/components/EtlExecutionHistory.tsx`: Cloudscape `Table` in a `Container`, five columns in the required order, loading and empty states, em dash for unknown values, locale-aware formatters, `StatusIndicator` per the status map, and the local total `formatElapsed`.
  - _Requirements: 4.1, 4.2, 4.5, 4.6, 4.7, 4.8, 4.9, 4.11_

- [x] **4.4** Wire it into `SettingsPage.tsx` below the ETL status card: independent fetch effect for a 5-day window, and a reload after a successful manual run.
  - _Requirements: 4.1, 4.3, 4.4, 4.10_

- [x] **4.5** Add `frontend/src/components/__tests__/EtlExecutionHistory.test.tsx`: renders rows, em dash for a running execution and for missing counters, empty state, status indicator mapping.
  - _Requirements: 4.5, 4.6, 4.8_

- [x] **4.6*** fast-check property: `formatElapsed` is total and monotonic (P6).
  - _Requirements: 4.7_

**Validation checkpoint 4**: `cd frontend && npm run test && npm run build` pass (`check:locales` runs inside `build`).

---

## Checkpoint 5 — Ship

- [x] **5.1** Full gates: `python -m pytest tests/ -q`, `cd frontend && npm run lint && npm run test && npm run build`.

- [x] **5.2** Add a `docs/changelog.md` entry under `## Unreleased`.
  - _Requirements: —_

- [x] **5.3** Deploy with `make deploy AWS_PROFILE=kca` after confirming the target account and region via STS.
  - _Requirements: 5.3_

- [x] **5.4** Verify in the deployed stack: the new endpoint returns executions, and the ETL tab renders the history table.
  - _Requirements: 3.1, 4.1_
