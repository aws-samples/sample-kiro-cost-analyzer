# Requirements Document

## Introduction

The Settings page currently lets an Admin user change the S3 source bucket name, source prefix, and prompts prefix that Kiro Cost Analyzer (KCA) reads Kiro CSV logs and prompt logs from. Supporting this "reconfigure at runtime" capability requires the backend to validate an admin-supplied bucket name via `HeadBucket` before saving it, which in turn requires an `s3:ListBucket` grant scoped to `Resource: "arn:aws:s3:::*"` (see `ValidateSourceBucket` in `template.yaml` and the corresponding note in `docs/security.md`). This wildcard resource scope has been repeatedly flagged by the project's security scanner as excessive: it lets anything running as the Backend Lambda enumerate the existence of any S3 bucket in any AWS account, not only the configured source bucket.

This feature removes the write path entirely. The bucket name, source prefix, and prompts prefix become read-only in the UI — still visible so an Admin can confirm current configuration — and the corresponding write endpoints, handlers, and the `ValidateSourceBucket` IAM statement are removed from the codebase. Changing the source bucket after initial deployment becomes a redeploy operation (new `SourceBucketName`/`SourcePrefix`/`PromptsPrefix` template parameters), which is the accepted trade-off documented in `docs/security.md`.

## Glossary

- **KCA**: Kiro Cost Analyzer — the serverless application for analyzing Kiro usage and costs.
- **Settings_Page**: The `SettingsPage` React component (`frontend/src/pages/SettingsPage.tsx`), specifically the "Source Bucket" (`settings.bucket.*`) and "Prompts Configuration" (`settings.prompts.*`) containers on the "Data" tab.
- **Config_API**: The set of backend routes handled in `backend/handler.py` under `/api/config/*` and their corresponding functions in `backend/handlers/config_handler.py`.
- **Backend_Function**: The `BackendFunction` AWS Lambda resource defined in `template.yaml`, which backs the Config_API.
- **SSM_Parameter_Store**: AWS Systems Manager Parameter Store, holding configuration values under the `/kiro-cost-analyzer/` prefix.
- **ValidateSourceBucket_Statement**: The IAM policy statement with `Sid: ValidateSourceBucket` in the `BackendFunction` resource's `Policies` block in `template.yaml`, granting `s3:ListBucket` on `Resource: "arn:aws:s3:::*"`.
- **Admin**: A Cognito user whose JWT claims include membership in the `Admins` group, as checked by `_is_admin()` in `backend/handler.py`.

## Requirements

### Requirement 1: Read-Only Source Bucket Display

**User Story:** As an Admin, I want to see the currently configured source bucket name and source prefix without being able to edit them from the UI, so that I can confirm configuration without risking an unvalidated or accidental change.

#### Acceptance Criteria

1. THE Settings_Page SHALL display the current bucket name next to its existing "Bucket Name" field label, and the current source prefix next to its existing "Source Prefix" field label, sourced from the existing `GET /api/config` response (`bucketName`, `sourcePrefix` fields), as plain read-only text (for example a Cloudscape `Box`/key-value label), inside the existing "Source Bucket" container.
2. THE Settings_Page SHALL NOT render an `Input`, `Textarea`, or any other editable form control for the bucket name field, under any circumstance.
3. THE Settings_Page SHALL NOT render an `Input`, `Textarea`, or any other editable form control for the source prefix field, under any circumstance.
4. THE Settings_Page SHALL NOT render a "Save Configuration" button (`settings.bucket.submit`) or any other button, including a button whose primary purpose is a different setting, that would submit a write of the bucket name or source prefix.
5. THE Settings_Page and the Config_API SHALL NOT provide any mechanism, in any UI state or application flow, to send a write request for the bucket name or source prefix. THE Settings_Page SHALL NOT make an HTTP request to `PUT /api/config/bucket` because that route SHALL NOT exist (see Requirement 3).
6. IF the `GET /api/config` response returns an empty string for `bucketName` or `sourcePrefix`, THEN THE Settings_Page SHALL display a non-empty placeholder (for example an em dash or a "not configured" label) in place of that value, instead of blank text.

### Requirement 2: Read-Only Prompts Prefix Display

**User Story:** As an Admin, I want to see the currently configured prompts prefix without being able to edit it from the UI, so that I can confirm where prompt logs are read from without risking an accidental change.

#### Acceptance Criteria

