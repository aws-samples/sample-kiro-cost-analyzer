# Implementation Plan — Cross-Account IAM Identity Center Access

## Overview

This plan delivers cross-account IAM Identity Center name resolution behind an optional `IdentityStoreRoleArn` parameter, reusing the STS AssumeRole pattern already proven by the cross-account S3 feature (`.kiro/specs/cross-account-s3-access/`). Tasks are ordered for incremental, testable validation: infrastructure first, then the STS helper, configuration, the resolver wiring, the Parse handler integration, the backend endpoint, the IDC helper template and Makefile target, the frontend Settings field, and finally the property-based regression suite, i18n checks, and documentation. Each checkpoint lets the developer run the newly-written tests before moving on to the next layer.

Tasks marked with `*` are optional — they extend property-based coverage (more Hypothesis iterations, shrink-guided edge cases), add CI smoke tests for the new helper template, and record an operator walkthrough. The MVP is complete without them; the pt-BR snapshot regression and the alphabetized-i18n-key parity check are **not** optional.

## Tasks

- [x] 1. CloudFormation infrastructure — parameter, condition, SSM resource, env vars, IAM policy, API route
  - [x] 1.1 Add `IdentityStoreRoleArn` parameter, `HasIdentityStoreRoleArn` condition, and `IdentityStoreRoleArnParameter` SSM resource in `template.yaml`
    - Add the `IdentityStoreRoleArn` parameter (`Type: String`, `Default: ""`, `Description` matching the `SourceBucketRoleArn` style) in the `Parameters` section
    - Add `HasIdentityStoreRoleArn: !Not [!Equals [!Ref IdentityStoreRoleArn, ""]]` to the `Conditions` section, next to `HasSourceBucketRoleArn`
    - Create the SSM `AWS::SSM::Parameter` resource `IdentityStoreRoleArnParameter` at path `/kiro-cost-analyzer/identity-store-role-arn` with `Value: !If [HasIdentityStoreRoleArn, !Ref IdentityStoreRoleArn, "NONE"]`
    - _Requirements: 1.1, 1.2, 1.3, 1.7_

  - [x] 1.2 Add `SSM_IDENTITY_STORE_ROLE_ARN` env var to `ParseFunction` and `BackendFunction`
    - Add `SSM_IDENTITY_STORE_ROLE_ARN: /kiro-cost-analyzer/identity-store-role-arn` to `ParseFunction.Environment.Variables`
    - Add the same env var to `BackendFunction.Environment.Variables`
    - Do NOT add it to `ListFilesFunction` — name resolution runs only in Parse
    - _Requirements: 1.4, 11.7_

  - [x] 1.3 Add the conditional `sts:AssumeRole` policy statement on `ParseFunction`
    - Append a second `!If [HasIdentityStoreRoleArn, Statement: [...], !Ref "AWS::NoValue"]` block to `ParseFunction.Policies`, mirroring the existing `HasSourceBucketRoleArn` block
    - `Sid: AssumeIdentityStoreRole`, `Action: [sts:AssumeRole]`, `Resource: !Ref IdentityStoreRoleArn` (no wildcards)
    - Keep the existing inline `IdentityCenterAccess` statement (`identitystore:DescribeUser`, `identitystore:ListUsers`, `Resource: "*"`) unchanged so single-account mode still works when the operator toggles the ARN off at runtime
    - _Requirements: 1.5, 1.6, 7.3, 9.2_

  - [x] 1.4 Add the API Gateway PUT event for the new endpoint on `BackendFunction`
    - Add a new `Events` entry `ConfigIdentityStoreRoleArnPut` of type `Api`, `Path: /api/config/identity-store-role-arn`, `Method: PUT`, `RestApiId: !Ref ApiGateway`, following the exact shape of `ConfigSourceBucketRoleArnPut`
    - _Requirements: 11.2_

  - [x] 1.5 Checkpoint — run `sam validate`
    - Execute `sam validate` (and `sam validate --lint` if available). Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.7_

