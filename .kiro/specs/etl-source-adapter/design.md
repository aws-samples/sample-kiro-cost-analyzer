# Design — ETL Source Adapter Seam

## 1. Current coupling

The pipeline currently has source knowledge in four orchestration points:

1. `list_handler.py` separately calls the CSV and prompt listers and classifies membership with a set.
2. `parse_handler.py` dispatches `csv`/`prompt`, owns source-specific readers and path extraction, and invokes the matching processor.
3. `writer_handler.py` repeats the same type ladder.
4. `path_resolver.py`, parsers, normalizers and processors encode the Kiro formats independently of an explicit source boundary.

The parsers and normalizers are already cohesive and tested. The seam should put them behind adapters, not replace them.

## 2. Contract

`etl/sources/base.py` defines:

- `PathMetadata`: an immutable typed value with format, region, date, account and client fields plus conversion to the legacy mapping expected by current normalizers.
- `ParsedSource`: raw parsed records plus `PathMetadata`.
- `SourceAdapter`: a protocol with stable identity and the lifecycle methods `list_files`, `claim`, `read`, `parse`, `normalize`.

Adapters also declare:

- `source_type`: canonical internal name (`kiro_csv`, `kiro_prompt_log`).
- `aliases`: accepted historical names (`csv`, `prompt`).
- `wire_type`: value emitted by ListFiles. It remains the legacy value for both current adapters.
- `record_kind`: writer strategy (`activity` or `prompt`).
- `count_key`: existing ListFiles counter field.
- `requires_content_placement`: whether Parse must apply prompt payload placement.

The lister is part of the contract even though the issue shorthand named only claim/parse/normalize. Without discovery in the adapter, adding a source would still require editing ListFiles, defeating Requirement 1.5.

## 3. Registry

`etl/sources/__init__.py` holds an ordered tuple `REGISTRY`. Registry construction validates every canonical name, alias and wire type for uniqueness. APIs:

- `resolve_adapter(file_type)` — canonical/alias lookup or `ValueError`.
- `claim_adapter(key, config)` — first matching adapter or `None`.
- `discover_files(bucket, config, s3_client)` — invokes each adapter's lister, re-runs claim dispatch for deterministic ownership, skips unclaimed keys, de-duplicates keys in registry order, and returns claimed files plus per-adapter counts.

First claim wins is intentional and tested. Registry order is behavior and therefore explicit rather than discovered dynamically.

## 4. Existing adapters

### 4.1 Kiro CSV

- Lists through `list_csv_files`.
- Claims `{source_prefix}user_report/**/*.csv`.
- Reads through `read_csv_content`.
- Resolves metadata through `resolve_path_metadata`.
- Parses through `parse_csv`.
- Normalizes through `normalize_records`, then uses the existing processor conversion helper.

An unrecognized path normalizes to an empty list, matching current behavior.

### 4.2 Kiro prompt log

- Lists through `list_prompt_files` only when `prompts_prefix` is configured.
- Claims `{prompts_prefix}GenerateAssistantResponse/**/*.json.gz`.
- Reads through `read_prompt_file`.
- Extracts region/account metadata currently owned by `parse_handler.py`.
- Parses through `parse_prompt_file`.
- Normalizes through `normalize_prompt_records`, then uses the existing processor conversion helper.

Name enrichment remains after adapter normalization because it is a pipeline concern shared across source types. Prompt content placement also remains in Parse, selected through adapter metadata rather than a `fileType` conditional.

## 5. Wire compatibility

The adapters have canonical names, but ListFiles keeps emitting `csv` and `prompt`. This is stricter than merely accepting aliases: it preserves the current Step Functions envelope byte-for-byte and prevents a newly updated List Lambda from sending a canonical name to an old Parse Lambda during a rolling CloudFormation update.

Parse and Writer accept both names. Parse returns the input `fileType`, preserving an old payload through the next task. No state-machine definition change is required.

## 6. Writer and optional metrics

Writer dispatches through `adapter.record_kind`; it contains no source-name conditional. Existing `_write_csv_record` remains as a compatibility alias for tests/importers, delegating to the generic activity writer.

`AnalyticsWriter` builds DynamoDB `ADD` clauses from values that are not `None`. Existing Kiro records provide every current metric, so their UpdateExpression and resulting attribute set remain equivalent. A future Bedrock record can omit credits/messages/conversations and provide tokens/cost; absent metrics are not materialized as zero.

The token/cost support belongs in this prerequisite because otherwise #56 would need to modify the shared writer and aggregation methods while adding its adapter, violating the intended seam. No current producer emits those fields in this change.

## 7. Verification

Golden-model property tests compare each adapter to the pre-seam processor API over generated valid inputs:

- CSV: generated valid user-report rows; adapter parse+normalize equals `process_csv`.
- Prompt: generated valid compressed prompt records; adapter parse+normalize equals `process_prompts`.

The oracle remains the existing processor API. It is intentionally not copied: duplicated golden code could preserve the same mistake twice and would become a second implementation to maintain. Existing parser/normalizer unit tests remain the lower-level behavioral proof.

Targeted tests additionally lock registry ordering, duplicates, aliases, wire types, unknown types, content placement and optional-absent writer attributes. The final checks are the full pytest suite and `sam build`.

## 8. Deliberate exclusions

No Bedrock config, identity model, pricing item, exclusion list, frontend behavior or deployment parameter is introduced. This keeps #55 reviewable as an internal refactor and prevents its prerequisite from absorbing #56.
