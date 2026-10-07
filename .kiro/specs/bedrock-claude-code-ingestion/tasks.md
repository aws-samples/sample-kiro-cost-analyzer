# Tasks — Claude Code on Amazon Bedrock Ingestion

This is the implementation plan for issue #56. Checkpoints follow the agreed order, and each one can be validated on its own. Optional tasks are marked `*`. The feature stays disabled (`BedrockIngestionEnabled=false`) until task 6.9, which runs only after checkpoints 0–5 and tasks 6.1–6.8 are merged and deployed. Property tests run at least 100 examples (`.kiro/steering/development-standards.md` §7.2).

Checkpoints 3–4 are verified with moto and explicit environment variables. The template wiring they rely on in a real deployment (`ANALYTICS_TABLE`, `SSM_BEDROCK_INGESTION`, the conditional IAM statements) lands in task 6.1. This is safe because discovery stays disabled until 6.9.

---

## Checkpoint 0 — Spike and sanitized fixtures

- [ ] **0.1** In a sandbox Claude Code account, enable Bedrock model invocation logging to S3 in one Region with **every body-delivery flag off**. Run Claude Code with an IdC profile (`aws configure sso`, `CLAUDE_CODE_USE_BEDROCK=1`). First resolve spike item S3 (gating, design §22): are records with token counts and identity delivered in this mode? If not, switch to Text delivery under a lifecycle-managed prefix, using synthetic prompts only. Capture records for:
  - `InvokeModelWithResponseStream`;
  - a non-stream `InvokeModel`;
  - an AIP `modelId`;
  - a `us.` and a `global.` system profile;
  - non-zero cache read and cache write;
  - a non-null `errorCode`, including a throttled request;
  - a client-cancelled stream (Esc in Claude Code).
  - _Requirements: 1.1, 1.3, 1.6_

- [ ] **0.2** Record the S3 layout as a listing (key names only): full key format, the `permission-check` object and the `data/` body-object key name. Never download or commit body-object content. Measure records per file, file size distribution, delivery latency, files per day per Region and the maximum distinct `(user, day, region, modelRef)` keys per file (S12). Check whether any `requestId` appears in more than one object over the capture window (S11).
  - _Requirements: 1.1, 1.3, 4.8, 10.6_

- [ ] **0.3** Capture `bedrock:GetInferenceProfile` responses for AIPs created from a foundation model, a `us.` profile and a `global.` profile. Check whether the global AIP lists a Region-less foundation-model ARN (`arn:aws:bedrock:::foundation-model/{id}`). Decide the AIP scope rule (design S5, D19, Q2).
  - _Requirements: 1.4, 9.3_

- [ ] **0.4** Confirm that the session name equals the IdC `UserName`, including case, for every identity source available (IdC directory, external IdP with SCIM, Active Directory). Check `identitystore:GetUserId` on the `userName` path: case sensitivity, the not-found error shape (`ResourceType`, `Reason`), the error for a wrong Region and for a wrong store ID, and user names longer than 64 characters (design S4). Record the IdC role-name suffix format (S10).
  - _Requirements: 1.3, 1.7, 6.1, 6.4_

- [ ] **0.5** Sanitize the captures: replace account IDs with `111111111111`/`222222222222`, use fake user names, request IDs and ARNs, and drop every body field. Commit them under `tests/fixtures/bedrock_invocation_logs/` (`.json.gz`, a key-listing fixture, plus a `README.md` with provenance). Add `tests/test_bedrock_fixture_hygiene.py`, which rejects 12-digit IDs outside the placeholder allowlist and any `inputBodyJson`/`outputBodyJson` key.
  - _Requirements: 1.1, 1.2_

- [ ] **0.6** Capture the list prices for the Claude models Claude Code uses, for the `in-region`, `geo` and `global` scopes, including cache read/write (5m and 1h) and long-context rates (design S7, S9). Record the source URL and date.
  - _Requirements: 1.5, 8.2_

- [ ] **0.7** Update `design.md`: confirmed field paths and timestamp format (§5.3), key regex (§5.1), IdC role regex (§7), geo-prefix list (§10.2), AIP scope rule (§10.3), error and cancelled-record shape (amend Requirement 4.9 if they carry billable tokens), the S3 decision, the S11 result (cross-file de-duplication or documented limitation) and the S12 volumes. Mark S1–S12 resolved or amended, and close or keep Q2 and Q3.
  - _Requirements: 1.3, 1.4, 1.6, 1.7_