1. WHEN THE Settings_Page finishes loading configuration data from `GET /api/config`, THE Settings_Page SHALL display the value of the `promptsPrefix` field as plain read-only text (for example a Cloudscape `Box`/key-value label) inside the existing "Prompts Configuration" container.
2. IF the `promptsPrefix` field returned by `GET /api/config` is an empty string, THEN THE Settings_Page SHALL display a non-empty placeholder (for example an em dash or a "not configured" label) in place of blank text.
3. WHILE the Settings_Page is loading configuration data from `GET /api/config`, THE Settings_Page SHALL display a loading indicator in the "Prompts Configuration" container instead of the prompts prefix value or any editable control.
4. IF the `GET /api/config` request fails, THEN THE Settings_Page SHALL display an error indication in the "Prompts Configuration" container in place of the prompts prefix value, and SHALL NOT display a previously loaded or cached prompts prefix value as if it were the current configuration.
5. THE Settings_Page SHALL NOT render an `Input`, `Textarea`, or any other editable form control for the prompts prefix field, under any circumstance.
6. THE Settings_Page SHALL NOT render a "Save Prompts Prefix" button (`settings.prompts.submit`) or any other button, including a button whose primary purpose is a different setting, that would submit a write of the prompts prefix.
7. THE Settings_Page and the Config_API SHALL NOT provide any mechanism, in any UI state or application flow, to send a write request for the prompts prefix. THE Settings_Page SHALL NOT make an HTTP request to `PUT /api/config/prompts-prefix` because that route SHALL NOT exist (see Requirement 4).

### Requirement 3: Remove Bucket Configuration Write Endpoint

**User Story:** As a security-conscious maintainer, I want the bucket/source-prefix write endpoint removed from the API, so that there is no code path in the Backend_Function that accepts admin-supplied bucket names and validates them against arbitrary S3 buckets.

#### Acceptance Criteria

1. THE Config_API SHALL NOT contain a reachable conditional branch in `backend/handler.py`'s request-dispatch chain (the sequence of `if http_method == ... and path == ...` checks) that matches `PUT /api/config/bucket`; any residual reference to that route MUST NOT be wired into the dispatch chain and MUST NOT be counted as compliant if left as orphaned or unreachable code.
2. THE `backend/handlers/config_handler.py` module SHALL NOT contain the `handle_put_config_bucket` function.
3. THE `template.yaml` `BackendFunction` resource SHALL NOT contain a `ConfigBucketPut` API event definition for `Path: /api/config/bucket`.
4. WHEN a client sends a `PUT /api/config/bucket` request to the Config_API, THE Config_API SHALL fall through to the existing generic "Unknown route" 404 fallback response in `backend/handler.py`, identical in behavior to any other undefined route, regardless of whether any residual `ConfigBucketPut` API Gateway event definition remains configured in `template.yaml`; the 404 behavior is guaranteed by the absence of a matching branch in the Lambda's dispatch chain (Criterion 1), not by API Gateway's own route configuration.

### Requirement 4: Remove Prompts Prefix Write Endpoint

**User Story:** As a security-conscious maintainer, I want the prompts-prefix write endpoint removed from the API, so that there is no remaining code path for modifying S3 source configuration from outside a redeploy.

#### Acceptance Criteria

1. THE Config_API SHALL NOT contain a route for `PUT /api/config/prompts-prefix` in `backend/handler.py`.
2. THE `backend/handlers/config_handler.py` module SHALL NOT contain the `handle_put_config_prompts_prefix` function.
3. THE `template.yaml` `BackendFunction` resource SHALL NOT contain a `ConfigPromptsPrefixPut` API event definition for `Path: /api/config/prompts-prefix`.
4. WHEN a client sends a `PUT /api/config/prompts-prefix` request after removal, THE Config_API SHALL respond through the existing generic "Unknown route" 404 fallback in `backend/handler.py`, returning a 404 status with an error indication that the route was not found.

### Requirement 5: Remove the Overly Broad S3 IAM Permission

**User Story:** As a security-conscious maintainer, I want the wildcard-resource S3 permission removed from the Backend_Function's IAM policy, so that the security scanner finding tied to account-wide bucket enumeration is eliminated rather than merely documented as an accepted trade-off.

#### Acceptance Criteria

