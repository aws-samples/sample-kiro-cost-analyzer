# Implementation Plan: S3 Source Config Read-Only

## Overview

This plan removes the "reconfigure source bucket at runtime" write path (`PUT /api/config/bucket`, `PUT /api/config/prompts-prefix`) and the `ValidateSourceBucket` wildcard IAM statement it required, replacing the Settings page's editable bucket/prefix fields with read-only display. `SourcePrefix` and `PromptsPrefix` become required deploy-time parameters. The implementation language is Python 3.13 (backend, per existing project convention) and TypeScript/React (frontend, per existing project convention) — the design document already specifies these languages directly, with no pseudocode requiring a language choice.

## Tasks

- [x] 1. Remove the backend write path for bucket/prompts-prefix configuration
  - [x] 1.1 Remove the `PUT /api/config/bucket` and `PUT /api/config/prompts-prefix` dispatch branches from `backend/handler.py`
    - Delete both `if http_method == "PUT" and path == ...` blocks (including their admin-check guards) from `_route`, so both paths fall through to the existing generic 404 `NotFound` response
    - Leave every other branch in `_route` (including the other `/api/config/*` admin-only branches) unmodified
    - _Requirements: 3.1, 3.4, 4.1, 4.4_

  - [x] 1.2 Remove `handle_put_config_bucket` and `handle_put_config_prompts_prefix` from `backend/handlers/config_handler.py`
    - Delete both functions in full, plus `_get_s3_client` (now unused since it was `handle_put_config_bucket`'s only caller)
    - Update the module docstring to drop the removed routes from its description
    - Leave `_get_ssm_client`, `_get_parameter`, `handle_get_config`, and every other `handle_put_config_*`/`handle_get_schedule` function unmodified
    - _Requirements: 3.2, 4.2, 6.2_

  - [x]* 1.3 Remove obsolete tests for the deleted routes and handlers
    - In `tests/test_backend_handler.py`, remove the `TestPutConfigBucket` class
    - In `tests/test_config_handler.py`, remove the `handle_put_config_bucket` import and the `TestHandlePutConfigBucket` class (and any other test cases calling `handle_put_config_prompts_prefix`)
    - Leave `TestGetConfig` and other retained test classes unmodified
    - _Requirements: 7.1, 7.2_

  - [x]* 1.4 Write property test for Property 1 in `tests/test_backend_handler.py`
    - **Property 1: Removed write routes always 404 regardless of request content**
    - **Validates: Requirements 3.1, 3.4, 4.1, 4.4**
    - Use Hypothesis, parameterized over `path in ("/api/config/bucket", "/api/config/prompts-prefix")`, an arbitrary JSON-serializable body (`st.dictionaries`/`st.one_of`), and `groups in ("Admins", "Viewers", "")`; assert `statusCode == 404` and `body["error"] == "NotFound"` for every combination
    - Minimum 100 iterations (`@settings(max_examples=100)`); tag the test class with the comment `# Feature: s3-source-config-readonly, Property 1: Removed write routes always 404 regardless of request content`
    - No AWS calls are needed — invoke the in-memory `lambda_handler`/`_route` directly

  - [x]* 1.5 Write property test for Property 2 in `tests/test_config_handler.py`
    - **Property 2: `GET /api/config` display fields are total and empty-parameter-tolerant**
    - **Validates: Requirements 1.1, 1.6, 2.1, 2.2, 6.1, 6.3**
    - Use Hypothesis against `handle_get_config`, with a mocked SSM client whose `get_parameter` is configured per-call to independently return an arbitrary string, an empty string, or raise, for each of the `bucketName`/`sourcePrefix`/`promptsPrefix` parameter names
    - Assert the returned dict always has `bucketName`, `sourcePrefix`, and `promptsPrefix` present as `str`, equal to the parameter's value when present, and equal to `""` when absent or empty
    - Minimum 100 iterations (`@settings(max_examples=100)`); tag with `# Feature: s3-source-config-readonly, Property 2: GET /api/config display fields are total and empty-parameter-tolerant`
    - Extend the existing `TestHandleGetConfig*` classes rather than replacing them

  - [x]* 1.6 Write a module-shape smoke test confirming the removed functions no longer exist
    - In `tests/test_config_handler.py`, add one example test asserting `hasattr(config_handler, "handle_put_config_bucket") is False` and `hasattr(config_handler, "handle_put_config_prompts_prefix") is False`
    - _Requirements: 3.2, 4.2, 6.2_

- [x] 2. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Remove the `ValidateSourceBucket` IAM grant and update deploy-time parameters in `template.yaml`
  - [x] 3.1 Remove the `ConfigBucketPut` and `ConfigPromptsPrefixPut` API event definitions from the `BackendFunction` resource
    - Delete both `Events` entries (`Path: /api/config/bucket` / `Method: PUT` and `Path: /api/config/prompts-prefix` / `Method: PUT`) in full
    - Leave every other `Events` entry on `BackendFunction` unmodified
    - _Requirements: 3.3, 4.3_

  - [x] 3.2 Remove the `ValidateSourceBucket` IAM statement from the `BackendFunction` `Policies` block
    - Delete the entire `Sid: ValidateSourceBucket` statement, including its `holmes:suppress`/`TODO` comment block, in full
    - Leave every other statement in the `Policies` block unmodified (per the least-privilege review in the design: no other statement grants an action unused by retained code or a resource broader than what retained code accesses)
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 3.3 Remove the `Default: ""` key from `Parameters.SourcePrefix` and `Parameters.PromptsPrefix`
    - Remove only the `Default` line from each parameter definition; leave `Type`, `Description`, and every other parameter (including `SourceBucketName`, which already has no `Default`) unmodified
    - _Requirements: 9.1, 9.2, 9.3, 9.6_

  - [x]* 3.4 Write a template-structure smoke test for `template.yaml`
    - Parse `template.yaml` once (following the existing `tests/test_identity_store_role_template.py` pattern) and assert:
      - No `ValidateSourceBucket` `Sid` under `BackendFunction.Properties.Policies`
      - No `ConfigBucketPut`/`ConfigPromptsPrefixPut` under `BackendFunction.Properties.Events`
      - `Parameters.SourcePrefix` and `Parameters.PromptsPrefix` have no `Default` key
      - `Parameters.SourceBucketName` still has no `Default` key
      - The `Sid: ReadSourceBucket` statements on `ListFilesFunction`/`ParseFunction` are unchanged
    - _Requirements: 3.3, 4.3, 5.1, 9.1, 9.2, 9.3, 9.6_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Make the Settings page bucket/prefix fields read-only
  - [x] 5.1 Remove write-only state and handlers from `frontend/src/pages/SettingsPage.tsx`
    - Remove the `saving` and `savingPrompts` `useState` declarations
    - Remove the `handleSave` and `handleSavePromptsPrefix` functions
    - Add the shared `NOT_CONFIGURED_PLACEHOLDER = '—'` constant and `displayValue(value: string): string` helper (trims the value, returns the placeholder when blank)
    - Keep the `bucketName`/`sourcePrefix`/`promptsPrefix` `useState` setters — they remain populated from `fetchConfig` but are no longer wired to any `onChange` handler
    - Remove the now-unused `Input`, `Form`, `FormField`, and `Button` imports if no longer referenced elsewhere in the file (`Button` is still used by other containers — verify before removing)
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 2.5, 2.6, 2.7_

  - [x] 5.2 Replace the "Source Bucket" container with a read-only key-value display
    - Replace the `Form`/`FormField`/`Input`/`Button` block with a `ColumnLayout columns={2} variant="text-grid"` containing two `Box variant="awsui-key-label"` + `displayValue(...)` pairs for `bucketName` and `sourcePrefix`, matching the pattern already used by the ETL status container
    - _Requirements: 1.1, 1.6_

  - [x] 5.3 Replace the "Prompts Configuration" container with a state-aware read-only display
    - Render a loading indicator (`StatusIndicator type="loading"`) while the page-level `loading` state is true
    - Render an error indicator (`StatusIndicator type="error"`) when a derived `promptsConfigError` (computed from the existing `error` state, not new `useState`) is truthy
    - Otherwise render the `promptsPrefix` label and `displayValue(promptsPrefix)`
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x]* 5.4 Write unit tests for the read-only containers in `frontend/src/pages/__tests__/SettingsPage.test.tsx`
    - Assert the "Source Bucket" and "Prompts Configuration" containers render no `<input>`/`<textarea>` element and no button with the removed `settings.bucket.submit`/`settings.prompts.submit` label text
    - Assert a loading indicator renders in the Prompts Configuration container when the config fetch is pending, instead of a value
    - Assert an error indicator renders (and no prefix text) when the config fetch fails
    - _Requirements: 1.2, 1.3, 1.4, 2.3, 2.4, 2.5, 2.6_

  - [x]* 5.5 Write property test for the frontend counterpart of Property 2 in `frontend/src/pages/__tests__/SettingsPage.test.tsx`
    - **Property 2: `GET /api/config` display fields are total and empty-parameter-tolerant (frontend `displayValue` counterpart)**
    - **Validates: Requirements 1.1, 1.6, 2.1, 2.2**
    - Use fast-check: for an arbitrary string (including empty and whitespace-only strings) supplied as `bucketName`/`sourcePrefix`/`promptsPrefix` in the mocked `GET /api/config` response, assert the rendered container text equals the input value when non-blank, or `'—'` when blank
    - Minimum 100 runs (`fc.assert(fc.property(...), { numRuns: 100 })`); tag with a comment referencing `Feature: s3-source-config-readonly, Property 2`

  - [x]* 5.6 Regenerate the `frontend/src/pages/ptBrSnapshots.test.tsx` snapshot for `SettingsPage`
    - No existing assertion in this file simulates editing the bucket/prefix/prompts-prefix fields, so no removal is needed here
    - Re-run the snapshot test and accept the updated snapshot (no more "Save Configuration"/"Save Prompts Prefix" button text; `'—'` placeholders appear for the empty mocked values)
    - _Requirements: 7.3_

