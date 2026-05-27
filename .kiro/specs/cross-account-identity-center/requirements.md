# Requirements Document — Cross-Account IAM Identity Center Access

## Introduction

The Kiro Cost Analyzer currently resolves user display names by calling `identitystore:DescribeUser` and `identitystore:ListUsers` directly from the `ParseFunction`. This works only when IAM Identity Center is provisioned in the same AWS account as KCA. In enterprise environments, IAM Identity Center is commonly deployed in a different account — typically the AWS Organizations management account or a delegated Identity Center account — which breaks name resolution.

This feature applies the same **STS AssumeRole** pattern already implemented for cross-account S3 access (see `.kiro/specs/cross-account-s3-access/`) to Identity Store calls. An optional CloudFormation parameter exposes a role ARN; when configured, the `ParseFunction` assumes that role in the IDC account and uses the resulting temporary credentials to build the `identitystore` client. When the parameter is empty, the system keeps its current single-account behavior unchanged.

The feature reuses existing infrastructure: the central `etl/sts_session.py` module, the `/kiro-cost-analyzer/` SSM Parameter Store convention, the Settings page admin editor, and the `source-account-role.yaml` helper pattern.

## Glossary

- **ETL_Pipeline**: The Step Functions pipeline (Standard + Distributed Map Express) that processes Kiro usage data; includes the `ParseFunction` Lambda which resolves user names.
- **KCA_Account**: AWS account where the Kiro Cost Analyzer stack is deployed (Lambdas, Step Functions, DynamoDB, API Gateway).
- **IDC_Account**: AWS account where IAM Identity Center is provisioned (Organizations management account or delegated Identity Center account).
- **Identity_Store_Role**: IAM Role created in the IDC_Account that grants `identitystore:DescribeUser` and `identitystore:ListUsers` permissions, with a trust policy allowing the KCA_Account to assume it.
- **IdentityStoreRoleArn**: Optional CloudFormation parameter holding the ARN of the Identity_Store_Role; when empty, the system runs in single-account mode.
- **IDC_Helper_Template**: CloudFormation helper template (`identity-store-role.yaml`) that administrators of the IDC_Account deploy to create the Identity_Store_Role with correct permissions and trust policy.
- **STS_Session_Manager**: Existing shared Python module (`etl/sts_session.py`) responsible for creating cross-account boto3 clients via `sts:AssumeRole`.
- **Name_Resolver**: Module responsible for resolving userIds to display names (`etl/user_name_resolver.py` orchestrated via `etl/utils/name_resolver.py`).
- **User_Name_Cache**: DynamoDB table (`UserNamesTable`) that caches resolved (displayName, userName) pairs for 7 days.
- **SSM_Parameter_Store**: AWS Systems Manager Parameter Store, used under the `/kiro-cost-analyzer/` prefix for dynamic configuration.
- **IDC_Role_Deploy_Target**: Makefile target (`deploy-identity-store-role`) that automates deploying the IDC_Helper_Template in the IDC_Account via `aws cloudformation deploy`.
- **Settings_Page**: Admin page in the React frontend (`frontend/src/pages/SettingsPage.tsx`) used to edit KCA dynamic configuration.

## Requirements

### Requirement 1: Optional Identity Store Role ARN Parameter in CloudFormation

**User Story:** As a KCA administrator, I want to optionally provide the ARN of a cross-account IAM role for IAM Identity Center during deploy, so that the ETL pipeline can resolve user names when Identity Center lives in a different AWS account.

#### Acceptance Criteria

