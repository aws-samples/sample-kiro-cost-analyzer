# Implementation Plan: GitLab Provider Support

## Overview

The tasks below follow the design's component list (components 1–14 plus infrastructure and documentation), not the requirement list. Requirement references are attached to each task for traceability.

Order is driven by four hard dependencies from the design:

1. The `git_repository.py` duplication is resolved first. This feature edits that file, and while two byte-identical copies exist (`backend/repository/` imported by handlers, `layers/shared/git_shared/` imported by tests), editing either one makes the tested file diverge from the deployed file with no visible symptom. Nothing mapping-related lands before task 1.
2. Shared-layer modules (`git_providers.py`, `git_url_parser.py`, `git_mapping_selection.py`) come before their consumers. `select_mapping` in particular is shared by the correlation handler and the migrator so the two cannot disagree about which mapping wins.
3. The migrator gets `SharedLayer` attached, unlike `admin_user_creator.py`, because it needs `mapping_sort_key` and `select_mapping` from the layer.
4. Frontend contract changes (`deleteGitMapping` arity, `GitMappingForm.onSubmit` return type, the widened `CorrelationStatusSlug`) are grouped so `tsc` is not left failing across several tasks. Locale keys land before the code that references them, since `keys.d.ts` is generated from the catalogs.

The backend and the agent deploy independently (`make deploy-infra` vs `make deploy-agentcore`). Per DD-5 the invocation payload is additive, so no task assumes one side shipped before the other.

Implementation languages: Python 3.13 (backend, shared layer, custom resource, agent) and TypeScript/React (frontend), as specified in the design.

**Property test placement**, fixed by the design's Testing Strategy:

- `tests/test_gitlab_provider_properties.py` — Properties 1–5 and 7–19
- `tests/test_git_mapping_properties.py` — Properties 6, 22, 23, 24, 25 (split out: they share a populated-table fixture and rebuild the table per example)
- fast-check under `frontend/src/` — Properties 20, 21

Every property is implemented by exactly one test, tagged `# Feature: gitlab-provider-support, Property N: <title>`, with a 100-iteration floor (`@settings(max_examples=100)` / `{ numRuns: 100 }`).

Criteria the design classifies as example tests are not promoted to properties: 2.9 (delete idempotence), 11.8 (per-item failure resilience), the watchdog's early stop, and 9.1 / 9.2 / 9.6 / 9.7 (frontend rendering).

## Tasks

- [x] 1. Resolve the shared Git repository duplication (prerequisite for every mapping change)
  - [x] 1.1 Collapse `git_repository.py` to the shared-layer copy
    - Delete `backend/repository/git_repository.py`
    - Repoint every backend importer to `from git_shared.git_repository import GitRepository`, using the project's try/except import fallback pattern
    - Confirm `conftest.py`'s existing `layers/shared` path entry keeps `tests/test_git_repository.py` resolving, and that no test import changes are needed
    - No behavior change in this task — it only makes the tested file the deployed file, which is the precondition for Properties 6, 22, 23, 24, and 25 to say anything about production
    - _Requirements: 2.5, 2.6_

- [x] 2. Checkpoint - Existing suite green after the collapse
  - Run the full Python test suite unchanged. Ensure all tests pass, ask the user if questions arise.

- [x] 3. Shared-layer provider foundation
  - [x] 3.1 Create `layers/shared/git_shared/git_providers.py`
    - `SUPPORTED_PROVIDERS = frozenset({"github", "gitlab"})`, `PROVIDER_ORDER = ("github", "gitlab")`, `SSM_TOKEN_PATH_PREFIX`, `TOKEN_MISSING_SLUG`, `MAPPING_SK_PREFIX`
    - `mapping_sort_key(provider)` returning `GITMAP#{provider}` — the single place the key shape is written
    - `is_legacy_mapping_sort_key(sort_key)` discriminating on separator count (`>= 2` is legacy), so an unexpected shape migrates rather than being silently skipped
    - _Requirements: 1.3, 2.2, 2.5_

  - [x] 3.2 Create `layers/shared/git_shared/git_url_parser.py`
    - `normalize_repo_url`, `parse_repo_url`, `build_repo_url`, and the `RepoLocation` TypedDict
    - `urlsplit`-based, not regex-based. Total: never raises, returns `None` on unparseable input
    - GitHub takes the last two path segments; GitLab takes all segments, preserving subgroups. Strip `.git` and trailing slash, lowercase scheme and host, leave the path case intact, drop a default port matching the scheme
    - Leave `_URL_PATTERN` in `git_repo_handler` as the create-time validity gate; this module is the analysis-time structural derivation
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 3.3 Create `layers/shared/git_shared/git_mapping_selection.py`
    - `select_mapping(candidates)`: newest `createdAt` wins; on a tie the lexicographically smallest `gitUsername` wins; a missing `createdAt` sorts as the empty string and is therefore oldest rather than an error
    - Keep the two-stage form (max, then min over the tied set) — the rule mixes directions and a single `sorted(reverse=True)` cannot express it
    - This module is imported by both the correlation handler and the migrator; do not duplicate the rule in either
    - _Requirements: 7.9, 11.2, 11.3_

  - [x]* 3.4 Write property test for URL round trip and normalization
    - **Property 1: Repository URL round trip and normalization idempotence**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.6**
    - Generator note: compose URLs from parts (scheme, host labels, optional port, 2–6 path segments, optional `.git` and trailing slash) rather than sampling free text, so subgroup depth and non-standard ports actually occur

  - [x]* 3.5 Write property test for parser totality
    - **Property 2: URL parser totality**
    - **Validates: Requirements 4.5**
    - Generator note: the opposite generator — `st.text()` plus a curated hostile list (empty, whitespace, control characters, `git@host:path`, IPv6 literals, host with no path, arbitrary Unicode). The claim is that nothing crashes the parser

