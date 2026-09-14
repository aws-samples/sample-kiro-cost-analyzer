# Requirements — ETL Source Adapter Seam

The ETL pipeline currently understands the two Kiro source formats through coordinated conditionals spread across file discovery, path parsing, content parsing, normalization and writing. Adding a third source would require editing each of those points and extending the same `if file_type ==` ladder repeatedly. This spec extracts an internal adapter seam while preserving the deployed Kiro behavior and wire contract.

## Glossary

- **Source adapter**: the module that owns discovery, claiming, reading, parsing and normalization for one source format.
- **Registry**: the ordered collection of source adapters. First claim wins.
- **Canonical source type**: the stable internal adapter name, such as `kiro_csv`.
- **Wire type**: the `fileType` value exchanged by the Step Functions Map tasks. Existing Kiro wire types remain `csv` and `prompt`.
- **Path metadata**: source-independent metadata carried from parsing into normalization: format, region, date components, account and client type.

## Requirement 1: Each source is isolated behind one contract

**User Story.** As a maintainer adding a data source, I want source-specific knowledge in one adapter, so that I do not edit the ETL orchestration for each new format.

### Acceptance Criteria

1.1. THE ETL SHALL define a `SourceAdapter` protocol that owns source identity, aliases, discovery, claim, read, parse and normalize operations.

1.2. THE ETL SHALL define a typed `PathMetadata` value shared by adapters.

1.3. THE repository SHALL provide one adapter for Kiro user-report CSV files and one adapter for Kiro prompt-log files.

1.4. THE existing CSV parser, schema validator, normalizer, prompt parser and prompt normalizer SHALL remain the implementation behind the adapters rather than being replaced.

1.5. ADDING a source SHALL require a new adapter module and one registry entry, without adding a source-specific conditional to `list_handler.py`, `parse_handler.py` or `writer_handler.py`.

## Requirement 2: Registry dispatch is deterministic

**User Story.** As an operator, I want source classification deterministic, so that overlapping claims cannot route a file differently across runs.

### Acceptance Criteria

2.1. THE registry SHALL be ordered, and WHEN multiple adapters claim a key THEN the first registered adapter SHALL win.

2.2. WHEN a key is not claimed by any adapter THEN ListFiles SHALL skip it and log the omission without failing the batch.

2.3. WHEN a `fileType` is unknown THEN Parse and Writer SHALL fail with `ValueError` rather than silently selecting an adapter.

2.4. THE registry SHALL reject duplicate canonical names, aliases and wire types at import/test time.

## Requirement 3: Existing Kiro behavior is unchanged

**User Story.** As an operator of the deployed pipeline, I want the refactor to preserve all current records and counters, so that extensibility introduces no migration or analytics drift.

### Acceptance Criteria

3.1. ListFiles SHALL continue returning the existing top-level fields and Kiro `fileType` values (`csv`, `prompt`).

3.2. THE CSV adapter SHALL produce records equal to the pre-refactor `process_csv` output for every valid generated Kiro CSV input.

3.3. THE prompt adapter SHALL produce records equal to the pre-refactor `process_prompts` output for every valid generated Kiro prompt-log input.

3.4. Parse SHALL preserve name enrichment, cross-account client handling, access-denied logging and prompt content placement behavior.

3.5. Writer SHALL preserve the exact DynamoDB attribute set and counters produced for existing Kiro records.

3.6. THE current backend test suite SHALL pass without weakening an existing assertion.

## Requirement 4: Deploy-window compatibility is bidirectional

**User Story.** As an operator deploying while a Distributed Map is running, I want old and new task payloads accepted, so that a rolling Lambda update cannot strand in-flight children.

### Acceptance Criteria

4.1. THE CSV adapter SHALL resolve from both `csv` and `kiro_csv`.

4.2. THE prompt adapter SHALL resolve from both `prompt` and `kiro_prompt_log`.

4.3. Parse SHALL return the `fileType` received in the event, so that an in-flight legacy payload remains legacy through Writer.

4.4. Writer SHALL dispatch both legacy aliases and canonical names to the same record writer.

4.5. ListFiles SHALL continue emitting legacy Kiro wire types in this refactor, eliminating the new-List/old-Parse half of the rolling-deploy hazard.

## Requirement 5: The data model can represent non-credit sources without changing Kiro items

**User Story.** As the maintainer implementing #56 later, I want optional token and cost metrics available in the writer, so that Bedrock records do not fabricate zero-valued credit attributes.

### Acceptance Criteria

5.1. THE activity writer SHALL add a metric only when that metric is present in the normalized record.

5.2. THE supported optional metrics SHALL include `totalCredits`, `overageCredits`, `totalMessages`, `totalConversations`, `totalInteractions`, `inputTokens`, `outputTokens`, `cacheReadTokens`, `cacheWriteTokens` and `estimatedCostUsd`.

5.3. WHEN a metric is absent THEN its DynamoDB attribute SHALL remain absent rather than being created with zero.

5.4. EXISTING Kiro CSV records SHALL continue carrying all current credit/message/conversation/interaction attributes with the same values.

5.5. GLOBAL and client-type aggregates SHALL tolerate and accumulate records without credit attributes.

5.6. Tier aggregates SHALL only be written when a tier is present.

## Requirement 6: The seam is documented and verified

**User Story.** As a future contributor, I want the adapter boundary documented and regression-tested, so that new sources follow the same extension path.

### Acceptance Criteria

6.1. THE repository SHALL include golden-model Hypothesis tests for both existing adapters.

6.2. THE tests SHALL cover deterministic registry order, duplicate alias rejection, unknown types and legacy/canonical alias compatibility.

6.3. `docs/architecture.md` SHALL describe the registry, adapter lifecycle and source-extension procedure.

6.4. `docs/changelog.md` SHALL record the internal refactor under `## Unreleased`.

6.5. THE full backend gate and `sam build` SHALL pass.

## Out of scope

- The Bedrock invocation-log adapter, pricing, identity mapping, self-invocation filtering and frontend work from #56.
- A new S3 location or CloudFormation parameter.
- Changing the Kiro wire types emitted by ListFiles.
- Pre-computing or migrating existing DynamoDB items.
- Changing analytics semantics, recommendation eligibility or client-type presentation.