- [x] 2. STS session helper — extract shared primitives and add `get_identity_store_client`
  - [x] 2.1 Refactor `etl/sts_session.py` to extract `_build_session_name` and `_assume_role`
    - Extract the RoleSessionName builder into a private `_build_session_name() -> str` that returns `f"kiro-etl-{os.environ.get('AWS_LAMBDA_FUNCTION_NAME', 'unknown')}"`
    - Extract the `sts:AssumeRole` call, the structured-logger success log, and the AccessDenied hint log into a private `_assume_role(role_arn: str, logger: StructuredLogger) -> dict[str, str]`
    - Rewrite `get_s3_client` to call `_assume_role` instead of inlining the STS logic — public signature and observable behavior MUST be unchanged
    - Keep the existing `try/except ImportError` guard for `StructuredLogger`
    - _Requirements: 3.7, 8.3, 8.4, 9.5, 9.6_

  - [x] 2.2 Add `get_identity_store_client(role_arn, correlation_id="")` to `etl/sts_session.py`
    - Return `None` when `role_arn` is empty or `None` (single-account fallback)
    - Otherwise call `_assume_role(role_arn, logger)` and build `boto3.client("identitystore", aws_access_key_id=..., aws_secret_access_key=..., aws_session_token=...)` from the returned credentials
    - Use `DurationSeconds=3600` (enforced inside `_assume_role`) and the shared `_build_session_name()`
    - Propagate exceptions raised by `_assume_role` so Step Functions retries apply
    - Docstring MUST document the `None` return for empty input and the `ClientError` propagation contract
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 9.1, 9.5, 9.6_

  - [x] 2.3 Write unit tests for `get_identity_store_client` in `tests/test_sts_session.py`
    - Test that `role_arn=""` and `role_arn=None` both return `None` and do NOT call STS
    - Test that a non-empty ARN returns an object whose `meta.service_model.service_name == "identitystore"` (moto / mocked boto3)
    - Test the `AccessDeniedException` path logs via `StructuredLogger` and re-raises
    - Test the `RoleSessionName` format (`kiro-etl-{AWS_LAMBDA_FUNCTION_NAME}`) and `DurationSeconds=3600`
    - Assert that the refactored `get_s3_client` still produces an `s3` client and still returns `None` for empty ARN (regression guard for task 2.1)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 8.1, 8.3, 8.4, 9.1, 9.5, 9.6_

- [x] 3. `EtlConfig` extension — new field and SSM read with `NONE` normalization
  - [x] 3.1 Add `identity_store_role_arn` to `EtlConfig` in `etl/config.py`
    - Add the `identity_store_role_arn: str` field to the frozen dataclass, positioned after `source_bucket_role_arn`
    - Inside `get_config()`, read the SSM parameter path from `os.environ.get("SSM_IDENTITY_STORE_ROLE_ARN", "")`, normalize the sentinel `"NONE"` to `""`, and fall back to `""` on any exception (broad-except, matching the `source_bucket_role_arn` pattern exactly)
    - Pass the new field into the `EtlConfig(...)` constructor
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 7.4_

  - [x] 3.2 Write unit tests for the new SSM read in `tests/test_etl_config.py`
    - Case 1: env var `SSM_IDENTITY_STORE_ROLE_ARN` unset → `identity_store_role_arn == ""`
    - Case 2: SSM returns `""` → `identity_store_role_arn == ""`
    - Case 3: SSM returns `"NONE"` → `identity_store_role_arn == ""`
    - Case 4: SSM returns a valid ARN → `identity_store_role_arn` equals the ARN verbatim
    - Case 5: SSM `get_parameter` raises → `identity_store_role_arn == ""` and `get_config()` still returns successfully
    - Ensure existing tests for the other fields keep passing after the new field is appended to the dataclass
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 7.4_