1. THE template.yaml SHALL define a parameter `IdentityStoreRoleArn` of type `String` with default empty value (`""`).
2. WHEN the `IdentityStoreRoleArn` parameter is provided with a non-empty value, THE template.yaml SHALL create an SSM Parameter Store resource at path `/kiro-cost-analyzer/identity-store-role-arn` holding the ARN value.
3. WHEN the `IdentityStoreRoleArn` parameter is empty, THE template.yaml SHALL create the SSM Parameter Store resource at path `/kiro-cost-analyzer/identity-store-role-arn` with the sentinel value `NONE`.
4. THE template.yaml SHALL pass the environment variable `SSM_IDENTITY_STORE_ROLE_ARN` with path `/kiro-cost-analyzer/identity-store-role-arn` to the `ParseFunction`.
5. WHEN the `IdentityStoreRoleArn` parameter is provided with a non-empty value, THE template.yaml SHALL grant `sts:AssumeRole` permission scoped to exactly that ARN in the `ParseFunction` IAM policy.
6. WHEN the `IdentityStoreRoleArn` parameter is provided with a non-empty value, THE template.yaml SHALL scope the `ParseFunction` inline permissions `identitystore:DescribeUser` and `identitystore:ListUsers` down by replacing `Resource: "*"` with a condition that restricts the actions to the caller (i.e. the assumed role handles the target resource) while keeping the existing `"*"` resource only in the single-account branch.
7. THE template.yaml SHALL define a condition `HasIdentityStoreRoleArn` that evaluates to true when `IdentityStoreRoleArn` is non-empty.

### Requirement 2: Reading the Identity Store Role ARN Configuration

**User Story:** As an ETL pipeline developer, I want the configuration module to read the Identity Store role ARN from SSM Parameter Store, so that the Parse handler can decide whether to use cross-account access.

#### Acceptance Criteria

1. THE EtlConfig SHALL include a field `identity_store_role_arn` of type `str`.
2. WHEN the SSM parameter `/kiro-cost-analyzer/identity-store-role-arn` exists and contains a non-empty value other than `NONE`, THE `get_config()` function SHALL return that value in the `identity_store_role_arn` field.
3. WHEN the SSM parameter `/kiro-cost-analyzer/identity-store-role-arn` exists and contains the value `NONE` or the empty string, THE `get_config()` function SHALL return an empty string in the `identity_store_role_arn` field.
4. IF the read of SSM parameter `/kiro-cost-analyzer/identity-store-role-arn` fails, THEN THE `get_config()` function SHALL return an empty string in the `identity_store_role_arn` field and continue execution.

### Requirement 3: STS Session Management for Identity Store

**User Story:** As an ETL pipeline developer, I want a shared module that produces a cross-account Identity Store client, so that the AssumeRole logic is reusable and testable alongside the existing S3 cross-account helper.

#### Acceptance Criteria

1. THE STS_Session_Manager SHALL expose a function `get_identity_store_client(role_arn: str, correlation_id: str = "")` that returns a boto3 `identitystore` client built with temporary credentials obtained via `sts:AssumeRole`.
2. WHEN `get_identity_store_client` receives a non-empty `role_arn`, THE STS_Session_Manager SHALL call `sts:AssumeRole` with the provided ARN and a `RoleSessionName` that identifies the calling Lambda.
3. WHEN `get_identity_store_client` receives a non-empty `role_arn`, THE STS_Session_Manager SHALL request `DurationSeconds` of 3600 seconds for the temporary credentials.
4. WHEN the `sts:AssumeRole` call succeeds, THE STS_Session_Manager SHALL build and return a boto3 `identitystore` client using the `AccessKeyId`, `SecretAccessKey`, and `SessionToken` from the returned credentials.
5. IF the `sts:AssumeRole` call fails, THEN THE STS_Session_Manager SHALL log the error with fields `roleArn`, `sessionName`, `errorType`, and `errorMessage`, and propagate the exception to the caller.
6. WHEN `get_identity_store_client` receives an empty or `None` `role_arn`, THE STS_Session_Manager SHALL return `None` to signal that single-account mode must be used.
7. THE STS_Session_Manager SHALL generate a `RoleSessionName` that includes the Lambda function name from environment variable `AWS_LAMBDA_FUNCTION_NAME` for CloudTrail traceability.

### Requirement 4: Cross-Account User Name Resolution

**User Story:** As an ETL operator, I want the Parse Lambda to resolve user names using cross-account credentials when configured, so that display names are populated even when IAM Identity Center lives in a different account.

#### Acceptance Criteria