1. THE `template.yaml` `BackendFunction` resource's `Policies` block SHALL NOT contain the ValidateSourceBucket_Statement (`Sid: ValidateSourceBucket`, granting `s3:ListBucket` on `Resource: "arn:aws:s3:::*"`).
2. THE `template.yaml` `BackendFunction` resource's `Policies` block, after removing the ValidateSourceBucket_Statement, SHALL NOT contain any statement that grants an IAM Action not used by the retained code paths in `backend/handler.py` and `backend/handlers/*.py`, nor any statement whose `Resource` is broader than what those retained code paths actually access.
3. THIS change SHALL NOT modify the IAM policy of `ListFilesFunction`, `ParseFunction`, or any other Lambda function besides `BackendFunction`.

### Requirement 6: Preserve Read Access to Existing Configuration

**User Story:** As an Admin, I want the current bucket name, source prefix, and prompts prefix to remain visible after this change, so that removing the write capability does not also remove visibility into what is currently configured.

#### Acceptance Criteria

1. THE Config_API SHALL continue to serve `GET /api/config` returning an HTTP 200 response with `bucketName`, `sourcePrefix`, and `promptsPrefix` as string fields populated from SSM_Parameter_Store, unchanged from current behavior.
2. THE `backend/handlers/config_handler.py` module SHALL retain the `handle_get_config` function with its SSM read logic unmodified.
3. IF an SSM parameter for `bucketName`, `sourcePrefix`, or `promptsPrefix` does not exist or is unreadable, THEN THE Config_API SHALL return an empty string for that specific field only, while the `GET /api/config` request still succeeds and the remaining fields retain their actual values, consistent with current `_get_parameter` error-handling behavior. IF an SSM parameter for `bucketName`, `sourcePrefix`, or `promptsPrefix` exists but its stored value is an empty string, THEN THE Config_API SHALL return that actual empty string value for that field, which is observably identical to the non-existent-parameter case but SHALL NOT require the Config_API to distinguish the two cases from the caller's perspective — both are represented as an empty string in the `GET /api/config` response.

### Requirement 7: Remove Dead Code Tied to the Removed Write Path

**User Story:** As a maintainer, I want tests, translation keys, and type fields that only existed to support the removed write path cleaned up, so that the codebase does not carry references to endpoints and UI controls that no longer exist.

#### Acceptance Criteria

1. THE `tests/test_config_handler.py` module SHALL NOT contain test cases that call `handle_put_config_bucket` or `handle_put_config_prompts_prefix`, and SHALL NOT contain an import of `handle_put_config_bucket`.
2. THE `tests/test_backend_handler.py` module SHALL NOT contain test cases that assert admin or non-admin behavior for `PUT /api/config/bucket` or `PUT /api/config/prompts-prefix`, including removal of the `TestPutConfigBucket` test class.
3. THE `frontend/src/pages/__tests__/SettingsPage.test.tsx` and `frontend/src/pages/ptBrSnapshots.test.tsx` files SHALL NOT contain assertions that simulate editing or saving the bucket name, source prefix, or prompts prefix fields.
4. THE `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json` catalogs SHALL NOT contain the following translation keys, which were used exclusively by the removed editable fields and Save actions: `settings.bucket.submit`, `settings.bucket.nameField.placeholder`, `settings.bucket.sourcePrefixField.placeholder`, `settings.error.bucketNameRequired`, `settings.error.save`, `settings.success.saved`, `settings.prompts.submit`, `settings.prompts.prefixField.placeholder`, `settings.error.savePromptsPrefix`, `settings.success.promptsPrefixSaved`.
5. IF a translation key is one of the following shared field labels or descriptions for the retained read-only bucket/prefix display, THEN THE `en.json` and `pt-BR.json` catalogs SHALL retain that key: `settings.bucket.nameField.label`, `settings.bucket.nameField.description`, `settings.bucket.sourcePrefixField.label`, `settings.bucket.sourcePrefixField.description`, `settings.prompts.prefixField.label`, `settings.prompts.prefixField.description`, `settings.bucket.title`, `settings.prompts.title`.
6. AFTER removing translation keys from both catalogs, THE `en.json` and `pt-BR.json` files SHALL be checked by running `npm run check:locales` (backed by `scripts/check-locales.ts`) to confirm identical key sets; IF the removal leaves the two catalogs with mismatched key sets, THEN THE mismatch SHALL be corrected so the key sets are equal.

### Requirement 8: Update Security Documentation

**User Story:** As a maintainer, I want `docs/security.md` updated to reflect that the fix has been implemented, so that the documentation does not continue to describe a resolved finding as an open, planned fix.

#### Acceptance Criteria