- [x] 4. Name resolver integration — harden the `identity_client` injection seam and log AccessDenied
  - [x] 4.1 Document and harden the injection seam in `etl/user_name_resolver.py`
    - Expand the `resolve_user_names` docstring to describe the cross-account contract (`None` → default client, non-`None` → used verbatim for `DescribeUser`) referencing Requirements 4.2, 4.4, 5.1
    - Extend the `DescribeUser` `except Exception` branch with an AccessDenied-specific log path that includes `userId` and the hint `"Check the Identity_Store_Role permissions (identitystore:DescribeUser) in the IDC account."`
    - Preserve the existing tolerant return of `("", "")` on any resolution failure (Requirement 7.5)
    - _Requirements: 4.2, 4.4, 5.1, 5.2, 5.3, 5.4, 7.5, 8.2_

  - [x] 4.2 Document the forwarding guarantee in `etl/utils/name_resolver.py`
    - Expand the `resolve_names` docstring to state that `identity_client` is forwarded to `resolve_user_names` verbatim with no transformation (Requirement 4.5) — no code change is required
    - _Requirements: 4.5, 7.5_

  - [x] 4.3 Write unit tests for the resolver in `tests/test_user_name_resolver.py` and `tests/test_name_resolver.py`
    - Test `resolve_user_names` with `identity_client=None` (default client is built; asserted via `boto3.client` mock)
    - Test `resolve_user_names` with an injected mock client — only the injected client's `describe_user` is called
    - Test the AccessDenied log path emits a record containing `userId` and the permission-hint string, and that the function still returns `("", "")` for that userId
    - Test `resolve_names` forwards `identity_client` to `resolve_user_names` without transformation
    - _Requirements: 4.2, 4.4, 4.5, 5.3, 7.5, 8.2_

- [x] 5. Parse handler wiring — build the cross-account client and pass it to `resolve_names`
  - [x] 5.1 Wire `get_identity_store_client` into `etl/parse_handler.py`
    - Extend the existing import block to also import `get_identity_store_client` (both the relative and absolute branches of the `try/except ImportError`)
    - After `get_config()` and after the existing `get_s3_client` call, build `identity_client = get_identity_store_client(cfg.identity_store_role_arn, correlation_id=correlation_id)` inside a `try/except Exception` that sets `identity_client = None` on failure (Requirement 8.5 fallback)
    - Pass `identity_client=identity_client` to `resolve_names(...)` in the existing `if user_ids:` block
    - Do NOT remove or change the existing `get_s3_client` call — the two cross-account features are independent
    - _Requirements: 4.1, 4.2, 4.3, 7.1, 7.2, 8.5_

  - [x] 5.2 Write unit tests for Parse in `tests/test_parse_handler.py`
    - Cross-account mode: `cfg.identity_store_role_arn` is non-empty → `get_identity_store_client` is called with that ARN and the correlation ID, and the returned mock is forwarded into `resolve_names(identity_client=...)`
    - Single-account mode: `cfg.identity_store_role_arn` is `""` → `get_identity_store_client` returns `None` and `resolve_names` receives `identity_client=None`
    - Fallback: when `get_identity_store_client` raises, `parse_handler` still completes and calls `resolve_names(identity_client=None)`
    - Ensure existing Parse tests (S3 cross-account, single-account) keep passing
    - _Requirements: 4.1, 4.3, 7.1, 7.2, 8.5_

  - [x] 5.3 Checkpoint — run ETL pipeline tests
    - Execute `pytest tests/test_sts_session.py tests/test_etl_config.py tests/test_user_name_resolver.py tests/test_name_resolver.py tests/test_parse_handler.py -v`. Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 2.1, 3.1, 4.1, 4.2, 4.3, 4.5, 5.1, 7.1, 7.2, 8.5_