**Validation checkpoint 0.** Fixtures are committed and the hygiene test passes. Every spike item in design §22 is marked confirmed or amended, and S3 is decided before checkpoint 2 starts. No adapter code exists yet.

---

## Checkpoint 1 — Seam plumbing (no Bedrock behavior)

- [ ] **1.0** Golden ETL baselines. From the pre-feature commit (`fa550e7`), generate and commit golden outputs for Kiro inputs: ListFiles results, Parse outputs, Writer DynamoDB items, RecordStatus summaries and `EXEC#` items. Commit them before any handler is changed.
  - _Requirements: 11.1, 21.6_

- [ ] **1.1** Extend `etl/sources/base.py`:
  - `SourceAccess` and `DiscoveryContext` (`processed_keys`, `now`, `clients`, `cursors`, `analytics_table`);
  - `ParsedSource.counters` (default empty) and `ParsedSource.context` (default `None`);
  - optional protocol members `source_access`, `enabled` and the `list_files(..., *, context=None)` keyword;
  - class attributes `dispatch_once_per_execution`, `failure_isolated`, `retry_ledger_pk` and `spill_records`, with Kiro-preserving defaults.
  
  Update the Kiro adapters to accept `context`, return `None` from `source_access` and return `True` from `enabled`.
  - _Requirements: 2.3, 2.4, 12.1_

- [ ] **1.2** Add `ClientFactory` to `etl/sts_session.py`. It provides `s3(role_arn, region)`, `bedrock(role_arn, region)` and a strict `identitystore(region)` (no `None` fallback, explicit `region_name`), with a per-container cache, refresh before credential expiry and adaptive retries. AssumeRole errors raise. Existing functions stay unchanged.
  - _Requirements: 2.2, 2.3, 2.6, 6.8_

- [ ] **1.3** Add `/kiro-cost-analyzer/bedrock-ingestion` parsing to `etl/config.py` (`SSM_BEDROCK_INGESTION`). It produces `BedrockIngestionConfig` and `LogLocation`, handles the `NONE` sentinel, zips the parallel lists, validates them (lengths, dates, Regions, role ARN, `identityStoreRegion`) and reports `config_error`. Add a test that the `GetParameters` name count is ≤ 10.
  - _Requirements: 2.1, 18.1_

- [ ] **1.4** `etl/list_handler.py`:
  - load processed keys before discovery and pass `DiscoveryContext`, including `cursors` read from `event.listResult.cursors` and `ANALYTICS_TABLE`;
  - add the serialized-size batch budget;
  - emit `cursors` for `dispatch_once_per_execution` adapters only when non-empty;
  - emit an adapter count field only when `adapter.enabled(cfg)`.
  
  No source-specific conditional is added.
  - _Requirements: 3.7, 3.8, 3.10, 11.4_

- [ ] **1.5** Add `layers/shared/shared/pseudo_users.py` (`build_pseudo_user_id`, `is_pseudo_user`). Logic only; the property tests come in 2.3.
  - _Requirements: 7.1, 7.2_

- [ ] **1.6** `etl/parse_handler.py`:
  - select the client and bucket through `adapter.source_access`, building the Kiro client only on the Kiro branch;
  - return `counters` only when non-empty;
  - skip pseudo-users in `_collect_user_ids` (uses 1.5);
  - for `spill_records` adapters, spill the batch to `DATA_BUCKET/etl-spill/` above 200 KB and return a single `recordsRef` record.
  - _Requirements: 2.3, 2.4, 7.5, 10.6, 11.4, 12.1_