1. WHEN the `identity_store_role_arn` field of the configuration is non-empty, THE `parse_handler` SHALL obtain an Identity Store client through the STS_Session_Manager before invoking name resolution.
2. WHEN a cross-account Identity Store client is available, THE Name_Resolver SHALL use the provided client for all `identitystore:DescribeUser` and `identitystore:ListUsers` calls instead of creating a new `boto3.client("identitystore")`.
3. WHEN the `identity_store_role_arn` field of the configuration is empty, THE `parse_handler` SHALL preserve the current behavior of using the default `boto3.client("identitystore")`.
4. THE `resolve_user_names` function SHALL accept an optional `identity_client` parameter that, when provided, replaces the internal boto3 client creation for Identity Store calls.
5. THE `resolve_names` wrapper in `etl/utils/name_resolver.py` SHALL forward the `identity_client` parameter to `resolve_user_names` unchanged.

### Requirement 5: Cache Consistency Across Account Modes

**User Story:** As an ETL operator, I want the DynamoDB user-name cache to behave identically in single-account and cross-account mode, so that switching modes does not force a full cache rebuild or produce duplicate entries.

#### Acceptance Criteria

1. THE Name_Resolver SHALL write cache entries to the `UserNamesTable` using the same key schema (`userId` as partition key) regardless of whether single-account or cross-account mode is in use.
2. THE Name_Resolver SHALL NOT include the source account identifier or the assumed role ARN in the `UserNamesTable` item keys.
3. WHEN a cache entry is valid (resolvedAt within the 7-day TTL window), THE Name_Resolver SHALL return the cached value without performing any `sts:AssumeRole` or `identitystore:DescribeUser` calls.
4. WHEN a cache miss occurs in cross-account mode, THE Name_Resolver SHALL resolve the name via the cross-account Identity Store client and persist the result to the `UserNamesTable` using the same cache-write path as single-account mode.

### Requirement 6: Helper Template for the IDC Account

**User Story:** As an administrator of the IDC_Account, I want a ready-to-use CloudFormation template that creates the cross-account IAM role with the correct Identity Store permissions, so that I can enable cross-account name resolution with minimal configuration effort.

#### Acceptance Criteria

1. THE IDC_Helper_Template SHALL be a valid CloudFormation file named `identity-store-role.yaml` at the repository root.
2. THE IDC_Helper_Template SHALL require one mandatory parameter `KiroAccountId` representing the AWS account ID where KCA is deployed.
3. THE IDC_Helper_Template SHALL accept an optional parameter `IdentityStoreId` (default empty) representing the IAM Identity Center instance ID, used for documentation purposes only.
4. THE IDC_Helper_Template SHALL create an IAM Role with a trust policy that allows only the account specified in `KiroAccountId` to assume the role via `sts:AssumeRole`, using the condition key `aws:PrincipalAccount`.
5. THE IDC_Helper_Template SHALL attach to the IAM Role an inline policy granting the actions `identitystore:DescribeUser` and `identitystore:ListUsers`, with `Resource: "*"`.
6. THE IDC_Helper_Template SHALL NOT grant any write actions on Identity Store (no `CreateUser`, `UpdateUser`, `DeleteUser`, or group-management actions).
7. THE IDC_Helper_Template SHALL export the ARN of the created IAM Role as a CloudFormation Output named `IdentityStoreRoleArn`.
8. THE IDC_Helper_Template SHALL name the role `kiro-cost-analyzer-identity-store-read` to allow administrators to locate it consistently across deployments.

### Requirement 7: Backward Compatibility with Single-Account Mode

**User Story:** As an existing KCA user running in single-account mode, I want the system to keep working without any configuration changes, so that adding the cross-account Identity Center feature does not disrupt my deployment.

#### Acceptance Criteria

1. WHEN the `IdentityStoreRoleArn` parameter is empty at deploy time, THE ETL_Pipeline SHALL execute with the same Identity Store access behavior in use before this feature.
2. WHEN the `identity_store_role_arn` field is empty, THE `parse_handler` SHALL create the Identity Store client via the default `boto3.client("identitystore")` without any STS call.
3. THE template.yaml SHALL retain the existing `ParseFunction` `identitystore:DescribeUser` and `identitystore:ListUsers` permissions for single-account mode when `IdentityStoreRoleArn` is empty.
4. THE EtlConfig SHALL preserve all existing fields (`bucket_name`, `source_prefix`, `prompts_prefix`, `identity_store_id`, `source_bucket_role_arn`) with unchanged read semantics.
5. WHEN a user name cannot be resolved in single-account mode for any reason, THE Name_Resolver SHALL return `("", "")` for that userId and continue processing, preserving the current tolerant behavior.