1. THE `docs/security.md` file SHALL NOT contain the "Known finding, planned fix — `s3:ListBucket` wildcard on the source-bucket validation endpoint" heading, nor any other text describing the `ValidateSourceBucket` wildcard grant as a currently open, planned-but-not-implemented finding.
2. THE `docs/security.md` file SHALL record that the "reconfigure source bucket" feature (Settings page write fields, `PUT /api/config/bucket`, `PUT /api/config/prompts-prefix`, and the ValidateSourceBucket_Statement) has been removed, and that changing the source bucket now requires a redeploy with updated `SourceBucketName`, `SourcePrefix`, and `PromptsPrefix` template parameters.
3. THE `docs/changelog.md` file SHALL contain a new entry describing this change as a security hardening fix, formatted per the reverse-chronological `## vX.Y — Title (YYYY-MM-DD)` heading and bullet-point convention defined in section 8.4 of the project's development standards, placed under the current version heading.
4. THE `docs/changelog.md` file SHALL NOT retain the existing "### TODO (planned, not yet implemented) — Remove the source-bucket hot-swap feature" entry under the `v3.3` heading in its original planned-but-not-implemented form; that entry SHALL be removed or rewritten to reflect that the feature removal described in Criterion 3's entry has been completed.

### Requirement 9: Mandatory Deploy-Time Bucket and Prefix Parameters

**User Story:** As a person deploying KCA, I want the source bucket, source prefix, and prompts prefix to be required inputs at deploy time, so that once the runtime "reconfigure at runtime" path is removed (Requirements 1–4), the deployment itself cannot produce a stack with an unset source location, and the retained least-privilege S3 read permissions are scoped against a bucket name the operator explicitly provided rather than an implicit default.

#### Acceptance Criteria

1. THE `template.yaml` `Parameters.SourceBucketName` definition SHALL remain a required parameter (`Type: String`, no `Default` key), consistent with its current definition; this requirement introduces no change to `SourceBucketName`'s optionality.
2. THE `template.yaml` `Parameters.SourcePrefix` definition SHALL NOT contain a `Default` key, so that `sam deploy` fails parameter validation if `SourcePrefix` is omitted from `parameter_overrides` or the guided-deploy prompts.
3. THE `template.yaml` `Parameters.PromptsPrefix` definition SHALL NOT contain a `Default` key, so that `sam deploy` fails parameter validation if `PromptsPrefix` is omitted from `parameter_overrides` or the guided-deploy prompts.
4. IF `parameter_overrides` or the guided-deploy prompts explicitly supply `SourcePrefix=""` and/or `PromptsPrefix=""` (for example because Kiro CSV logs or prompt logs are stored at the root of their respective bucket, with no sub-prefix), THEN THE `sam deploy` parameter validation SHALL accept the explicitly-empty value and SHALL NOT reject it as missing. IF `SourcePrefix` and/or `PromptsPrefix` are omitted entirely from `parameter_overrides` and the guided-deploy prompts (as opposed to being explicitly set to an empty string), THEN THE `sam deploy` parameter validation SHALL reject the deploy for each omitted parameter; an omission SHALL NOT be treated as equivalent to an explicitly-supplied empty string, and no implicit empty-string default SHALL be substituted for either parameter.
5. THE `samconfig.toml` `default.deploy.parameters.parameter_overrides` value SHALL continue to include explicit, non-omitted `SourceBucketName`, `SourcePrefix`, and `PromptsPrefix` entries after this change, so the project's own default deploy profile remains valid under the new parameter requirements.
6. THE removal of the `Default: ""` key from `SourcePrefix` and `PromptsPrefix` SHALL NOT alter the `Sid: ReadSourceBucket` IAM statements on `ListFilesFunction` and `ParseFunction` in `template.yaml`, which are scoped using `SourceBucketName` only (`arn:aws:s3:::${SourceBucketName}` and `arn:aws:s3:::${SourceBucketName}/*`) and do not reference `SourcePrefix` in their `Resource` today; narrowing those statements further, if desired, is out of scope for this requirement.
7. THE `docs/deploy.md` "Template parameters `--guided` asks for" table, which currently marks `SourcePrefix` and `PromptsPrefix` as `Required: no`, SHALL be updated to mark `SourcePrefix` and `PromptsPrefix` as required, with an accompanying note that an explicitly empty string (`SourcePrefix=""` / `PromptsPrefix=""`) is an accepted value for a bucket-root deployment, consistent with Criterion 4.