- [x] 4. Widen provider validation across the two CRUD handlers
  - [x] 4.1 Import `SUPPORTED_PROVIDERS` in `git_repo_handler.py` and `git_mapping_handler.py`
    - Replace both local `frozenset({"github"})` literals with the shared constant, via the try/except fallback
    - Generalize the `git_repo_handler` rejection message (currently "Only GitHub is supported.") to render from the set: `f"Unsupported provider: {provider}. Valid providers: {', '.join(sorted(SUPPORTED_PROVIDERS))}"`. `git_mapping_handler` already renders it this way
    - _Requirements: 1.1, 1.3, 2.2_

  - [x]* 4.2 Write property test for provider validation
    - **Property 4: Provider validation is exactly the supported set**
    - **Validates: Requirements 1.3, 2.2**

  - [x]* 4.3 Write property test for repository configuration round trip and secret non-disclosure
    - **Property 5: Repository configuration round trip and secret non-disclosure**
    - **Validates: Requirements 1.1, 1.2, 1.5**

  - [x]* 4.4 Extend `tests/test_git_repo_handler.py`
    - `gitlab` accepted with an arbitrary host and non-standard port
    - SecureString storage shape for the per-repository token (1.4)
    - Delete removes both the DynamoDB item and the SSM parameter (1.6)
    - _Requirements: 1.4, 1.6_