- [x] 6. Backend config handler — GET extension and new PUT endpoint
  - [x] 6.1 Extend `handle_get_config` in `backend/handlers/config_handler.py`
    - Read the SSM parameter path from `os.environ.get("SSM_IDENTITY_STORE_ROLE_ARN", "/kiro-cost-analyzer/identity-store-role-arn")`
    - Call the existing `_get_parameter(ssm, ...)` helper, then normalize `"NONE"` → `""`, exactly as done for `sourceBucketRoleArn`
    - Add `"identityStoreRoleArn": identity_store_role_arn` to the returned dict
    - _Requirements: 11.1, 12.3, 12.4_

  - [x] 6.2 Add `handle_put_config_identity_store_role_arn(body, ssm_client=None)` to `backend/handlers/config_handler.py`
    - Reuse the module-level `_ARN_PATTERN = re.compile(r"^arn:aws:iam::\d{12}:role/.+$")` — do NOT introduce a duplicate constant
    - Strip the input, allow empty, reject non-empty non-matches with `status: "error"` and the English message `"Invalid ARN format. Expected: arn:aws:iam::<account-id>:role/<role-name>"`
    - On valid or empty input, persist via `ssm.put_parameter(Name=..., Value=role_arn or "NONE", Type="String", Overwrite=True)` using `os.environ.get("SSM_IDENTITY_STORE_ROLE_ARN", "/kiro-cost-analyzer/identity-store-role-arn")`
    - Return `status: "valid"` with message `"Identity Store role ARN saved successfully"` (non-empty) or `"Cross-account Identity Store mode disabled"` (empty)
    - All human-readable strings MUST be in English (banned-strings regression below)
    - _Requirements: 11.1, 11.4, 11.5, 11.6, 12.1, 12.2_

  - [x] 6.3 Add the admin-gated route in `backend/handler.py`
    - Add a new branch `if http_method == "PUT" and path == "/api/config/identity-store-role-arn":` right after the existing `/api/config/source-bucket-role-arn` branch
    - Gate with `_is_admin(claims)` → `403 Forbidden` with English `message: "Admin access required"`
    - On authorized callers, invoke `config_handler.handle_put_config_identity_store_role_arn(body)` and return `_build_response(200, result)`
    - Do NOT introduce the pt-BR string `"Acesso restrito a administradores"` on the new route — use the English variant so the banned-strings regression passes on the new code path
    - _Requirements: 11.2, 11.3_

  - [x] 6.4 Write unit tests in `tests/test_config_handler.py` and `tests/test_backend_handler.py`
    - `handle_get_config`: returns `identityStoreRoleArn == ""` for SSM sentinel `"NONE"`; returns the ARN verbatim for valid values; returns `""` on SSM exception
    - `handle_put_config_identity_store_role_arn`: valid ARN → persists the ARN, returns `status: "valid"`; empty input → persists `"NONE"`, returns the "disabled" message; invalid ARN → returns `status: "error"` and does NOT call `put_parameter`
    - Assert all `message` strings are English (no pt-BR chars like `ã`, `ç`, `õ`)
    - Routing: admin caller → 200 via handler; non-admin → 403 with English message; non-admin path never reaches the handler
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3, 12.4_

  - [x] 6.5 Checkpoint — run backend tests
    - Execute `pytest tests/test_config_handler.py tests/test_backend_handler.py -v`. Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3, 12.4_

