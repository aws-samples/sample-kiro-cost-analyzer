# Deploy Guide

> Back to [README](../README.md)

This guide walks through deploying the Kiro Cost Analyzer end to end. Pick the
scenario that matches where your Kiro source data lives:

- [Scenario A — Single account](#scenario-a--single-account): the S3 bucket with
  Kiro logs (and, optionally, IAM Identity Center) is in the **same** account
  where you deploy the app. Start here if you are unsure.
- [Scenario B — Cross-account](#scenario-b--cross-account): the source bucket
  and/or IAM Identity Center live in a **different** account from the app.

Both scenarios share the same [prerequisites](#prerequisites) and
[first-deploy recipe](#first-deploy-sam-deploy---guided).

## Prerequisites

- AWS CLI configured with credentials for the **app** account
- AWS SAM CLI (`brew install aws-sam-cli`)
- Node.js 18+ and Python 3.13+
- An S3 bucket containing Kiro activity logs (its name → `SourceBucketName`)
- An admin email address for the initial Cognito user
- Your app account ID — `aws sts get-caller-identity --query Account --output text`
- Bedrock model access enabled in the target region for Claude Haiku 4.5 and
  Claude Sonnet 4.6 — see [Region and model availability](#region-and-model-availability)
- (Optional) IAM Identity Center ID (`d-xxxxxxxxxx`) for user-name resolution
- (Cross-account only) a profile for the **source** account, and the source
  bucket's KMS key ARN if it is SSE-KMS encrypted — see
  [Find the source bucket's KMS key](#1-find-the-source-buckets-kms-key)

> **Profiles.** Every command accepts `AWS_PROFILE=<profile>` (Makefile targets)
> or `--profile <profile>` (raw `aws`/`sam`). In cross-account setups you will
> use **two** profiles: one for the app account and one for the source account.

## Region and model availability

The default deployment region is `sa-east-1`. Before deploying to a different
region, confirm every required service is available there.

| Service | Notes |
|---|---|
| AWS Lambda, API Gateway REST, DynamoDB, S3, CloudFront, Cognito, EventBridge Scheduler, Step Functions (Standard + Express), SSM Parameter Store, KMS, STS | Available in all commercial AWS regions used by this sample. |
| AWS IAM Identity Center | Available globally; `IdentityStoreId` is region-agnostic. |
| Amazon Bedrock — Claude Haiku 4.5 | Required for prompt categorization. Invoked via the **global** cross-region inference profile (`global.anthropic.claude-haiku-4-5-*`) so the call lands in the stack's deploy region (where the regional `AWS::Bedrock::Guardrail` lives). Verify model access is enabled in the target region. |
| Amazon Bedrock — Claude Sonnet 4.6 | Required for Git-Kiro correlation. Verify model access is enabled in the target region. |
| Amazon Bedrock AgentCore | Required for the correlation agent runtime. Confirm AgentCore is generally available in the target region before changing the default. |

To change the default region:

1. Pass `--region <region>` to the first-deploy command below (it is saved to
   `samconfig.toml`), or edit `samconfig.toml` after the first deploy.
2. Update `agent/agentcore/aws-targets.json` to point at the same region.
3. Re-run `make deploy`.

> **Tip.** If you hit `AccessDeniedException` on the first ETL execution that
> calls Bedrock, the most likely cause is that the model is not enabled in the
> region. Enable model access via the Bedrock console under *Model access*.

## First deploy: `sam deploy --guided`

`samconfig.toml` holds the stack name, region, capabilities, and parameter
values for every subsequent deploy. **It is gitignored and does not exist in a
fresh clone** — you generate it once with `--guided`. Run this from the repo
root, with credentials for the **app** account:

```bash
sam build
sam deploy --guided
```

`--guided` prompts for the stack name (use `kiro-cost-analyzer`), the region
(`sa-east-1`), the template parameters below, and whether to save them. Answer
**yes** to "Save arguments to configuration file" so `samconfig.toml` is
written. After that, `make deploy-infra` and `make deploy` work with no extra
flags.

Template parameters `--guided` asks for:

| Parameter | Required | Value |
|---|---|---|
| `SourceBucketName` | yes | name of the S3 bucket with Kiro logs |
| `AdminEmail` | yes | email for the first Cognito user |
| `SourcePrefix` | no | CSV prefix, e.g. `activities/AWSLogs/<source-account-id>/KiroLogs/` |
| `PromptsPrefix` | no | prompt-log prefix, e.g. `prompts/AWSLogs/<source-account-id>/KiroLogs/` |
| `IdentityStoreId` | no | `d-xxxxxxxxxx` for user-name resolution |
| `SourceBucketRoleArn` | no | cross-account only — see [Scenario B](#scenario-b--cross-account) |
| `IdentityStoreRoleArn` | no | cross-account only — see [Scenario B](#scenario-b--cross-account) |

> **`--stack-name`.** The stack name (set via the `--guided` prompt, or
> `--stack-name` on a raw `sam deploy`) is also used to prefix the names of the
> resources the stack creates, via the built-in `AWS::StackName` pseudo-parameter.
> There is no separate `StackName` parameter to keep in sync — set the stack name
> once.

If you prefer a non-interactive first deploy, the complete raw command is:

```bash
sam build
sam deploy \
  --stack-name kiro-cost-analyzer \
  --region sa-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    SourceBucketName=YOUR-S3-BUCKET \
    SourcePrefix=activities/AWSLogs/ACCOUNT_ID/KiroLogs/ \
    PromptsPrefix=prompts/AWSLogs/ACCOUNT_ID/KiroLogs/ \
    IdentityStoreId=d-XXXXXXXXXX \
    AdminEmail=admin@example.com
```

All three of `--resolve-s3`, `--capabilities ...`, and `--stack-name` are
required; omitting any of them fails the deploy. `--guided` sets them for you,
which is why it is the recommended path.

---

## Scenario A — Single account

The source bucket and IAM Identity Center are in the same account as the app.
Do **not** pass `SourceBucketRoleArn` or `IdentityStoreRoleArn` — the Lambdas
read the bucket directly.

### 1. Deploy the infrastructure

First time (writes `samconfig.toml`):

```bash
sam build && sam deploy --guided
```

Subsequent deploys:

```bash
make deploy-infra
make deploy-infra AWS_PROFILE=my-profile   # if you use a named profile
```

### 2. Deploy the frontend

```bash
make deploy-frontend
make deploy-frontend AWS_PROFILE=my-profile
```

Generates `frontend/.env.production` from the stack outputs, builds the SPA,
syncs it to the website S3 bucket, and invalidates the CloudFront cache.

### 3. Deploy the correlation agent (optional)

The Git-Kiro correlation feature runs on Amazon Bedrock AgentCore. It is a
separate deploy from the SAM stack and goes into the **same account** as the app
(its execution role and DynamoDB/SSM access live there).

Run it **after** `make deploy-infra` — the SAM stack defines the
`CorrelationAgentRuntimeArn` parameter that this step populates. The target
resolves the runtime ARN by its stable name (`GitCorrelationAgent`) and syncs it
into the live stack, so the correlation worker always points at the current
runtime even after the AgentCore toolkit recreates it with a new ID.

```bash
# The agentcore CLI lives in the project's virtualenv — activate it first.
python3 -m venv .venv && source .venv/bin/activate
pip install bedrock-agentcore-starter-toolkit

make deploy-agentcore
make deploy-agentcore AWS_PROFILE=my-profile
```

Skip this step if you do not need Git-Kiro correlation; the rest of the app
works without it. Until you run it, `CorrelationAgentRuntimeArn` stays `"NONE"`
and the correlation worker returns a clean error instead of invoking a
non-existent runtime.

### 4. Run the ETL

See [Run the ETL](#run-the-etl).

---

## Scenario B — Cross-account

The source bucket and/or IAM Identity Center live in a **different** account
(the *source* account) from the app (the *app* account). Access is granted by
IAM roles deployed **in the source account** that the app account assumes via
STS. Deploy those roles **first**, then feed their ARNs into the app deploy.

Throughout this section:

- `APP_ACCOUNT_ID` / `app-profile` — where the Kiro Cost Analyzer runs.
- `SOURCE_ACCOUNT_ID` / `source-profile` — where the bucket and IDC live.

### 1. Find the source bucket's KMS key

If the source bucket is encrypted with a customer-managed KMS key (SSE-KMS), the
cross-account role needs `kms:Decrypt` on that key, or the ETL fails at read
time with `AccessDenied ... kms:Decrypt`. Discover the key ARN (run with the
source-account profile):

```bash
aws s3api get-bucket-encryption --bucket SOURCE-BUCKET --profile source-profile \
  --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault'
```

If `SSEAlgorithm` is `aws:kms`, note the `KMSMasterKeyID` (a full key ARN) and
pass it as `KMS_KEY_ARN` in the next step. If it is `AES256` (SSE-S3) or the
bucket has no encryption config, skip `KMS_KEY_ARN`.

### 2. Deploy the cross-account roles in the SOURCE account

```bash
# S3 read role (+ KMS decrypt when the bucket is SSE-KMS)
make deploy-source-role \
  SOURCE_ACCOUNT_PROFILE=source-profile \
  KIRO_ACCOUNT_ID=APP_ACCOUNT_ID \
  SOURCE_BUCKET_NAME=SOURCE-BUCKET \
  KMS_KEY_ARN=arn:aws:kms:REGION:SOURCE_ACCOUNT_ID:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

```bash
# Identity Store read role (only if IDC is in the source account)
make deploy-identity-store-role \
  IDC_ACCOUNT_PROFILE=source-profile \
  KIRO_ACCOUNT_ID=APP_ACCOUNT_ID \
  IDENTITY_STORE_ID=d-XXXXXXXXXX
```

`KIRO_ACCOUNT_ID` is the **app** account (the one allowed to assume the role).
Each target prints the **Role ARN** it created — copy both; you need them in
step 3. They look like:

- `arn:aws:iam::SOURCE_ACCOUNT_ID:role/kiro-cost-analyzer-cross-account-read`
- `arn:aws:iam::SOURCE_ACCOUNT_ID:role/kiro-cost-analyzer-identity-store-read`

> **Region note.** The `make deploy-*-role` targets use the source profile's
> default region. The role itself is global, but the stack lands in that region;
> pass `REGION=<region>` if you want it elsewhere.

### 3. Deploy the app stack in the APP account

First time, with `--guided`, supplying the two role ARNs from step 2 (and the
`SourcePrefix`/`PromptsPrefix` using the **source** account id in the path):

```bash
sam build
sam deploy --guided --profile app-profile
# When prompted:
#   SourceBucketName     = SOURCE-BUCKET
#   SourcePrefix         = activities/AWSLogs/SOURCE_ACCOUNT_ID/KiroLogs/
#   PromptsPrefix        = prompts/AWSLogs/SOURCE_ACCOUNT_ID/KiroLogs/
#   IdentityStoreId      = d-XXXXXXXXXX
#   SourceBucketRoleArn  = arn:aws:iam::SOURCE_ACCOUNT_ID:role/kiro-cost-analyzer-cross-account-read
#   IdentityStoreRoleArn = arn:aws:iam::SOURCE_ACCOUNT_ID:role/kiro-cost-analyzer-identity-store-read
#   AdminEmail           = admin@example.com
```

Equivalent non-interactive form:

```bash
sam build && sam deploy \
  --stack-name kiro-cost-analyzer \
  --profile app-profile \
  --region sa-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    SourceBucketName=SOURCE-BUCKET \
    SourcePrefix=activities/AWSLogs/SOURCE_ACCOUNT_ID/KiroLogs/ \
    PromptsPrefix=prompts/AWSLogs/SOURCE_ACCOUNT_ID/KiroLogs/ \
    IdentityStoreId=d-XXXXXXXXXX \
    SourceBucketRoleArn=arn:aws:iam::SOURCE_ACCOUNT_ID:role/kiro-cost-analyzer-cross-account-read \
    IdentityStoreRoleArn=arn:aws:iam::SOURCE_ACCOUNT_ID:role/kiro-cost-analyzer-identity-store-read \
    AdminEmail=admin@example.com
```

> You can also set the role ARNs after deploy, without redeploying: paste them
> into **Settings → Source Bucket Role ARN** / **Identity Store Role ARN** in
> the app.

### 4. Frontend and agent

Same as the single-account flow — run `make deploy-frontend AWS_PROFILE=app-profile`
and (optionally) `make deploy-agentcore AWS_PROFILE=app-profile`.

### Rollback to single-account

Clear the Role ARN fields in **Settings** and save. No redeploy needed.

---

## Run the ETL

The ETL runs daily at 23:59 UTC via EventBridge Scheduler. To trigger it
manually:

- **UI:** Settings page → "Run ETL" button.
- **CLI:**

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:REGION:ACCOUNT:stateMachine:kiro-cost-analyzer-etl-state-machine \
  --region sa-east-1
```

- **Makefile:** `make reingest-data AWS_PROFILE=my-profile` resolves the state
  machine ARN for you and prints a console URL plus a poll command.

> **Tip — re-categorize without re-ingesting source data.** The categorization
> phase runs on every execution, even when there are no new files in the source
> bucket. To re-classify items already in DynamoDB, reset their `category`
> attribute to `"NOT_CATEGORIZED"` (e.g.,
> `aws dynamodb update-item ... --update-expression 'SET category = :c' --expression-attribute-values '{":c": {"S": "NOT_CATEGORIZED"}}'`)
> and trigger the state machine — `ListUncategorizedPrompts` will pick them up.

## Local development

```bash
cd frontend
cp .env.example .env.local
# Fill in with deploy outputs (ApiUrl, CognitoDomain, ClientId)
npm install
npm run dev
```

Or `make dev` from the repo root.

## Get deploy outputs

```bash
aws cloudformation describe-stacks \
  --stack-name kiro-cost-analyzer \
  --region sa-east-1 \
  --query "Stacks[0].Outputs" \
  --output table
```

---

## Makefile reference

| Target | Description |
|---|---|
| `make deploy` | Full deploy (infra + frontend). Requires `samconfig.toml` (run `sam deploy --guided` once first). |
| `make deploy-infra` | `sam build` + `sam deploy` using `samconfig.toml`. |
| `make deploy-frontend` | Build the SPA, sync to S3, invalidate CloudFront. |
| `make deploy-agentcore` | Deploy the Git-Kiro Correlation Agent (needs the project venv active). |
| `make deploy-source-role` | Cross-account S3 read role, deployed in the source account. |
| `make deploy-identity-store-role` | Cross-account Identity Center read role, deployed in the IDC account. |
| `make reingest-data` | Start a fresh ETL execution. |
| `make dev` | Local frontend dev server. |

| Variable | Default | Description |
|---|---|---|
| `STACK_NAME` | `kiro-cost-analyzer` | CloudFormation stack name |
| `REGION` | `sa-east-1` | AWS region |
| `AWS_PROFILE` | _(default)_ | AWS CLI profile for the app account |
| `SOURCE_ACCOUNT_PROFILE` | _(required for `deploy-source-role`)_ | Profile for the source account |
| `IDC_ACCOUNT_PROFILE` | _(required for `deploy-identity-store-role`)_ | Profile for the IDC account |
| `KIRO_ACCOUNT_ID` | _(required for role targets)_ | App account ID allowed to assume the role |
| `SOURCE_BUCKET_NAME` | _(required for `deploy-source-role`)_ | Source S3 bucket name |
| `IDENTITY_STORE_ID` | _(required for `deploy-identity-store-role`)_ | Identity Store ID (`d-xxxxxxxxxx`) |
| `KMS_KEY_ARN` | _(empty)_ | Source bucket CMK ARN. Required when the source bucket is **SSE-KMS**; omit only for SSE-S3 buckets. |