### Requirement 8: Error Handling and Observability

**User Story:** As an ETL operator, I want cross-account Identity Store errors to be logged with enough detail to diagnose configuration issues, so that I can identify and fix problems quickly.

#### Acceptance Criteria

1. IF the `sts:AssumeRole` call for the Identity Store role fails with `AccessDeniedException`, THEN THE STS_Session_Manager SHALL log an error including `roleArn`, the exception type, and a hint to verify the trust policy of the Identity_Store_Role.
2. IF an `identitystore:DescribeUser` call using cross-account credentials returns `AccessDenied`, THEN THE Name_Resolver SHALL log an error including `roleArn`, `userId`, exception type, and a hint to verify the Identity_Store_Role permissions, and SHALL return `("", "")` for that userId.
3. WHEN the STS_Session_Manager successfully creates a cross-account Identity Store session, THE STS_Session_Manager SHALL emit an informational log entry including the assumed `roleArn` and `sessionName`, without exposing any credentials.
4. THE STS_Session_Manager SHALL use `StructuredLogger` with consistent fields (`roleArn`, `sessionName`, `errorType`, `errorMessage`) for all Identity Store session logging.
5. IF the cross-account Identity Store client cannot be built, THEN THE `parse_handler` SHALL fall back to `identity_client=None` so that `resolve_user_names` creates a default client, preserving the pipeline's ability to complete when the cache already contains the required entries.

### Requirement 9: Security of Cross-Account Access

**User Story:** As a security architect, I want cross-account Identity Store access to follow least-privilege principles and use temporary credentials, so that the risk of unauthorized access is minimized.

#### Acceptance Criteria

1. THE STS_Session_Manager SHALL use temporary credentials with a maximum duration of 3600 seconds (1 hour) for each AssumeRole call.
2. THE template.yaml SHALL grant `sts:AssumeRole` permission only for the specific ARN supplied in `IdentityStoreRoleArn`, without wildcards.
3. THE IDC_Helper_Template SHALL restrict the trust policy of the Identity_Store_Role to allow AssumeRole only from the account supplied in `KiroAccountId`, using the `aws:PrincipalAccount` condition key.
4. THE IDC_Helper_Template SHALL grant the Identity_Store_Role only read actions (`identitystore:DescribeUser`, `identitystore:ListUsers`) and no write actions.
5. THE STS_Session_Manager SHALL generate a `RoleSessionName` per invocation that includes the Lambda function name, enabling CloudTrail attribution.
6. WHEN temporary credentials are obtained, THE STS_Session_Manager SHALL use them only to construct the boto3 Identity Store client, without persisting them to environment variables, logs, or SSM parameters.

### Requirement 10: Makefile Target for Deploying the IDC Role

**User Story:** As a system operator, I want a Makefile target that deploys `identity-store-role.yaml` in the IDC_Account, so that I can create the Identity_Store_Role in an automated way and retrieve its ARN for the main stack.

#### Acceptance Criteria

1. THE Makefile SHALL define a target `deploy-identity-store-role` that runs `aws cloudformation deploy` with the template `identity-store-role.yaml`.
2. THE IDC_Role_Deploy_Target SHALL accept the parameter `IDC_ACCOUNT_PROFILE` specifying the AWS CLI profile of the IDC_Account to use via the `--profile` flag.
3. THE IDC_Role_Deploy_Target SHALL accept the parameter `KIRO_ACCOUNT_ID` specifying the AWS account ID where KCA is deployed.
4. THE IDC_Role_Deploy_Target SHALL accept the optional parameter `IDENTITY_STORE_ID` with an empty default for documentation purposes.
5. IF the parameters `IDC_ACCOUNT_PROFILE` or `KIRO_ACCOUNT_ID` are not supplied, THEN THE IDC_Role_Deploy_Target SHALL emit an error message listing the required parameters and stop execution.
6. WHEN the CloudFormation deploy succeeds, THE IDC_Role_Deploy_Target SHALL query the stack outputs and print the value of `IdentityStoreRoleArn` to the terminal to facilitate copying the ARN into the main stack's `IdentityStoreRoleArn` parameter.
7. THE IDC_Role_Deploy_Target SHALL pass `KiroAccountId` and `IdentityStoreId` as `--parameter-overrides` to `aws cloudformation deploy`.
8. THE IDC_Role_Deploy_Target SHALL use a default stack name `kiro-identity-store-role` configurable via the parameter `IDC_ROLE_STACK_NAME`.