- [x] 6. Remove dead translation keys used only by the removed write path
  - [x] 6.1 Remove the ten dead keys from `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json`
    - Remove: `settings.bucket.submit`, `settings.bucket.nameField.placeholder`, `settings.bucket.sourcePrefixField.placeholder`, `settings.error.bucketNameRequired`, `settings.error.save`, `settings.success.saved`, `settings.prompts.submit`, `settings.prompts.prefixField.placeholder`, `settings.error.savePromptsPrefix`, `settings.success.promptsPrefixSaved`
    - Retain: `settings.bucket.nameField.label`, `settings.bucket.nameField.description`, `settings.bucket.sourcePrefixField.label`, `settings.bucket.sourcePrefixField.description`, `settings.prompts.prefixField.label`, `settings.prompts.prefixField.description`, `settings.bucket.title`, `settings.prompts.title`
    - Keep both catalogs alphabetically sorted after removal (required by `scripts/check-locales.ts`); verify with `npm run check:locales`
    - _Requirements: 7.4, 7.5, 7.6_

  - [x]* 6.2 Write/extend a locale-content smoke test asserting the ten removed keys are absent and the eight retained keys are present in both `en.json` and `pt-BR.json`
    - _Requirements: 7.4, 7.5_

- [x] 7. Checkpoint - Ensure all frontend and locale tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Update security and deploy documentation to reflect the completed fix
  - [x] 8.1 Update `docs/security.md`
    - Remove the "Known finding, planned fix — `s3:ListBucket` wildcard on the source-bucket validation endpoint" heading and its planned-fix paragraph
    - Add a "Resolved finding — source-bucket reconfiguration feature removed" section recording that the write path and `ValidateSourceBucket` statement have been removed, and that changing the source bucket/prefixes now requires a redeploy with updated template parameters
    - _Requirements: 8.1, 8.2_

  - [x] 8.2 Update `docs/changelog.md`
    - Add a new entry under `## Unreleased` describing this change as a security hardening fix, following the reverse-chronological `## vX.Y — Title (YYYY-MM-DD)` heading and bullet-point convention
    - Rewrite the existing `### TODO (planned, not yet implemented) — Remove the source-bucket hot-swap feature` entry under `## v3.3` in place, so it references the completed removal instead of describing it as planned
    - _Requirements: 8.3, 8.4_

  - [x] 8.3 Update the `docs/deploy.md` `--guided` parameter table
    - Change the `SourcePrefix` and `PromptsPrefix` rows from `Required: no` to `Required: yes`, adding a note that an explicitly empty string (`SourcePrefix=""` / `PromptsPrefix=""`) is accepted for a bucket-root deployment
    - Leave the `SourceBucketName`, `AdminEmail`, and `IdentityStoreId` rows unmodified
    - _Requirements: 9.7_

  - [x]* 8.4 Write a doc-content smoke test asserting the documentation updates landed
    - Assert `docs/security.md` no longer contains the string `"Known finding, planned fix"` and does contain a reference to the redeploy requirement
    - Assert `docs/changelog.md` no longer contains `"### TODO (planned, not yet implemented) — Remove the source-bucket hot-swap feature"` verbatim and does contain a new `Unreleased` entry mentioning `ValidateSourceBucket`
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; core implementation tasks (unmarked) are never optional.
- Property tests use Hypothesis (Python, backend) and fast-check (TypeScript, frontend), per `.kiro/steering/development-standards.md` §7.2, with a minimum of 100 iterations each.
- The read path (`GET /api/config`, `handle_get_config`) is not modified by this plan — only write-side code, IAM, deploy parameters, UI controls, tests, translation keys, and documentation are touched.
- No new backend or frontend dependencies are introduced; Hypothesis and fast-check are already project dependencies.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "3.1", "5.1", "6.1", "8.1", "8.2", "8.3"] },
    { "id": 1, "tasks": ["1.3", "3.2", "5.2"] },
    { "id": 2, "tasks": ["1.4", "1.5", "3.3", "5.3"] },
    { "id": 3, "tasks": ["1.6", "3.4", "5.4", "5.6", "6.2", "8.4"] },
    { "id": 4, "tasks": ["5.5"] }
  ]
}
```