- [x] 7. IDC helper CloudFormation template
  - [x] 7.1 Create `identity-store-role.yaml` at the repository root
    - `AWSTemplateFormatVersion: '2010-09-09'`, description pointing at the IDC account deployment
    - Parameters: `KiroAccountId` (required, `AllowedPattern: "\\d{12}"`) and `IdentityStoreId` (optional, default `""`, documented as informational only because `identitystore` APIs do not support resource-level permissions)
    - Resource `CrossAccountIdentityStoreRole` (`AWS::IAM::Role`) with `RoleName: kiro-cost-analyzer-identity-store-read`
    - Trust policy: `Principal.AWS: !Sub "arn:aws:iam::${KiroAccountId}:root"`, `Action: sts:AssumeRole`, `Condition.StringEquals.aws:PrincipalAccount: !Ref KiroAccountId`
    - Inline policy `kiro-identity-store-read` with statement `Sid: IdentityStoreReadOnly`, `Action: [identitystore:DescribeUser, identitystore:ListUsers]`, `Resource: "*"` (and no other actions)
    - `Outputs.IdentityStoreRoleArn` with `Value: !GetAtt CrossAccountIdentityStoreRole.Arn` and an exported name `!Sub "${AWS::StackName}-IdentityStoreRoleArn"`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 9.3, 9.4_

  - [x] 7.2 Write a template-parse regression test in `tests/test_identity_store_role_template.py`
    - Load `identity-store-role.yaml` with `yaml.safe_load` (or the project's existing CFN yaml loader)
    - Assert the role name is exactly `kiro-cost-analyzer-identity-store-read`
    - Assert the inline policy's `Action` set equals `{"identitystore:DescribeUser", "identitystore:ListUsers"}` — no extra actions, especially no `CreateUser`, `UpdateUser`, `DeleteUser`, or any `identitystore:*Group*` action
    - Assert the trust policy `Condition.StringEquals["aws:PrincipalAccount"]` refers to `KiroAccountId` (pinned by parameter)
    - Assert `Outputs.IdentityStoreRoleArn` exists and exports `${AWS::StackName}-IdentityStoreRoleArn`
    - _Requirements: 6.4, 6.5, 6.6, 6.7, 6.8, 9.3, 9.4_

- [x] 8. Makefile — `deploy-identity-store-role` target
  - [x] 8.1 Add the `deploy-identity-store-role` target to `Makefile`
    - Declare the new variables `IDC_ACCOUNT_PROFILE ?=`, `IDENTITY_STORE_ID ?=`, `IDC_ROLE_STACK_NAME ?= kiro-identity-store-role` (do NOT redeclare `KIRO_ACCOUNT_ID` — it is already defined for `deploy-source-role`)
    - Guard with `ifndef IDC_ACCOUNT_PROFILE` and `ifndef KIRO_ACCOUNT_ID`, printing a `$(error ...)` that enumerates the required parameters and the usage example
    - Run `aws cloudformation deploy --template-file identity-store-role.yaml --stack-name $(IDC_ROLE_STACK_NAME) --capabilities CAPABILITY_NAMED_IAM --profile $(IDC_ACCOUNT_PROFILE) --parameter-overrides KiroAccountId=$(KIRO_ACCOUNT_ID) IdentityStoreId=$(IDENTITY_STORE_ID)`
    - On success, print the `IdentityStoreRoleArn` output via `aws cloudformation describe-stacks ... --query "Stacks[0].Outputs[?OutputKey=='IdentityStoreRoleArn'].OutputValue" --output text`
    - Add the new target to the `.PHONY` declaration
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_

- [x] 9. Frontend Settings page — field, i18n, API call, and tests
  - [x] 9.1 Extend the `AppConfig` interface and `SettingsPage` state
    - Add `identityStoreRoleArn?: string` to the `AppConfig` interface in `frontend/src/types/index.ts`
    - In `frontend/src/pages/SettingsPage.tsx`, add a `useState<string>("")` slot for `identityStoreRoleArn`
    - Populate it from the `GET /api/config` response inside the existing `fetchConfig` effect, mirroring the `sourceBucketRoleArn` assignment
    - _Requirements: 11.1, 11.8, 11.9_

  - [x] 9.2 Add the Cloudscape `FormField` + `Input` + Save button for the Identity Store role ARN
    - Place the new `FormField` immediately after the existing `sourceBucketRoleArn` `FormField` inside the same `SpaceBetween`
    - Use `t("settings.identityStoreRoleArn.label")`, `t("settings.identityStoreRoleArn.description")`, `t("settings.identityStoreRoleArn.placeholder")` — no hardcoded strings
    - Save button calls `put("/api/config/identity-store-role-arn", { identityStoreRoleArn })` via the centralized API client; on success render the Cloudscape `StatusIndicator` using `t("settings.identityStoreRoleArn.status.success")`, on error use `t("settings.identityStoreRoleArn.status.error")`
    - Allow empty submission to disable cross-account mode
    - _Requirements: 11.2, 11.8, 11.9, 11.10_

  - [x] 9.3 Add the seven new i18n keys to `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json`
    - Keys (sorted alphabetically, both catalogs must declare all seven):
      - `settings.identityStoreRoleArn.description`
      - `settings.identityStoreRoleArn.label`
      - `settings.identityStoreRoleArn.placeholder`
      - `settings.identityStoreRoleArn.save`
      - `settings.identityStoreRoleArn.status.error`
      - `settings.identityStoreRoleArn.status.success`
      - `settings.identityStoreRoleArn.status.validating`
    - English values describe the cross-account IDC role; pt-BR values are the faithful translations
    - Both files remain alphabetically sorted (the `scripts/check-locales.ts` build step enforces this)
    - _Requirements: 11.10_

  - [x] 9.4 Write Vitest coverage in `frontend/src/pages/__tests__/SettingsPage.test.tsx`
    - Render the page with a mocked `GET /api/config` that includes `identityStoreRoleArn`; assert the input displays the fetched value
    - Typing into the field and clicking Save issues `PUT /api/config/identity-store-role-arn` with the current value in the body
    - Successful save renders the i18n-backed success message; failed save renders the i18n-backed error message
    - Clearing the field and saving submits `{ identityStoreRoleArn: "" }`
    - _Requirements: 11.2, 11.8, 11.9_

  - [x] 9.5 Extend the pt-BR snapshot regression test in `frontend/src/__tests__/localeSwitchIntegration.test.tsx`
    - Switch locale to `pt-BR`, render the Settings page, and snapshot the Identity Store role ARN field block
    - The rendered label, description, placeholder, and Save button MUST resolve from `pt-BR.json` — any hardcoded English leaks fail the test
    - _Requirements: 11.10_

- [ ] 10. Property-based tests — one sub-task per design property (P1–P6)
  - [ ]* 10.1 Property 1 — SSM persistence round-trip for valid ARNs (`tests/test_properties_identity_store_role.py`)
    - `# Feature: cross-account-identity-center, Property 1: ARN persistence round-trip`
    - Hypothesis strategy: generate valid ARNs matching `r"^arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@_-]{1,64}$"`
    - Invariant: for any generated ARN, `handle_put_config_identity_store_role_arn({"identityStoreRoleArn": arn})` followed by `handle_get_config()` returns the same ARN verbatim (using moto-backed SSM)
    - `@settings(max_examples=100)` minimum
    - _Property: 1_
    - _Requirements: 12.1, 12.3_

  - [ ]* 10.2 Property 2 — Empty round-trip and `NONE` sentinel equivalence
    - `# Feature: cross-account-identity-center, Property 2: Empty round-trip with NONE sentinel`
    - Invariant: `PUT` of `""` persists the SSM value `"NONE"`, and `GET` returns `""`; `PUT` of `"NONE"` string literal is rejected as invalid (does not match the ARN regex) — the sentinel is only written by the handler, never accepted as input
    - Hypothesis strategy: fixed `""` plus a small set of whitespace-only strings that strip to `""`
    - `@settings(max_examples=100)` minimum
    - _Property: 2_
    - _Requirements: 12.2, 12.3_

  - [ ]* 10.3 Property 3 — ARN validation totality at the PUT endpoint
    - `# Feature: cross-account-identity-center, Property 3: ARN validation totality`
    - Invariant: for every generated string, `handle_put_config_identity_store_role_arn` returns exactly one of `status: "valid"` (empty or matches the regex) or `status: "error"` (non-empty non-match), and `put_parameter` is called only in the `"valid"` branch
    - Hypothesis strategy: `st.text()` mixing Unicode, whitespace, and ARN-like but malformed strings
    - `@settings(max_examples=100)` minimum
    - _Property: 3_
    - _Requirements: 11.4, 11.5, 11.6_

  - [ ]* 10.4 Property 4 — Single-account bypass for the Identity Store client
    - `# Feature: cross-account-identity-center, Property 4: single-account bypass`
    - Invariant: for every `role_arn` in `{"", None}`, `get_identity_store_client(role_arn)` returns `None` and does NOT call `sts:AssumeRole`; `parse_handler` with `cfg.identity_store_role_arn == ""` passes `identity_client=None` into `resolve_names`
    - Hypothesis strategy: fixed `""` plus `None` plus whitespace-only strings
    - `@settings(max_examples=100)` minimum
    - _Property: 4_
    - _Requirements: 3.6, 7.1, 7.2_

  - [ ]* 10.5 Property 5 — `identity_client` forwarding is transparent
    - `# Feature: cross-account-identity-center, Property 5: identity_client forwarding`
    - Invariant: for any object passed as `identity_client`, `resolve_names` forwards the exact same object reference to `resolve_user_names`, and `resolve_user_names` uses that object's `describe_user` method (never `boto3.client("identitystore")`)
    - Hypothesis strategy: `st.builds(...)` producing distinguishable mock objects
    - `@settings(max_examples=100)` minimum
    - _Property: 5_
    - _Requirements: 4.2, 4.4, 4.5_

  - [ ]* 10.6 Property 6 — Cache key stability across account modes
    - `# Feature: cross-account-identity-center, Property 6: cache key stability`
    - Invariant: for every `userId`, the `UserNamesTable` item written after a resolution has partition key exactly `userId`, regardless of whether the resolution used a single-account or cross-account `identity_client`; the item MUST NOT include any attribute named `sourceAccountId`, `roleArn`, `assumedRoleArn`, or similar
    - Hypothesis strategy: UUID-shaped userIds and a boolean toggle for cross-account vs single-account mode
    - `@settings(max_examples=100)` minimum
    - _Property: 6_
    - _Requirements: 5.1, 5.2, 5.4_

  - [ ]* 10.7 Extended PBT coverage for edge-case ARN inputs
    - Additional Hypothesis strategies: non-ASCII characters inside the role path segment, whitespace-only strings, extremely long strings (>2 KB), strings that look like ARNs but use a different service (`arn:aws:s3:::...`) — all must be rejected by the PUT handler
    - Wired into the existing `tests/test_properties_identity_store_role.py`; shrink-guided to keep the failing example minimal
    - _Requirements: 11.4, 11.5_

- [x] 11. Regression checks — English-only banned strings and i18n key parity
  - [x] 11.1 Run the backend banned-strings regression on the new config handler
    - Ensure the existing banned-strings test in `tests/test_backend_handler.py` / `tests/test_config_handler.py` sees the new route's responses — add the new PUT path and the GET `identityStoreRoleArn` field to the inputs the test iterates over
    - The test MUST fail if any `message`/`humanReadable`/`description` string from the new handler contains pt-BR characters or the forbidden pt-BR phrase `"Acesso restrito a administradores"`
    - _Requirements: 11.5, 11.6, 12.1, 12.2_

  - [x] 11.2 Run `scripts/check-locales.ts` and confirm the seven new keys parity-check clean
    - `npm run build` in `frontend/` MUST succeed; the parity check fails the build if `en.json` and `pt-BR.json` disagree on the seven `settings.identityStoreRoleArn.*` keys or if either file is not alphabetically sorted
    - The generated `frontend/src/locales/keys.d.ts` MUST include each new key in the `TranslationKey` string-literal union
    - _Requirements: 11.10_

  - [x] 11.3 Checkpoint — full test suite
    - Execute `pytest tests/ -v` and `cd frontend && npm run test -- --run && npm run build`. Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 1.1–1.7, 2.1–2.4, 3.1–3.7, 4.1–4.5, 5.1–5.4, 6.1–6.8, 7.1–7.5, 8.1–8.5, 9.1–9.6, 10.1–10.8, 11.1–11.10, 12.1–12.4_

- [x] 12. Documentation
  - [x] 12.1 Add a "Cross-Account IAM Identity Center" section to `README.md`
    - Mirror the depth and structure of the existing "Cross-Account S3 Access" section: when to use, trust model, `make deploy-identity-store-role` usage, Settings page instructions, and the rollback path (clear the ARN in Settings to go back to single-account mode)
    - Include the exact `make deploy-identity-store-role IDC_ACCOUNT_PROFILE=... KIRO_ACCOUNT_ID=... IDENTITY_STORE_ID=...` example
    - English only
    - _Requirements: 6.1, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 11.8, 11.9_

  - [x] 12.2 Add the translated pt-BR counterpart to `README.pt-BR.md`
    - Same structure as the English section, translated faithfully; brand strings (`Kiro`, `Kiro Cost Analyzer`) stay untranslated per the development standards
    - _Requirements: 11.10_

- [ ]* 13. Optional — CI smoke and operator walkthrough
  - [ ]* 13.1 CI hook that runs `sam validate` and `aws cloudformation validate-template identity-store-role.yaml` on every commit
    - Add a GitHub Actions step (or equivalent) that fails the build on template parse errors
    - Not required for MVP — the checkpoint in task 1.5 already covers local validation
    - _Requirements: 1.1, 6.1_

  - [ ]* 13.2 Record a short operator walkthrough (video or animated gif) for the Settings page flow
    - Store the asset under `docs/` and link it from the new README section
    - Not required for MVP
    - _Requirements: 11.8, 11.9_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP (extended PBT coverage, CI smoke, operator walkthrough). Every non-optional task corresponds to a requirement acceptance criterion.
- Each task lists the exact files and function/class names to touch so a developer can execute it without re-reading the design.
- Checkpoints (tasks 1.5, 5.3, 6.5, 11.3) provide natural verification points between infrastructure, ETL, backend, and full-stack validation.
- Property tests live in `tests/test_properties_identity_store_role.py` and reuse moto-backed SSM; each carries the `# Feature: cross-account-identity-center, Property N: <name>` comment and validates at least 100 Hypothesis examples.
- All human-readable strings added by this feature are English in the backend; the frontend surfaces every user-facing string through `en.json` and `pt-BR.json` via `t(key)`.
- Backward compatibility is preserved: deployments that leave `IdentityStoreRoleArn` empty keep the exact current single-account behavior, and the `UserNamesTable` schema is frozen so caches survive any mode toggle.