- [x] 5. Mapping repository layer (component 13)
  - [x] 5.1 Change the mapping key shape and the two mutating signatures in `layers/shared/git_shared/git_repository.py`
    - `put_user_mapping` writes `SK = mapping_sort_key(provider)` and returns `(stored_item, previous_item)`, sourcing `previous_item` from `put_item(..., ReturnValues="ALL_OLD")` — one round trip, and an answer that cannot be stale
    - `delete_user_mapping(user_id, provider)` drops the username argument
    - Leave `list_user_mappings` unchanged: its `begins_with("GITMAP#")` condition matches both key shapes, which is what makes the read path legacy-tolerant
    - _Requirements: 2.5, 2.6, 2.7, 2.8_

  - [x] 5.2 Correct `get_all_mappings_for_provider`
    - The current predicate `Key("SK").begins_with(f"GITMAP#{provider}#") & Attr("provider").eq(provider)` matches nothing under the new key shape — the trailing `#` is gone, so the method would silently return an empty list for every provider
    - Replace with exact equality: `Attr("SK").eq(mapping_sort_key(provider)) & Attr("provider").eq(provider)`. Do **not** shorten to `begins_with(f"GITMAP#{provider}")` — `GITMAP#git` prefix-matches both `GITMAP#github` and `GITMAP#gitlab`
    - Use `Attr` rather than `Key` in the scan filter (the existing `Key` usage worked by accident of boto3's condition rendering)
    - _Requirements: 2.10_

  - [x] 5.3 Write property test for provider-scoped retrieval
    - **Property 22: Provider-scoped retrieval returns exactly one provider's mappings**
    - **Validates: Requirements 2.10**
    - Not optional: this is the regression guard for the `begins_with` bug above, whose failure mode is an empty result rather than an error
    - Generator note: sample providers from a small set that includes a bare `git` alongside `github` and `gitlab`, so the prefix collision is exercised head-on rather than incidentally

  - [x]* 5.4 Extend `tests/test_git_repository.py`
    - New sort key written; `put_user_mapping` returns the overwritten item; `delete_user_mapping` two-argument signature; `get_all_mappings_for_provider` returns nothing for a legacy-keyed item
    - _Requirements: 2.5, 2.8, 2.10_

- [x] 6. Mapping handler upsert, delete, and route (component 12)
  - [x] 6.1 Make `handle_create_mapping` an upsert that reports replacement
    - Consume the `(stored, previous)` tuple from `put_user_mapping`; return `replaced` and `previousGitUsername` in the 201 body and log both
    - `replaced` / `previousGitUsername` are data, not prose — the frontend composes the sentence, keeping the English-only-backend rule intact
    - Write `createdAt` and `createdBy` fresh on a replacement rather than carrying them over: the item now describes a different Git identity
    - _Requirements: 2.1, 2.3, 2.4, 2.7_

  - [x] 6.2 Shorten the delete path end to end
    - `handle_delete_mapping(user_id, provider, dynamodb_resource=None)` — no pre-existence read, no 404 branch, unconditional `{"userId", "provider", "deleted": True}`, which is what makes repeated deletion idempotent
    - `backend/handler.py`: `_GIT_MAPPING_DELETE_PATTERN` drops its third capture group, becoming `^/api/git/mappings/([^/]+)/([^/]+)$`
    - `template.yaml`: `GitMappingsDelete` path becomes `/api/git/mappings/{userId}/{provider}`
    - _Requirements: 2.8, 2.9, 2.11_

  - [x] 6.3 Write property test for mapping storage
    - **Property 6: Mapping storage — coexistence, uniqueness, replacement, and deletion**
    - **Validates: Requirements 2.1, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 7.8**
    - Not optional: this is the uniqueness invariant everything downstream leans on, and a defect here yields a plausible-looking wrong answer
    - Generator note: emit a *sequence* of usernames per provider (min length 1, max 4–5). A generator submitting exactly one username per provider tests coexistence and nothing else — the at-most-one invariant and the whole replacement branch never fire

  - [x]* 6.4 Extend `tests/test_git_mapping_handler.py` and `tests/test_handler.py`
    - `gitlab` accepted; both providers coexist for one user
    - Delete idempotence as examples: delete an existing pair twice, and delete a pair that never existed (2.9)
    - The upsert's `replaced` / `previousGitUsername` body on both branches
    - Two-segment DELETE path dispatches with `(userId, provider)`; the three-segment path no longer matches (2.11)
    - _Requirements: 2.9, 2.11_

- [x] 7. Checkpoint - Mapping CRUD and repository layer
  - Run the Python suite and `cfn-lint`. Ensure all tests pass, ask the user if questions arise.

- [x] 8. Mapping migrator and its infrastructure (component 14)
  - [x] 8.1 Create `custom_resources/mapping_migrator.py`
    - `migrate(table, logger, remaining_ms) -> dict` returning `{scanned, migrated, discarded, failed, unconverted, truncated}`; never raises
    - Discovery: paginated `Scan` filtered on `Attr("SK").begins_with("GITMAP#")`, with `is_legacy_mapping_sort_key` separating legacy items from already-migrated ones. Provider from the item attribute when present, from the sort key's second segment otherwise
    - Collapse: group legacy items by `(userId, provider)`, **including any item already under the new key** in the candidate set, and resolve with the shared `select_mapping`. Carry `provider`, `gitUsername`, `createdAt`, `createdBy` over verbatim
    - Ordering is put-then-delete, and it is load-bearing: a crash between them leaves a duplicate that a re-run collapses, whereas delete-then-put loses the mapping with no record of what it was
    - Response watchdog: check `remaining_ms()` **between items** against `RESPONSE_MARGIN_MS = 10_000`, set `truncated = True` and break cleanly. Checking once at the top is not sufficient — one slow item would overrun the reservation
    - Logging: one record per migrated pair (`userId`, `provider`, retained `gitUsername`, discarded count), one per failure (`userId`, `provider`), and one summary record carrying every count plus `truncated` and `unconverted`. The summary record is the only signal that distinguishes a partial run from a complete one, since both report `SUCCESS`
    - Lifecycle: Create/Update/Delete handling and the `_send_response` HTTPS callback modeled on `custom_resources/admin_user_creator.py`. Report `SUCCESS` with the report on per-item failure and on truncation; `FAILED` only when the scan itself could not run. Carry `truncated` in the CloudFormation response `Data`
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8_

  - [x] 8.2 Add the migrator resources to `template.yaml`
    - `MappingMigratorFunction`: `Handler: mapping_migrator.lambda_handler`, `CodeUri: custom_resources/`, `MemorySize: 256`, `Timeout: 900`, `ANALYTICS_TABLE` env var
    - Attach `SharedLayer` — a departure from `AdminUserCreatorFunction`, which attaches no layer, and the reason the migrator can share `mapping_sort_key` and `select_mapping` instead of re-implementing them
    - `MappingMigrationTableAccess` statement: `dynamodb:Scan`, `PutItem`, `DeleteItem` on the table ARN. This is the widest new grant in the feature — DynamoDB IAM conditions cannot constrain a sort key prefix on `DeleteItem`
    - `MappingMigration` custom resource: `ServiceTimeout: "960"` (quoted; custom resource properties travel as strings), `TableName`, `MigrationVersion: "1"`, `DependsOn: AnalyticsTable`
    - The two timeout values are coupled: `ServiceTimeout` must stay above the function `Timeout`, or the stack fails while the function is still legitimately working. Raising one without the other reintroduces that failure
    - _Requirements: 11.1_

  - [x] 8.3 Write property test for mapping selection agreement
    - **Property 23: Mapping selection is a function of the stored data, and both components compute it identically**
    - **Validates: Requirements 7.9, 11.2, 11.3, 11.4**
    - Not optional: divergence between the reader's and the migrator's selection rule attributes commits to a username the migration is about to discard, with no error anywhere
    - Generator notes: draw `createdAt` from a **small pool** of three or four distinct timestamps — freshly sampled ISO-8601 strings never repeat, so ties never occur and the lexicographic tie-break of 11.3 never executes. Some items must omit `createdAt` entirely. Candidate sets must have size **greater than one**: one mapping per pair makes the collapse rule vacuously true, and that is the single most likely way these migration properties look green while asserting nothing

  - [x] 8.4 Write property test for the migration postcondition
    - **Property 24: Migration postcondition — present under the new key, absent under the legacy key**
    - **Validates: Requirements 11.1, 11.5**
    - Not optional
    - Generator note: pass `migrate` a `remaining_ms` callable returning a large constant, well above `RESPONSE_MARGIN_MS`, so every generated run sits inside the untruncated precondition. This is a deliberate blind spot — the truncation path belongs to task 8.6

  - [x] 8.5 Write property test for migration idempotence
    - **Property 25: Migration idempotence**
    - **Validates: Requirements 11.6**
    - Not optional
    - Generator notes: the generator must construct a *partially migrated* store directly in the fixture — a legacy item and a current item for the same pair, either one holding the newer `createdAt`. That state is unreachable by running the migrator normally; it is what a crash between the put and the delete leaves behind, and therefore exactly what idempotence has to survive. Same large-constant `remaining_ms` as Property 24

  - [x]* 8.6 Write `tests/test_mapping_migrator.py`
    - Structured log content per migrated pair (11.7); the summary record's counts, `truncated` flag, and unconverted count
    - Per-item failure resilience with a table double whose `put_item` raises for one chosen item (11.8)
    - The already-migrated no-op and the partially-migrated convergence case
    - The watchdog's early stop: supply a `remaining_ms` callable that returns a comfortable budget for *k* items and then a value below `RESPONSE_MARGIN_MS` (a counter closure, or `itertools.chain(repeat(60_000, k), repeat(1_000))`). Assert the loop stopped at that index, the report is `truncated: True` with `migrated` and `unconverted` matching the split, the summary record carries both, and a `SUCCESS` response was sent. Also assert the weaker postcondition that survives truncation: every pair present before the run is still retrievable through `list_user_mappings`, under the new key if reached and the legacy key if not
    - Every call supplies the third `migrate` argument
    - _Requirements: 11.7, 11.8_

- [x] 9. Checkpoint - Migration path
  - Run the Python suite including both property files and `cfn-lint`. Ensure all tests pass, ask the user if questions arise.

- [x] 10. Correlation handler — descriptors and token resolution (components 3, 4)
  - [x] 10.1 Replace the GitHub-only descriptor construction
    - `build_repo_descriptors(repo_configs, mappings) -> (descriptors, excluded)` as a pure function, replacing the `if "github.com" in url` block. Exclusion reasons: `UNSUPPORTED_PROVIDER`, `UNPARSEABLE_URL`, `NO_USER_MAPPING`. Every input config lands in exactly one list
    - `resolve_usernames_by_provider(mappings)` keyed on provider, calling `select_mapping` per provider so reads stay deterministic while unconverted legacy items exist
    - One structured warning per exclusion carrying `repoId`, `provider`, `reason` — silent exclusion is the failure mode this design most wants to avoid
    - Descriptors carry `repoId`, never a token and never an SSM path (DD-3)
    - _Requirements: 4.5, 7.1, 7.2, 7.3, 7.4, 7.8, 7.9_

  - [x] 10.2 Replace provider-blind token resolution
    - Delete `_fetch_github_token`; it called `get_parameters_by_path` and returned the most-recently-modified value, which hands a GitLab token to the GitHub tool once two providers coexist
    - `resolve_token_availability(descriptors, ssm_client=None)` calling `get_parameter(Name=f"{SSM_TOKEN_PATH_PREFIX}/{repoId}", WithDecryption=False)` — existence only, so no secret is decrypted into the API Lambda
    - `select_token_missing_slug(missing)`: provider with the most affected repositories wins, ties break by `PROVIDER_ORDER`
    - At least one token present: proceed with those descriptors, warn per repository without one, emit no slug. No token anywhere: emit the selected slug
    - Widen the handler's slug union with the three `GITLAB_*` members
    - _Requirements: 3.1, 3.2, 3.3, 8.4, 8.5, 8.6_

  - [x] 10.3 Write property test for repository-scoped token resolution
    - **Property 7: Repository-scoped token resolution**
    - **Validates: Requirements 3.1, 3.2**
    - Not optional: handing the wrong provider's token to a tool produces an auth failure that looks like a user configuration problem, not a bug

  - [x]* 10.4 Write property test for token-missing slug selection
    - **Property 9: Token-missing slug selection totality and determinism**
    - **Validates: Requirements 3.3**

  - [x]* 10.5 Write property test for descriptor well-formedness
    - **Property 10: Repository descriptor well-formedness and provider-matched username**
    - **Validates: Requirements 7.1, 7.2**

  - [x]* 10.6 Write property test for the descriptor/exclusion partition
    - **Property 11: Descriptor and exclusion partition**
    - **Validates: Requirements 7.3, 4.5**

  - [x]* 10.7 Write property test for status slug closure
    - **Property 19: Correlation status slug closure and absence of prose**
    - **Validates: Requirements 8.4, 8.6**

  - [x]* 10.8 Extend `tests/test_agent_correlation_handler.py`
    - Descriptor construction examples; the `GIT_MAPPING_MISSING` branch (7.4); token-missing branches per provider
    - _Requirements: 7.4_

- [x] 11. Correlation worker (component 5)
  - [x] 11.1 Forward descriptors verbatim into the agent payload
    - `_invoke_agent` stops rebuilding the payload from positional arguments and passes `repos` through unchanged — no transformation, no filtering, no defaulting
    - Retain the top-level `gitUsername`, populated from the GitHub mapping and falling back to the first mapping, so an older agent build keeps working (DD-5)
    - _Requirements: 7.5_

  - [x]* 11.2 Write property test for the invocation payload round trip
    - **Property 12: Agent invocation payload round trip**
    - **Validates: Requirements 7.5**

  - [x]* 11.3 Extend `tests/test_correlation_worker.py`
    - Payload forwarding example; the unconfigured-runtime-ARN guard
    - _Requirements: 7.5_

- [x] 12. Checkpoint - Backend correlation flow
  - Run the Python suite. Ensure all tests pass, ask the user if questions arise.

- [x] 13. Correlation agent (components 6, 7, 8, 9, 10)
  - [x] 13.1 Create `agent/app/GitCorrelationAgent/tools/ssm_token.py`
    - `fetch_repo_token(repo_id, ssm_client=None)` validating against `REPO_ID_PATTERN = ^[0-9a-f]{8}$` before constructing the parameter name, so a hostile payload value cannot address an arbitrary parameter
    - Returns `""` on validation failure, `ParameterNotFound`, or any `ClientError`, logging the reason
    - Note the coupling to `_generate_repo_id()` (`uuid.uuid4().hex[:8]`) in both modules' docstrings
    - _Requirements: 3.4_

  - [x] 13.2 Create `agent/app/GitCorrelationAgent/tools/gitlab_tool.py`
    - `build_gitlab_tool(repo_id)` returning a `@tool`-decorated `get_gitlab_activity(base_url, project_path, author, since)`, mirroring `github_tool.py` structurally
    - `MAX_COMMITS = 100`, `MAX_MRS = 50`, `REQUEST_TIMEOUT_SECONDS = 30`, `API_PATH = "/api/v4"`; project segment is `quote(project_path, safe="")`
    - `PRIVATE-TOKEN` header, never `Authorization`. Commits: `since`, `per_page=100`. Merge requests: `author_username`, `created_after`, `state=all`, `per_page=50`, `order_by=updated_at`, `sort=desc`
    - Always filter commits client-side on `author_name` and `author_email`, case-insensitively — the endpoint's `author` parameter arrived in GitLab 15.10 and matches the commit author name, not the account username, so no server-side filter is relied on
    - Re-check `author.username` client-side on merge requests too, and drop any item whose normalized date sorts before the start date
    - Normalize commits to `sha`/`message`/`date` (`authored_date`, falling back to `committed_date` then `created_at`) and merge requests into `pull_requests` as `number` (`iid`), `title`, `state` (GitLab vocabulary verbatim), `created_at`
    - Error returns per the design's table: `GITLAB_AUTH_FAILED` non-retryable for 401/403, `GITLAB_RATE_LIMIT` retryable for 429, `GITLAB_REQUEST_FAILED` retryable for network failures and 404, empty collections for a 200 with an unexpected body, commits plus a `warning` field when only the merge request call fails
    - Every field access via `.get()` with a default; return error dicts rather than raising, so the model can reason about the failure instead of retry-looping
    - Certificate verification stays enabled — no `verify=False` escape hatch, since the `PRIVATE-TOKEN` header travels on that connection
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 6.1, 6.2, 6.3, 8.1, 8.2, 8.3, 10.1, 10.3, 10.4_

  - [x] 13.3 Change the `GitHub_Tool` factory signature
    - `build_github_tool(token)` becomes `build_github_tool(repo_id)`, fetching through `fetch_repo_token` lazily on first invocation and memoizing in the closure, so a GitLab-only analysis never reads a GitHub token
    - Request construction, filtering, caps, error codes, and output shape untouched. `tests/test_github_tool.py` must pass with no change beyond the factory call — any further change means the output shape moved
    - _Requirements: 6.4, 8.5_

  - [x] 13.4 Register both tools in `agent/app/GitCorrelationAgent/main.py`
    - Register `kiro_tool`, `github_tool`, and `gitlab_tool` unconditionally; the prompt decides which is called
    - Delete `_fetch_token_from_ssm` — it sorted `get_parameters_by_path` results by `LastModifiedDate` and has no correct behavior with two providers
    - `_normalize_descriptors(repos, fallback_username)` applying the DD-5 defaults: a descriptor with no `provider` is treated as `github`, a descriptor with no `gitUsername` falls back to the top-level value, and descriptors with an unknown provider or missing location fields are dropped with a warning
    - `repo_id` becomes a per-call tool argument alongside the location parameters
    - _Requirements: 7.6, 3.4_

  - [x] 13.5 Make `agent/app/GitCorrelationAgent/prompts.py` provider-aware
    - `SYSTEM_PROMPT`: third tool inventory entry; the workflow step becomes "For EACH repository listed, call the tool matching that repository's provider"; a terminology note that merge requests and pull requests are the same concept for correlation
    - Do **not** extend `correlations[].type` with `prompt_to_mr` — both map to `prompt_to_pr`, keeping the frontend union and the `productivity.correlation.type.*` keys intact
    - `build_user_prompt` renders provider-annotated repository lines carrying `repoId` and the per-repository username, and mentions each provider's terminology only when that provider is present in the payload
    - _Requirements: 7.7_

  - [x]* 13.6 Write property test for agent token parameter derivation
    - **Property 8: Agent token parameter derivation**
    - **Validates: Requirements 3.4**

  - [x]* 13.7 Write property test for GitLab request shape
    - **Property 3: GitLab request shape**
    - **Validates: Requirements 4.4, 5.1, 5.2, 5.3, 5.8, 10.1, 10.3, 10.4**
    - Patch `requests.get` and assert on captured arguments — no real network calls, which is what makes 100+ iterations affordable. The path allowlist in this property is also the partial guard for criterion 10.2

  - [x]* 13.8 Write property test for normalized contract totality
    - **Property 15: Normalized activity contract totality across providers**
    - **Validates: Requirements 6.1**
    - Generator note: the response generator **must** produce malformed payloads — missing keys, `None` values, integers where strings belong, deeply nested junk. A generator emitting only well-formed GitLab responses makes the property pass without testing the totality claim

  - [x]* 13.9 Write property test for GitLab normalization field fidelity
    - **Property 16: GitLab normalization field fidelity**
    - **Validates: Requirements 6.2, 6.3**

  - [x]* 13.10 Write property test for GitLab filtering and bounds
    - **Property 17: GitLab activity filtering and bounds**
    - **Validates: Requirements 5.4, 5.5, 5.6, 5.7**
    - Generator note: the commit and merge request generators must mix matching and non-matching authors, and spread dates before, on, and after the start date. A generator where every item matches the target author makes the filtering assertion vacuous

  - [x]* 13.11 Write property test for GitLab error classification
    - **Property 18: GitLab error classification totality**
    - **Validates: Requirements 8.1, 8.2, 8.3**

  - [x]* 13.12 Write property test for provider dispatch totality
    - **Property 13: Provider dispatch totality**
    - **Validates: Requirements 7.6**

  - [x]* 13.13 Write property test for prompt terminology
    - **Property 14: Provider-appropriate prompt terminology**
    - **Validates: Requirements 7.7**

  - [x]* 13.14 Write `tests/test_gitlab_tool.py`
    - Endpoint construction, header, param, and timeout examples; each error branch; the partial-failure branch where commits succeed and merge requests fail
    - _Requirements: 5.1, 5.2, 5.3, 5.8, 8.1, 8.2, 8.3_

- [x] 14. Checkpoint - Agent tools and prompts
  - Run the Python suite. Ensure all tests pass, ask the user if questions arise.

- [x] 15. Frontend (component 11)
  - [x] 15.1 Create `frontend/src/constants/gitProviders.ts` and consume it in both forms
    - `SUPPORTED_GIT_PROVIDERS`, `SupportedGitProvider`, `buildProviderOptions(t)`
    - `GitRepoForm.tsx` and `GitMappingForm.tsx` both drop their local single-entry `PROVIDER_OPTIONS` literal and call `buildProviderOptions(t)`. The `git.provider.github` and `git.provider.gitlab` keys already exist in both catalogs, so no new translations are needed here
    - _Requirements: 9.1, 9.2_

  - [x] 15.2 Add the five locale keys to both catalogs
    - `productivity.correlation.status.gitlabTokenMissing`, `gitlabAuthFailed`, `gitlabRateLimit`, plus `gitMappingForm.successReplaced` and `gitSettings.mappings.success.removed`
    - Use the wording drafted in the design for `en` and `pt-BR`; insert each at its alphabetical position, since `check-locales.ts` gates the build on sort order and key parity
    - `gitMappingForm.successReplaced` is deliberately not `gitMappingForm.success.replaced`: `gitMappingForm.success` already exists as a leaf, and i18next resolves a key that is simultaneously a leaf and a prefix unpredictably
    - This task lands before the code that references the keys, because `keys.d.ts` is generated from the catalogs and `t()` is typed against it
    - _Requirements: 9.5, 9.8_

  - [x] 15.3 Widen the status slug union and the `UserPage` maps together
    - `types/index.ts`: three new `CorrelationStatusSlug` members; new `GitMappingCreated extends GitUserMapping` with `replaced` and optional `previousGitUsername`
    - `pages/UserPage.tsx`: three entries in each of `slugToTranslationKey`, `slugToAlertType`, and `RETRYABLE_SLUGS` — `GITLAB_TOKEN_MISSING` and `GITLAB_AUTH_FAILED` as non-retryable `warning`, `GITLAB_RATE_LIMIT` as retryable `info`
    - Union and maps change in the same task: the maps are typed `Record<CorrelationStatusSlug, …>`, so widening one without the other fails `tsc`
    - _Requirements: 9.3, 9.4_

  - [x] 15.4 Land the mapping API contract change in one step
    - `api/gitApi.ts`: `deleteGitMapping(userId, provider)` loses its third argument; `createGitMapping` returns `GitMappingCreated`
    - `components/GitMappingForm.tsx`: `onSubmit` return type becomes `Promise<GitMappingCreated>`; the success branch picks between `gitMappingForm.successReplaced` (interpolating `previous` and `current`) and `gitMappingForm.success`
    - `pages/GitSettingsPage.tsx`: `handleDeleteMapping` calls `deleteGitMapping(m.userId, m.provider)` and sets `gitSettings.mappings.success.removed`; `handleCreateMapping` returns the API result so the form can render the outcome
    - Grouped deliberately: `tsc` fails from the moment the union or the arity changes until every call site follows, so these edits land together rather than leaving the build broken across tasks
    - _Requirements: 9.6, 9.7_

  - [x]* 15.5 Write fast-check property test for the slug maps
    - **Property 20: Frontend slug map totality**
    - **Validates: Requirements 9.3, 9.4**
    - Finite domain (the slug union × supported locales), so the generator enumerates rather than samples

  - [x]* 15.6 Write fast-check property test for catalog key parity
    - **Property 21: Locale catalog key parity**
    - **Validates: Requirements 9.5, 9.8**
    - Includes the no-key-is-a-dot-prefix-of-another check for the five new keys

  - [x]* 15.7 Write frontend component example tests (Vitest + Testing Library)
    - `GitRepoForm` and `GitMappingForm` expose exactly `github` and `gitlab`, labelled from `git.provider.*` and derived from `buildProviderOptions` rather than a local literal (9.1, 9.2)
    - `GitSettingsPage` remove action: assert the mocked `deleteGitMapping` received exactly the row's `userId` and `provider` — `tsc` enforces the arity, this pins the values (9.6)
    - `GitMappingForm` with `replaced: true` and a `previousGitUsername` interpolates both usernames; with `replaced: false` renders the plain success message. Run in both locales, since the placeholder positions differ between `en` and `pt-BR` (9.7)
    - The mappings panel renders `gitSettings.mappings.success.removed` after a successful delete
    - _Requirements: 9.1, 9.2, 9.6, 9.7_

- [x] 16. Documentation and infrastructure hardening
  - [x] 16.1 Add the `docs/changelog.md` entry
    - One entry for this change set, covering the GitLab provider, the mapping key change and its migration, and the breaking delete-route change
    - _Requirements: 2.11, 11.1_

  - [x] 16.2 Record the operator prerequisites in `docs/deploy.md`, with a pointer from `README.md`
    - `docs/deploy.md` carries the detail, alongside the deployment steps: the cold-window prerequisite for the deployment that runs the migration — the first deploy of this feature and any later deploy that bumps `MigrationVersion` — scoped explicitly so it does not read as a standing requirement for every KCA deploy
    - `docs/deploy.md`: the `MigrationVersion` re-run lever and the summary log record an operator checks to tell a complete run from a truncated one
    - `README.md`: a short pointer to the prerequisite, not a duplicate of it, so the two cannot drift. The README's job is to make a deployer aware the constraint exists; `deploy.md` carries the procedure
    - `docs/deploy.md`: AgentCore-to-GitLab network reachability — the agent container makes the outbound call, so a GitLab instance reachable only inside a private network is not reachable at all. `GITLAB_REQUEST_FAILED` on every attempt is that signature
    - `docs/deploy.md`: TLS — verification stays on, so a private CA or self-signed certificate fails and surfaces as `GITLAB_REQUEST_FAILED`. Operators install a trusted certificate on the instance. Both of these are environment preconditions a deployer satisfies before the integration works at all, which is why they sit with the deployment steps rather than in the README
    - These travel with the code because this is an `aws-samples` repository — a third-party deployer was not party to the decisions that established them
    - _Requirements: 10.2, 10.3, 11.1_

  - [x] 16.3 Update both Git diagrams for the second provider
    - `docs/git-correlation.drawio` → re-export `docs/git-kiro-correlation-flow.png`. This is the primary target: it depicts the Kiro-to-Git correlation flow, the exact flow this feature makes provider-aware. Add the second provider egress path from the AgentCore runtime, and generalize any node or label that names GitHub as the only Git source
    - `docs/architecture.drawio` → re-export `docs/architecture.png`. The system-level view gains the GitLab egress path alongside the existing GitHub one
    - `docs/architecture.md`: update the prose wherever it describes the Git integration as GitHub-only
    - Grep `docs/**` for prose still asserting GitHub-only Git support — `features.md` and `security.md` are plausible additional sites, so do not treat the list above as exhaustive
    - Commit each `.drawio` source alongside its re-exported `.png`, with descriptive `alt` text, per the project's diagram convention. A diagram showing a GitHub-only correlation path while the code supports two providers is the stale-documentation failure the steering rules call out as worse than missing documentation
    - _Requirements: 5.1, 5.2, 10.4_

  - [x]* 16.4 Narrow the agent's SSM statement
    - `AgentCoreAppPermissionsPolicy` / `SSMGitTokenAccess`: resource from `parameter/kiro-cost-analyzer/*` to `parameter/kiro-cost-analyzer/git-tokens/*`, and drop `ssm:GetParametersByPath` — once `_fetch_token_from_ssm` is gone the agent only calls `GetParameter` on a git-token path
    - _Requirements: 3.4_

  - [x]* 16.5 Narrow the worker's SSM statement
    - Same treatment for the `CorrelationWorkerFunction` `SSMAccess` statement, which is also prefix-wide
    - _Requirements: 3.1_

- [x] 17. Final checkpoint - Full build and test suite
  - Run the Python suite (both property files included), `npm run build` (which runs `check-locales.ts` then `tsc -b`), `npm run test`, and `cfn-lint`. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Test tasks are deliberately **not** optional where a defect produces a plausible-looking wrong answer instead of an error: Property 6 (uniqueness invariant), Property 7 (repo-scoped token resolution), Property 22 (the `begins_with` regression that silently returns empty), and Properties 23, 24, 25 (the migration).
- Each task references the requirements it implements for traceability.
- The design's Manual Verification steps need a real GitLab CE instance and a real deployment. They are operator steps, not coding tasks, and are intentionally absent from this list. The one worth flagging is step 3: after deploying over an environment holding legacy mappings, read the migrator's summary log record and confirm `truncated` is false and `unconverted` is zero. A truncated run reports `SUCCESS`, leaves a green stack, and leaves a correct-looking subset of mappings, so the data alone cannot tell you the migration finished.
- Property tests validate universal correctness properties; unit tests cover the concrete branches properties cannot express — a specific call kwarg, a specific empty-input branch, a specific two-step teardown.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["3.1", "3.2", "3.3", "13.1", "15.1", "15.2"] },
    { "id": 2, "tasks": ["4.1", "5.1", "8.1", "13.2", "13.3", "15.3"] },
    { "id": 3, "tasks": ["5.2", "6.1", "13.4", "15.4", "3.4"] },
    { "id": 4, "tasks": ["6.2", "13.5", "3.5", "5.3"] },
    { "id": 5, "tasks": ["8.2", "10.1", "4.2", "6.3", "4.4"] },
    { "id": 6, "tasks": ["10.2", "4.3", "8.3", "6.4", "5.4"] },
    { "id": 7, "tasks": ["11.1", "10.3", "8.4", "8.6", "13.14"] },
    { "id": 8, "tasks": ["10.4", "8.5", "10.8", "11.3", "15.5"] },
    { "id": 9, "tasks": ["10.5", "15.6", "15.7", "16.1"] },
    { "id": 10, "tasks": ["10.6", "16.2"] },
    { "id": 11, "tasks": ["10.7", "16.3"] },
    { "id": 12, "tasks": ["11.2"] },
    { "id": 13, "tasks": ["13.6"] },
    { "id": 14, "tasks": ["13.7"] },
    { "id": 15, "tasks": ["13.8"] },
    { "id": 16, "tasks": ["13.9"] },
    { "id": 17, "tasks": ["13.10"] },
    { "id": 18, "tasks": ["13.11"] },
    { "id": 19, "tasks": ["13.12"] },
    { "id": 20, "tasks": ["13.13"] },
    { "id": 21, "tasks": ["16.4"] },
    { "id": 22, "tasks": ["16.5"] }
  ]
}
```
