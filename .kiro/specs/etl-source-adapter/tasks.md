# Tasks — ETL Source Adapter Seam

Implementation plan. Tasks are ordered so every checkpoint is independently testable. Optional tasks are marked `*`.

---

## Checkpoint 1 — Contract and golden tests

- [x] **1.1** Create `etl/sources/base.py` with `PathMetadata`, `ParsedSource` and the `SourceAdapter` protocol.
  - _Requirements: 1.1, 1.2_

- [x] **1.2** Add `tests/test_source_adapter_equivalence.py` with Hypothesis models for valid Kiro CSV and prompt inputs, comparing adapter parse+normalize output with the existing processors.
  - _Requirements: 3.2, 3.3, 6.1_

- [x] **1.3** Add registry unit tests for deterministic first-claim order, duplicate names/aliases, unknown types and legacy/canonical aliases.
  - _Requirements: 2.1, 2.3, 2.4, 4.1, 4.2, 6.2_

**Validation checkpoint 1** — adapter/registry tests fail for the expected missing implementation, while the pre-existing targeted tests remain green.

---

## Checkpoint 2 — Existing Kiro adapters and registry

- [x] **2.1** Implement `etl/sources/kiro_csv.py` around the existing CSV lister, reader, path resolver, parser, normalizer and processor conversion.
  - _Requirements: 1.3, 1.4, 3.2_

- [x] **2.2** Implement `etl/sources/kiro_prompt_log.py` around the existing prompt lister, reader, parser, normalizer and processor conversion; move prompt path metadata extraction behind it.
  - _Requirements: 1.3, 1.4, 3.3_

- [x] **2.3** Implement the ordered validated registry in `etl/sources/__init__.py` with canonical types, legacy aliases, first-claim ownership, de-duplication and unclaimed-key reporting.
  - _Requirements: 2.1, 2.2, 2.4, 4.1, 4.2_

**Validation checkpoint 2** — golden and registry tests pass.

---

## Checkpoint 3 — Handler wiring and deploy compatibility

- [x] **3.1** Wire `list_handler.py` through registry discovery while preserving the current result fields, counts, batch cap, ordering and legacy `fileType` values.
  - _Requirements: 1.5, 2.2, 3.1, 4.5_

- [x] **3.2** Wire `parse_handler.py` through registry lookup and adapter read/parse/normalize; retain shared name enrichment, cross-account clients, error propagation/logging and prompt content placement.
  - _Requirements: 1.5, 3.4, 4.1, 4.2, 4.3_

- [x] **3.3** Wire `writer_handler.py` through adapter `record_kind`, accepting legacy and canonical names; keep compatibility helpers used by tests and callers.
  - _Requirements: 1.5, 2.3, 4.4_

- [x] **3.4** Add regression tests for both aliases through Parse and Writer and for ListFiles continuing to emit legacy values.
  - _Requirements: 3.1, 4.1, 4.2, 4.3, 4.4, 4.5_

**Validation checkpoint 3** — list/parse/writer targeted suites pass without weakening assertions.

---

## Checkpoint 4 — Optional source metrics

- [x] **4.1** Make shared daily/global/tier/client counter expressions add only present metrics and accept token/cache/cost metrics.
  - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6_

- [x] **4.2** Make the generic activity writer distinguish absent metrics from zero while preserving every Kiro field.
  - _Requirements: 3.5, 5.3, 5.4_

- [x] **4.3** Add tests proving a token/cost-only activity item has no credit attributes and Kiro items keep their exact current attributes and values.
  - _Requirements: 3.5, 5.3, 5.4, 5.5_

**Validation checkpoint 4** — analytics writer and handler suites pass, including absence assertions.

---

## Checkpoint 5 — Documentation and full validation

- [x] **5.1** Document the source-adapter lifecycle and extension procedure in `docs/architecture.md`.
  - _Requirements: 6.3_

- [x] **5.2** Add a changelog entry under `## Unreleased`.
  - _Requirements: 6.4_

- [x] **5.3** Run the full backend gate and `sam build`; fix only regressions caused by this refactor.
  - _Requirements: 3.6, 6.5_

- [x] **5.4** Update this task file with actual validation counts and any design decision that changed during implementation.
  - _Requirements: 6.5_

## Definition of done

- [x] Existing Kiro List/Parse/Writer outputs and DynamoDB attributes are unchanged.
- [x] Both legacy and canonical source names are accepted during a deploy window.
- [x] A new source requires only an adapter and registry entry, not handler conditionals.
- [x] Golden property tests pass for both current adapters.
- [x] Full backend tests and `sam build` pass.
- [x] Architecture and changelog documentation are current.

## Implementation record

- Focused adapter/List/Parse/Writer/processor/path/analytics gate: **106 passed**.
- Full backend gate: **1021 passed**, with one pre-existing `bedrock_agentcore` Pydantic deprecation warning.
- Packaging gate: **`sam build` succeeded**; `sources/{base,kiro_csv,kiro_prompt_log,__init__}.py` is present in the ListFiles, Parse, and Writer artifacts.
- Static checks: changed Python files compile, language-server diagnostics are clean, the top-level Lambda import smoke test passes, and `git diff --check` passes.
- Final adjustment: handler and adapter imports select package-relative dependencies when loaded as `etl.*` and top-level dependencies when loaded from the SAM `CodeUri`. This removes the test-order-dependent `etl.sources` / `sources` duplication while retaining Lambda packaging compatibility.
- Final adjustment: CSV claiming delegates to the existing path resolver before S3 reads, preserving the prior rejection of malformed report paths without weakening production validation. Discovery tests use complete Kiro object keys accordingly.
