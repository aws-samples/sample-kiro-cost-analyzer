# Deploy Guide

> Back to [README](../README.md)

## Prerequisites

- AWS CLI configured
- SAM CLI (`brew install aws-sam-cli`)
- Node.js 18+ and Python 3.13+
- Bedrock model access enabled in the target region for Claude Haiku 4.5 and Claude Sonnet 4.6 — see [Region and model availability](#region-and-model-availability)

## Region and model availability

The default deployment region is `sa-east-1`. Before deploying to a different region, confirm every required service is available there.

| Service | Notes |
|---|---|
| AWS Lambda, API Gateway REST, DynamoDB, S3, CloudFront, Cognito, EventBridge Scheduler, Step Functions (Standard + Express), SSM Parameter Store, KMS, STS | Available in all commercial AWS regions used by this sample. |
| AWS IAM Identity Center | Available globally; `IdentityStoreId` is region-agnostic. |
| Amazon Bedrock — Claude Haiku 4.5 | Required for prompt categorization. Invoked via the **global** cross-region inference profile (`global.anthropic.claude-haiku-4-5-*`) so the call lands in the stack's deploy region (where the regional `AWS::Bedrock::Guardrail` lives). Verify model access is enabled in the target region. |
| Amazon Bedrock — Claude Sonnet 4.6 | Required for Git-Kiro correlation. Verify model access is enabled in the target region. |
| Amazon Bedrock AgentCore | Required for the correlation agent runtime. Confirm AgentCore is generally available in the target region before changing the default. |

To change the default region:

1. Edit `samconfig.toml` and update the `region` field, or pass `--region` explicitly to every `sam` and `aws` command shown below.
2. Update `agent/agentcore/aws-targets.json` to point at the same region.
3. Re-run `make deploy`.

> **Tip.** If you run into `AccessDeniedException` on the first ETL execution that calls Bedrock, the most likely cause is that the model is not enabled in the region. Enable model access via the Bedrock console under *Model access*.

## Quick Deploy

```bash
make deploy          # Full deploy (infra + frontend)
make deploy-infra    # SAM build + deploy only
make deploy-frontend # Build frontend, sync to Amazon S3, invalidate Amazon CloudFront
make dev             # Local frontend development server
```

## 1. Deploy the infrastructure

```bash
sam build
sam deploy \
  --stack-name kiro-cost-analyzer \
  --region sa-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    StackName=kiro-cost-analyzer \
    SourceBucketName=YOUR-S3-BUCKET \
    SourcePrefix=activities/AWSLogs/ACCOUNT_ID/KiroLogs/ \
    AdminEmail=admin@example.com \
    PromptsPrefix=prompts/AWSLogs/ACCOUNT_ID/KiroLogs/ \
    IdentityStoreId=d-XXXXXXXXXX
```

Or via Makefile:

```bash
make deploy-infra
make deploy-infra AWS_PROFILE=my-profile
```

`PromptsPrefix` and `IdentityStoreId` are optional. If omitted, the ETL processes only activity CSVs and user names are not resolved.

## 2. Deploy the frontend

```bash
make deploy-frontend
make deploy-frontend AWS_PROFILE=my-profile STACK_NAME=my-stack
```

Generates `.env.production` from CloudFormation outputs, builds, syncs to Amazon S3, and invalidates Amazon CloudFront.

## 3. Run the ETL

The ETL runs daily at 23:59 UTC via EventBridge Scheduler. To trigger manually:

- **UI:** Settings page → "Run ETL" button
- **CLI:**
```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:REGION:ACCOUNT:stateMachine:kiro-cost-analyzer-etl-state-machine \
  --region sa-east-1
```

> **Tip — re-categorize without re-ingesting source data.** The categorization phase runs on every execution, even when there are no new files in the source bucket. To re-classify items already in DynamoDB, reset their `category` attribute to `"NOT_CATEGORIZED"` (e.g., `aws dynamodb update-item ... --update-expression 'SET category = :c' --expression-attribute-values '{":c": {"S": "NOT_CATEGORIZED"}}'`) and trigger the state machine — `ListUncategorizedPrompts` will pick them up. Useful after fixing categorizer bugs without rebuilding analytics from the CSV/prompt source bucket.

## 4. Local development

```bash
cd frontend
cp .env.example .env.local
# Fill in with deploy outputs (ApiUrl, CognitoDomain, ClientId)
npm install
npm run dev
```

## 5. Get deploy outputs

```bash
aws cloudformation describe-stacks \
  --stack-name kiro-cost-analyzer \
  --region sa-east-1 \
  --query "Stacks[0].Outputs" \
  --output table
```

---

## Cross-Account Access (optional)

### Amazon S3 Source Bucket in another account

If the Amazon S3 bucket with Kiro logs lives in a different AWS account:

```bash
make deploy-source-role \
  SOURCE_ACCOUNT_PROFILE=logs-account \
  KIRO_ACCOUNT_ID=123456789012 \
  SOURCE_BUCKET_NAME=s3-logs-kiro
```

Then configure the role ARN in **Settings → Source Bucket Role ARN** or via deploy parameter `SourceBucketRoleArn`.

### AWS IAM Identity Center in another account

If AWS IAM Identity Center is in a different account:

```bash
make deploy-identity-store-role \
  IDC_ACCOUNT_PROFILE=idc-profile \
  KIRO_ACCOUNT_ID=123456789012 \
  IDENTITY_STORE_ID=d-1234567890
```

Then configure in **Settings → Identity Store Role ARN** or via deploy parameter `IdentityStoreRoleArn`.

### End-to-end cross-account (both in same foreign account)

```bash
# 1. S3 role in source account
make deploy-source-role \
  SOURCE_ACCOUNT_PROFILE=source-profile \
  KIRO_ACCOUNT_ID=123456789012 \
  SOURCE_BUCKET_NAME=my-bucket

# 2. Identity Store role in IDC account
make deploy-identity-store-role \
  IDC_ACCOUNT_PROFILE=source-profile \
  KIRO_ACCOUNT_ID=123456789012 \
  IDENTITY_STORE_ID=d-XXXXXXXXXX

# 3. Main stack
sam build && sam deploy \
  --profile kiro-profile \
  --region sa-east-1 \
  --parameter-overrides \
    StackName=kiro-cost-analyzer \
    SourceBucketName=my-bucket \
    SourcePrefix=activities/AWSLogs/111122223333/KiroLogs/ \
    PromptsPrefix=prompts/AWSLogs/111122223333/KiroLogs/ \
    IdentityStoreId=d-XXXXXXXXXX \
    SourceBucketRoleArn=arn:aws:iam::111122223333:role/kiro-cost-analyzer-cross-account-read \
    IdentityStoreRoleArn=arn:aws:iam::111122223333:role/kiro-cost-analyzer-identity-store-read \
    AdminEmail=admin@example.com

# 4. Frontend
make deploy-frontend AWS_PROFILE=kiro-profile
```

### Rollback to single-account

Clear the Role ARN field in Settings and save. No redeploy needed.

---

## Makefile Reference

| Target | Description |
|---|---|
| `make deploy` | Full deploy (infra + frontend) |
| `make deploy-infra` | SAM build + deploy |
| `make deploy-frontend` | Build + sync to S3 + CloudFront invalidation |
| `make deploy-agentcore` | Deploy the Git-Kiro Correlation Agent |
| `make deploy-source-role` | Cross-account IAM Role in source account |
| `make deploy-identity-store-role` | Cross-account IAM Role for Identity Center |
| `make dev` | Local frontend dev server |

| Variable | Default | Description |
|---|---|---|
| `STACK_NAME` | `kiro-cost-analyzer` | CloudFormation stack name |
| `REGION` | `sa-east-1` | AWS region |
| `AWS_PROFILE` | _(default)_ | AWS CLI profile |
| `SOURCE_ACCOUNT_PROFILE` | _(required)_ | Profile for source account |
| `KIRO_ACCOUNT_ID` | _(required)_ | Kiro account ID |
| `SOURCE_BUCKET_NAME` | _(required)_ | Source S3 bucket name |
| `KMS_KEY_ARN` | _(empty)_ | Bucket KMS key ARN (optional) |