- [ ] **1.7** `etl/record_status_handler.py`:
  - sum `parseResult.counters` and `writeResult.alreadyApplied` per source type, count `filesFailed` per source type (from the failed child's `Input.fileType`), and persist `sourceCounters` on `EXEC#` only when non-empty;
  - failure isolation: the returned `filesFailed` counts only non-isolated adapters plus manifest read failures; isolated failures set `status=ERROR` and are listed after Kiro errors;
  - retry ledger: upsert failed keys of adapters with `retry_ledger_pk` (`ADD attempts`, timestamps, error class), swallowing and logging write errors.
  - _Requirements: 3.9, 11.5, 12.2_

- [ ] **1.8** Kiro invariance and isolation tests. Extend `tests/test_source_adapter_equivalence.py`, `test_list_handler.py`, `test_parse_handler.py` and `test_record_status_handler.py` with assertions that List, Parse and RecordStatus outputs and the `EXEC#` item are byte-identical to the baselines committed in 1.0 for Kiro inputs (P1). Add P19 (failure isolation) and a `test_record_status_state_machine.py` case showing that a Bedrock-only failure leaves `filesFailed = 0`, so the definition routes to `ListUncategorizedPrompts`.
  - _Requirements: 11.1, 11.2, 11.4, 11.5, 21.1_

**Validation checkpoint 1.** The full backend suite passes without a weakened assertion. Golden Kiro outputs are identical to the committed baselines. `sam build` succeeds.

---

## Checkpoint 2 — Pure functions with property tests

- [ ] **2.1** `etl/sources/bedrock/keys.py`: qualified-key encode/decode, the claim predicate (layout regex, `data` segment, `permission-check`), partition-date extraction, the reader-account base prefix, and the candidate computation (watermark window with `overlapDays = 2` and the sliding backfill default, ledger keys, processed-key filter, sorting and cursor filter). Tests: P2 (disjointness against the Kiro claims) and P13 (including a failed key after the watermark passes `D + 2`, no key emitted twice across `hasMore` iterations, and off→on after N days).
  - _Requirements: 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.9, 3.10_

- [ ] **2.2** `etl/sources/bedrock/log_parser.py`: gzip NDJSON parsing into `RawInvocation` using only the allowlisted paths. It enforces the required fields (including `accountId` and `region`), counts malformed records (including timestamps more than 15 minutes in the future) and absent cache fields, treats offset-less timestamps as UTC, keeps absent token counts as `None`, and validates and caps token values. Tests: P3, P4 (sentinel in bodies), plus fixture-driven assertions on every checkpoint 0 fixture.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.11, 21.2_

- [ ] **2.3** `etl/sources/bedrock/principal.py` and `inclusion.py`: ARN parsing, the IdC role regex with the suffix format from task 0.4 (fixture-driven assertion that the captured principal is IdC), the outcome evaluation with reasons (including `foreignAccount` first), permission-set glob matching that ignores the suffix, and the AIP allowlist on the raw `modelId`. Tests: P5 and P14. Also property-test `pseudo_users` (P9).
  - _Requirements: 2.8, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 7.1, 7.2_

- [ ] **2.4** `etl/sources/bedrock/model_ref.py`: `classify_model_id` for base models, system profiles (geo and global), AIPs, provisioned models and unknown IDs; an ARN parser that accepts empty Region and account fields; the `modelRef.key` derivation and the `modelRefSk` encoding. Properties: it is total and deterministic, every system-profile ID maps to its stripped base, and P18.
  - _Requirements: 9.1, 9.2, 10.3_

- [ ] **2.5** `layers/shared/shared/bedrock_pricing.py`: `validate_bedrock_pricing` (including a duplicate `effectiveFrom`), `select_version` (returning `None` when nothing is effective), `lookup_entry` and `price_invocation` (Decimal, long-context flag, TTL assumption), plus `quantize_usd`. Tests: P7, P8, P15 and P17.
  - _Requirements: 8.2, 8.3, 8.6, 8.7, 9.5, 9.6, 9.7, 9.8, 10.8_

- [ ] **2.6** `etl/sources/bedrock/aggregate.py`: `requestId` dedupe, the operation filter, the failure split, `tokenCountsAbsent` handling and aggregation by `(userId, date, region, modelRefSk)` with counters and long-context subsets. Test: P6, plus both conservation identities of design §15.
  - _Requirements: 4.7, 4.8, 4.9, 4.10, 10.1, 10.2, 12.3_

- [ ]* **2.7** Add a mutation-style test: injecting a deliberate off-by-one into each pure function makes at least one property fail.
  - _Requirements: 21.1_

**Validation checkpoint 2.** Every property test (P2–P9, P13–P15, P17, P18) passes with at least 100 examples. The pure modules import no `boto3`.

---

## Checkpoint 3 — Adapter and writer

- [ ] **3.1** Define the service interfaces and test fakes in `etl/sources/bedrock/services.py`: `IdentityResolver`, `ProfileResolver`, `PriceBook` and `DiscoveryState` (retry ledger, seed hook and discovery status).
  - _Requirements: 3.9, 3.11, 6.1, 9.3, 9.5_

- [ ] **3.2** Implement `etl/sources/bedrock_invocation_log.py`: identity attributes (design §5 table); `enabled`; `list_files` (reader account, seed hook, ledger read and cleanup, per-location error guard, watermark, day partitions, qualified keys, sorted candidates after the cursor, discovery status); `claim` (key shape only); `source_access` (raises for an unknown location); `read`, `parse` and `normalize` (pipeline of design §5.4), with injected services. Register it last in `REGISTRY`.
  - _Requirements: 2.2, 2.5, 2.8, 2.9, 3.1–3.6, 3.9–3.11, 4.1–4.11, 5.1–5.6, 6.5, 9.4, 9.8, 9.9, 10.1, 19.1, 19.4_

- [ ] **3.3** Add the `token_usage` dispatch to `etl/writer_handler.py`, implemented by `_write_token_usage_records`. It resolves a spill reference, then applies records through `apply_token_usage` and `apply_global_token_usage` (two-item transactions with `BEDROCK#APPLIED#{sourceFile}` markers, Decimal-from-string cost) and `upsert_client_activity_summary` (only for non-pseudo records with `invocations > 0`), all added to `AnalyticsWriter`.
  - _Requirements: 9.7, 10.3, 10.4, 10.5, 10.6, 16.7_

- [ ] **3.4** Adapter tests: fixture-driven end-to-end parse+normalize with fakes; registry order and unknown-type tests; the disabled-flag and in-flight behavior (configured location → processed; location removed → raises); a location whose listing raises (other locations and the Kiro `newFiles` unchanged, status recorded); ledger keys listed beyond the watermark and removed once processed; the cursor across `hasMore` iterations; a two-account fixture (foreign records dropped as `foreignAccount`, a foreign AIP unpriced as `aipForeignAccount`).
  - _Requirements: 2.8, 2.9, 3.8, 3.9, 3.10, 19.3, 19.4, 21.2_

- [ ] **3.5** Writer tests (moto):
  - P10 idempotency (double apply, partial-then-full);
  - the documented double-count window after a re-parse with a changed identity (Requirement 10.7);
  - aggregate items do not grow across files;
  - Kiro items untouched by Claude Code writes;
  - no `STATS#DAILY#`, `STATS#CLIENT#`, `STATS#MODEL#` or `ACTIVITY_SUMMARY` writes;
  - pseudo-users and failed-only aggregates write no activity summary;
  - spill-reference resolution.
  - _Requirements: 7.5, 10.4, 10.5, 10.6, 10.7, 16.7, 21.3_

- [ ] **3.6** Payload and timing tests:
  - a 5,000-invocation, 50-user, 3-model file produces inline Parse output under 64 KB;
  - a file with 1,000 distinct aggregate keys takes the spill path and the inline output stays under 200 KB (P11);
  - a ListFiles batch of qualified keys stays under the byte budget;
  - the worst-case file parses and normalizes with fakes in under 10 s.
  - _Requirements: 3.7, 10.6_

**Validation checkpoint 3.** The adapter, writer and handler suites pass. P1 still holds with the adapter registered and disabled.

---

## Checkpoint 4 — Identity and pricing configuration

- [ ] **4.1** Implement the real `IdentityResolver` in `etl/sources/bedrock/identity.py`:
  - once-per-container preflight (`ListUsers`, `MaxResults=1`) through `ClientFactory.identitystore(region)`;
  - container cache (including negative results), then `GetUserId` on the `userName` path only; no persistent cache;
  - classification: `ResourceNotFoundException` with `ResourceType=USER` and no `Reason` → `NotFound` → pseudo-user; every other error raises;
  - log unresolved names once.
  
  Test it with a botocore `Stubber`: USER not-found, IDENTITY_STORE not-found, a `Reason`, AccessDenied, throttling, a failed preflight and a wrong Region.
  - _Requirements: 6.1, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 12.5_

- [ ] **4.2** Implement the real `ProfileResolver` in `etl/sources/bedrock/profiles.py`. It returns `aipForeignAccount` without an API call when the ARN's account differs from the reader account; otherwise it calls `GetInferenceProfile` through `ClientFactory.bedrock(role, region-from-ARN)` with a container cache, applies the scope rule from task 0.3, treats `ResourceNotFoundException` and `ValidationException` as `aipUnresolved`, and raises on any other error. Test it with a `Stubber`.
  - _Requirements: 9.3, 9.4_

- [ ] **4.3** Implement the real `PriceBook`, which runs one `Query` of `CONFIG#BEDROCK_PRICING` per invocation of Parse and yields `noPriceVersion` when nothing is effective. Add the seed file `layers/shared/shared/bedrock_price_seed.json` with the prices from task 0.6. Implement the real `DiscoveryState` in the new `etl/sources/bedrock/discovery_state.py`: the retry-ledger `Query`/`DeleteItem` on `BEDROCK#RETRY`, the `BEDROCK#DISCOVERY` status `PutItem` (design §5.2 step 6), and the seed hook used by the adapter's `list_files` (not `list_handler.py`): a conditional `PutItem` on the fixed key `VERSION#1970-01-01#seed`, only when enabled. Errors are logged and swallowed per design §5.2. Moto tests: "an admin version exists but no seed", ledger cleanup of processed keys, and a status write failure that does not fail discovery.
  - _Requirements: 2.9, 3.9, 3.11, 8.1, 8.4, 9.5, 9.8, 9.9_

- [ ] **4.4** Add the new backend `backend/handlers/bedrock_pricing_handler.py` and the repository accessors (`list_bedrock_price_versions`, `put_bedrock_price_version`, `delete_bedrock_price_version`):
  - `GET /api/config/bedrock-pricing`;
  - `POST /api/config/bedrock-pricing/versions`;
  - `DELETE /api/config/bedrock-pricing/versions/{versionId}`.
  
  They enforce Admins-only access, `effectiveFrom > today (UTC)`, a unique `effectiveFrom`, and 409 when deleting an effective version. Wire the routes in `backend/handler.py`, add the SAM API events and add 403 tests.
  - _Requirements: 8.5, 8.6, 8.7, 8.8, 21.4_

- [ ] **4.5** Frontend `BedrockPricingPanel` in `SettingsPage`:
  - version list and create form (minimum effective date = tomorrow, UTC; an existing `effectiveFrom` is rejected);
  - delete for future versions;
  - forward-only notice and the "newer bundled table" notice.
  
  Add types, locale keys in both catalogs, and Vitest tests.
  - _Requirements: 8.5, 8.6, 17.5, 17.6, 17.7_

- [ ] **4.6** Wire the real services into the adapter factory. Integration test: fixture file → ListFiles (moto S3 and DynamoDB: seed, ledger, status) → Parse (stubbed identitystore/bedrock) → Writer → expected items. It covers a mixed Kiro + Claude Code user under the same `USER#`, and a failed file that is retried from the ledger on the next run.
  - _Requirements: 3.9, 6.2, 21.3_

**Validation checkpoint 4.** The identity, pricing, backend-route and frontend pricing tests pass, and P8 holds against the real repository code path.

---

## Checkpoint 5 — Read model, coexistence and frontend

- [ ] **5.0** Golden API baselines. From the pre-feature commit (`fa550e7`), generate and commit golden JSON for a Kiro-only table across usage (list and single-user), account, details, export (CSV and JSON), engagement, engagement-thresholds PUT and config. Commit them before any backend handler is changed.
  - _Requirements: 11.1, 21.6_

- [ ] **5.1** Repository:
  - `scan_user_stats(include_claude_code=False, client_type=None)` with a single-scan union aggregation, the `#￿` end bound for token items, `estimatedCostUsdExact` computed before `_convert_decimals`, the `client_type` filter and ordering before summary and pagination, and `claude_code_summary` computed in the repository next to `aggregate_user_summary`;
  - `get_user_token_usage`, `get_global_token_usage`, `has_claude_code_data`, `scan_claude_code_token_usage`, `scan_client_activity_summaries` and `get_bedrock_discovery_status`;
  - pure helpers in `backend/handlers/claude_code_read_model.py`.
  
  Tests: P20, end-date-inclusive tests for the scan, the user Query and the GLOBAL Query, and the 500 × 90 × 3 aggregation benchmark.
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.8, 14.5, 15.1_

- [ ] **5.2** `GET /api/usage` (list and single-user): the `includeClaudeCode` opt-in; `_format_user` pass-through of `claudeCode`, `sources`, `isPseudoUser` and `pseudo*`; the repository summary; the `clientType` filter; the omission rule; pseudo rows admin-only; the single-user early return only when both Kiro stats and token items are empty. Tests: 60 Kiro users plus CC-only and pseudo rows (filter ordering, population-wide summary), a CC-only non-admin self-view, and a request without the flag that matches the baseline.
  - _Requirements: 7.3, 7.4, 7.6, 11.3, 13.1–13.7_

- [ ] **5.3** `GET /api/usage/account`: add the `claudeCode` block from `GLOBAL` items (totals, timeline, model breakdown with USD percentage, unattributed cost, price versions). Existing fields stay unchanged.
  - _Requirements: 13.8, 14.1, 14.2_

- [ ] **5.4** `GET /api/usage/{userId}/details`: add the `claudeCode` block and the extended 404 rule.
  - _Requirements: 14.3_

- [ ] **5.5** Export: request `includeClaudeCode=true` when Claude Code is visible; append the conditional CSV columns from `estimatedCostUsdExact`; the JSON export carries the API rows. Existing columns stay unchanged. Golden tests for both formats.
  - _Requirements: 14.4, 14.5_

- [ ] **5.6** Engagement:
  - keep the Kiro path unchanged, with `parse_thresholds`/`validate_thresholds` ignoring the `claudeCode` key;
  - add `validate_claude_code_thresholds`/`parse_claude_code_thresholds` and merge-on-PUT for the `claudeCode` block;
  - add `segmentationByClient.CLAUDE_CODE` (`classify_claude_code_user`, idle/dormant from `ACTIVITY_SUMMARY#CLAUDE_CODE`, pseudo-users excluded) from `scan_claude_code_token_usage`.
  
  Tests: property tests for the classifier, mirroring the existing segmentation properties; an invalid `claudeCode` block leaves Kiro thresholds unchanged; a Kiro-only PUT preserves `claudeCode`; a failed-only user becomes dormant.
  - _Requirements: 16.1–16.7_

- [ ] **5.7** Coexistence regression tests: mixed, CLAUDE_CODE-only, failed-only and pseudo users against tier recommendations, inactive subscribers, Kiro segmentation and the funnel. Add the P12 metamorphic test (adding Claude Code items changes no Kiro output; no field sums credits and USD).
  - _Requirements: 7.3, 13.7, 15.1–15.4, 16.1, 21.3_

- [ ] **5.8** `GET /api/config`: add `claudeCodeIngestion` (read-only), including the discovery status, retry backlog and `configError`. `GET /api/etl/executions`: add `sourceCounters`.
  - _Requirements: 3.11, 12.4, 12.6, 17.6, 19.5_

- [ ] **5.9** Frontend:
  - types;
  - `DashboardPage` sends `includeClaudeCode=true`; dashboard Claude Code section (cards from the summary, timeline, model breakdown, partial-estimate badge, unattributed cost) and the conditional `CLAUDE_CODE` filter option; `SummaryCards` unchanged;
  - `UsageTable` USD column, source badges, unattributed label, Kiro labels on the activity columns and a Claude Code last-active column when Claude Code data is present, and `encodeURIComponent`;
  - `UserPage` and `AccountUsagePage` panels; for pseudo-users the user page hides the Productivity tab and defaults to Usage;
  - `ClaudeCodeSegmentationWidget` on the engagement view;
  - `EstimateDisclaimer` with price versions;
  - read-only `ClaudeCodeIngestionConfigView` with the discovery status;
  - counters in `EtlExecutionHistory`, with a fallback label for unknown names.
  
  Add the locale keys (`claudeCode.*`, `users.unattributed.*`, `etl.counters.*`, and `brand.claudeCode`/`brand.amazonBedrock`) to both catalogs. `GitSettingsPage` and `ProductivityPage` stay unchanged.
  - _Requirements: 7.3, 7.6, 12.4, 17.1–17.12_

- [ ] **5.10** Frontend tests:
  - Vitest per new component;
  - Kiro-only snapshot tests unchanged (including pt-BR);
  - pseudo-row label and pseudo-user tab behavior;
  - URL encoding;
  - USD-never-labeled-as-credits (P16);
  - every counter name in the shared constant has an `etl.counters.*` key (modeled on `UserPage.slugMaps.property.test.ts`).
  - _Requirements: 11.1, 17.1, 17.3, 17.7, 17.12, 21.1_

- [ ] **5.11** Golden JSON tests for a Kiro-only table across usage, account, details, export, engagement and config, compared with the baselines committed in 5.0.
  - _Requirements: 11.1, 11.3_

**Validation checkpoint 5.** Backend and frontend suites pass, `npm run build` passes (including `check:locales`), and the Kiro-only golden and snapshot tests are unchanged.

---

## Checkpoint 6 — Infrastructure, IAM, docs, changelog and enabling

- [ ] **6.1** `template.yaml`:
  - the new parameters (including `BedrockIdentityStoreRegion`) and conditions (`HasBedrockLogBuckets`, `HasBedrockLogRole`, `HasBedrockSameAccountLogs`);
  - the `BedrockIngestionParameter` (SSM JSON); the `SSM_BEDROCK_INGESTION` env var on ListFiles, Parse and Backend; `ANALYTICS_TABLE: !Ref AnalyticsTable` on ListFiles and Parse;
  - the IAM statements of design §16 (bucket ARN lists without wildcards; `LeadingKeys` conditions; `GetUserId` in its own conditional statement; `GetInferenceProfile`; conditional `sts:AssumeRole`; RecordStatus ledger `UpdateItem`; Writer spill `GetObject`);
  - the pricing API events.
  
  Run `sam validate` and cfn-lint. Add `tests/test_bedrock_ingestion_template.py`: conditions per parameter combination, no `arn:aws:s3:::*` resource, the Kiro statements and `IdentityCenterAccess` unchanged, `ItemSelector`/`ProcessFiles`/`CheckEtlErrors` unchanged, `ListNewFiles` without `Parameters`/`InputPath`, and the env vars present wherever the new statements are granted.
  - _Requirements: 2.1, 2.2, 2.5, 18.1–18.4, 18.6–18.9_

- [ ] **6.2** Add the `bedrock-log-role.yaml` template (role `kiro-cost-analyzer-bedrock-log-read`; buckets, optional KMS keys, `GetInferenceProfile`; trust pinned to the KCA account) and the `make deploy-bedrock-log-role` target. Add `tests/test_bedrock_log_role_template.py`.
  - _Requirements: 2.7, 18.9_

- [ ] **6.3** `identity-store-role.yaml`: add the `IncludeClaudeCodeLookup` parameter (default `false`) and a conditional `identitystore:GetUserId` statement. Update `tests/test_identity_store_role_template.py` so the default action set stays exactly `DescribeUser` + `ListUsers`, and add a case for the parameter on.
  - _Requirements: 18.5, 18.9_

- [ ] **6.4** `docs/deploy.md`: add a "Claude Code on Amazon Bedrock" section covering:
  - the premises (IdC mandatory, same Identity Store, one reader account, supported identity sources, rename and reuse limits);
  - the IdC home Region (`BedrockIdentityStoreRegion`) and the KMS key policy for an IdC instance with a customer-managed key; correct the existing "`IdentityStoreId` is region-agnostic" row;
  - the dedicated account and the IdC permission set for Claude Code (`aws configure sso`, `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_PROFILE`, `AWS_REGION`);
  - invocation logging to S3 in every used Region (including `ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION`), with the body-delivery setting from task 0.1 (and, if Text delivery is needed, its storage cost and lifecycle policy), the bucket policy for `bedrock.amazonaws.com` and the KMS key policy;
  - tagged AIPs, pinning `ANTHROPIC_MODEL` and all three `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` (or `modelOverrides` for every version), optionally `availableModels`/`enforceAvailableModels`;
  - the complete optional AIP-only policy through `bedrock:InferenceProfileArn` (no `inference-profile/*`; keep `ListInferenceProfiles`/`GetInferenceProfile`);
  - denying `iam:CreateServiceSpecificCredential` and the `notAssumedRole` signal; the SCP for `AWSReservedSSO_*` role names;
  - the log-role deployment, the Identity Store role parameter, the stack parameters and the rollout order (design §17);
  - disabling and purging;
  - the Mantle limitation;
  - the warning about text logging in the KCA account;
  - troubleshooting through `sourceCounters`, the discovery status and the retry backlog;
  - that `BedrockPermissionSetPatterns` is required when the logs are in the KCA account (Q4).
  - _Requirements: 6.9, 20.1, 20.2, 20.5, 20.6_

- [ ] **6.5** `docs/architecture.md`: the adapter, qualified keys, the `token_usage` writer, failure isolation, the retry ledger and the new key families in the DynamoDB schema table. `docs/cost.md`: a Claude Code scenario (S3 List/Get in the customer account, Lambda, DynamoDB transactions and markers, the extra engagement Scan; no Bedrock cost in KCA). `docs/security.md`: metadata-only posture, the log role, the role-name trust assumption and threat-model entries. `docs/features.md`: the views and the `claudeCode` engagement-thresholds key. Also update the steering document's §5.1 and §6.4 tables and the README spec count.
  - _Requirements: 16.6, 20.3_

- [ ]* **6.6** Add `scripts/purge_claude_code_data.py` (design §17) with a dry-run default and a moto test.
  - _Requirements: 19.5_

- [ ] **6.7** `docs/changelog.md` `## Unreleased`: the feature entry. Include the notes that cross-account IdC installations using Claude Code ingestion must redeploy the Identity Store role with `IncludeClaudeCodeLookup=true`, and that Kiro-only behavior is unchanged.
  - _Requirements: 18.5, 20.4_

- [ ] **6.8** Full gates: pytest, `npm run build`, `npm run test`, `sam build`, cfn-lint and `git diff --check`.
  - _Requirements: 21.5_

- [ ] **6.9** Enable in the sandbox, only after checkpoints 0–5 and tasks 6.1–6.8 are merged and deployed:
  1. Deploy with `BedrockIngestionEnabled=false` and the locations configured.
  2. Deploy the log role and the updated Identity Store role.
  3. Update the stack to `BedrockIngestionEnabled=true`.
  4. Run the ETL.
  5. Verify the dashboard, user page, account page, export, `sourceCounters` and the discovery status.
  6. Break the log role on purpose and verify that Kiro categorization and ReconcileUsers still run and that the failed keys appear in the retry backlog; restore it and verify the retry.
  7. Disable and verify that in-flight and historical behavior matches design §17.
  
  Record the results below.
  - _Requirements: 3.9, 11.5, 19.1, 19.2, 19.3, 19.5, 19.6_

**Validation checkpoint 6.** All gates pass. The sandbox end-to-end run shows a mixed user merged under one `USER#`, USD next to credits but never summed with them, `unpricedInvocations` and the drop reasons visible, Bedrock failures isolated from Kiro, and a Kiro-only stack with no visible change.

---

## Definition of done

- [ ] Sanitized real fixtures back every parser assumption; the spike items are resolved in `design.md`.
- [ ] Kiro-only deployments are byte-identical across ETL outputs, DynamoDB items, APIs, exports and UI, against baselines committed from the pre-feature commit.
- [ ] Claude Code usage from IdC principals is attributed to the same `USER#` as Kiro activity. Unresolved names go to admin-only pseudo-users that are excluded from people counts.
- [ ] USD is computed at ingest in Decimal and is labeled as an estimate with its price version. Edits are forward-only, and unpriced invocations are counted.
- [ ] Tokens (with long-context subsets) are persisted per user, day, Region and model, idempotently per file.
- [ ] Tier and dormant logic are unaffected by Claude Code. Claude Code has its own engagement segmentation.
- [ ] Every drop, failure, unpriced and unmapped invocation is counted per run and visible in the UI. Failed files stay in the retry ledger until processed.
- [ ] Infra is least-privilege and conditional. The docs and changelog are current. The feature was enabled only after every checkpoint landed (checkpoints 0–5 and tasks 6.1–6.8).

## Implementation record

_To be filled during implementation: validation counts per checkpoint, spike outcomes, and any design decision changed along the way._