### Requirement 11: Role ARN Configuration via the Web Interface

**User Story:** As a KCA administrator, I want to view and edit the Identity Store role ARN from the Settings page, so that I can enable, change, or disable cross-account name resolution without redeploying the stack.

#### Acceptance Criteria

1. THE `handle_get_config` function SHALL return a field `identityStoreRoleArn` with the value read from SSM parameter `/kiro-cost-analyzer/identity-store-role-arn`, converting the sentinel value `NONE` to an empty string.
2. THE backend SHALL expose an endpoint `PUT /api/config/identity-store-role-arn` that accepts a JSON body with the field `identityStoreRoleArn`.
3. THE `PUT /api/config/identity-store-role-arn` endpoint SHALL require the caller to belong to the `Admins` Cognito group and SHALL return HTTP 403 for callers that do not.
4. WHEN the endpoint receives a non-empty value, THE handler SHALL validate that the value matches the IAM role ARN pattern `^arn:aws:iam::\d{12}:role/.+$` before persisting it.
5. IF the supplied value does not match the IAM role ARN pattern, THEN THE handler SHALL return a response with `status: "error"` and a descriptive English message, without writing to SSM.
6. WHEN the value is valid or empty, THE handler SHALL persist the value to SSM parameter `/kiro-cost-analyzer/identity-store-role-arn` via `ssm:PutParameter`, using the sentinel `NONE` for empty values to stay consistent with the existing cross-account S3 handler.
7. THE template.yaml SHALL pass the environment variable `SSM_IDENTITY_STORE_ROLE_ARN` with path `/kiro-cost-analyzer/identity-store-role-arn` to the `BackendFunction`.
8. THE Settings_Page SHALL display an editable field for `identityStoreRoleArn` that follows the same visual pattern as the existing `sourceBucketRoleArn` field (Cloudscape `Input` + `FormField` with label, description, and a primary Save button).
9. THE Settings_Page SHALL support clearing the `identityStoreRoleArn` field (saving an empty value) to disable cross-account mode.
10. THE Settings_Page SHALL render all labels, descriptions, placeholders, and status messages related to the Identity Store role ARN through the i18n catalog keys in both `en.json` and `pt-BR.json`, with no hardcoded UI strings.

### Requirement 12: Parser-Style Round-Trip for ARN Persistence

**User Story:** As an ETL developer, I want the SSM persistence of the Identity Store role ARN to be lossless across read-write cycles, so that values edited through the Settings page are returned verbatim on the next read.

#### Acceptance Criteria

1. FOR any valid IAM role ARN string `arn` matching `^arn:aws:iam::\d{12}:role/.+$`, WHEN `arn` is persisted through `PUT /api/config/identity-store-role-arn` and then read back through `GET /api/config`, THE `identityStoreRoleArn` field SHALL equal the original `arn` (round-trip property).
2. FOR the empty string input, WHEN the empty value is persisted through `PUT /api/config/identity-store-role-arn` and then read back through `GET /api/config`, THE `identityStoreRoleArn` field SHALL equal the empty string (empty round-trip).
3. THE `handle_get_config` function SHALL treat the sentinel value `NONE` as semantically equivalent to the empty string for the `identityStoreRoleArn` field.
4. THE `get_config()` function in `etl/config.py` SHALL produce the same `identity_store_role_arn` value that `handle_get_config` exposes as `identityStoreRoleArn` for any given SSM state (consistency between backend-config reads and ETL-config reads).
