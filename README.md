# Kiro Cost Analyzer

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=white)](https://react.dev/)
[![AWS SAM](https://img.shields.io/badge/AWS-SAM-FF9900.svg?logo=amazonaws&logoColor=white)](https://aws.amazon.com/serverless/sam/)
[![Cloudscape](https://img.shields.io/badge/Cloudscape-Design%20System-232F3E.svg)](https://cloudscape.design/)

A serverless sample for analyzing Kiro Enterprise credit usage and developer impact. It processes activity reports and prompt logs through Step Functions, stores data in DynamoDB, resolves user names via IAM Identity Center, and surfaces aggregated metrics, tier-optimization recommendations, and AI-generated Git correlation in a React/Cloudscape SPA.

> This repository is an AWS sample provided under the [MIT-0 License](LICENSE) as reference architecture and starter code. Review and adapt it before any non-experimental use.

![Kiro Cost Analyzer dashboard — overview cards showing total credits, active users, daily average, and last-updated timestamp; a daily-usage timeline chart; and tier and client-type breakdowns segmented across the active period.](docs/screenshots/dashboard.png)

## Features

- **Dashboard and analytics** — Account overview, per-user usage table (search, filter, CSV/JSON export), model and trigger distribution.
- **Tier optimization** — Per-user upgrade/downgrade recommendations and an annual savings estimate.
- **User engagement** — Engagement funnel, churn-risk and dormant-user detection with configurable thresholds.
- **AI-powered analysis** — On-demand Git-Kiro correlation (Claude Sonnet 4.6 via Bedrock AgentCore) and automatic prompt categorization (Claude Haiku 4.5).
- **Internationalization** — English (default) and Brazilian Portuguese, runtime switching, dark mode, locale-aware formatting.
- **Multi-account** — Cross-account S3 and IAM Identity Center via STS AssumeRole.
- **Administration** — ETL management, Cognito user management, Git repository config, and settings.

See [docs/features.md](docs/features.md) for the full walkthrough with screenshots.

## Stack

| Layer | Services |
|---|---|
| Frontend | React 19, TypeScript, Cloudscape Design System, `react-i18next` |
| Backend API | AWS Lambda (Python 3.13), Amazon API Gateway, Amazon Cognito |
| ETL pipeline | AWS Step Functions (Standard + Distributed Map Express), AWS Lambda, Amazon EventBridge Scheduler |
| Data | Amazon DynamoDB (On-Demand, single-table design), Amazon S3, AWS Systems Manager Parameter Store |
| AI | Amazon Bedrock (Claude Haiku 4.5 for categorization, Claude Sonnet 4.6 for correlation), Amazon Bedrock AgentCore |
| Identity & access | Amazon Cognito, AWS IAM Identity Center, AWS STS, AWS KMS |
| Delivery | Amazon CloudFront, Amazon S3 (static hosting), AWS Lambda Layers |
| Infrastructure | AWS SAM, AWS CloudFormation |

## Architecture

![Architecture diagram showing the frontend React SPA connecting to Amazon API Gateway and AWS Lambda backend, which integrates with Amazon DynamoDB, Amazon S3, Amazon Cognito, and a Git-Kiro Correlation Agent using Amazon Bedrock AgentCore and Claude Sonnet 4.6 with GitHub and GitLab tools](docs/architecture.png)

Full component layout, the ETL and Git-Kiro correlation data flows, the DynamoDB schema, and the design decisions behind them live in [docs/architecture.md](docs/architecture.md).

## Install

> **Estimated time to first deploy: ~15 minutes.** Default region is `sa-east-1`. To deploy elsewhere, confirm Bedrock model availability and set `--region` accordingly — see [docs/deploy.md](docs/deploy.md#region-and-model-availability).

### Prerequisites

- AWS CLI configured with credentials for the target account
- AWS SAM CLI (`brew install aws-sam-cli`)
- Node.js 18+ and Python 3.13+
- An S3 bucket containing Kiro activity logs (`SourceBucketName`)
- Your AWS account ID — `aws sts get-caller-identity --query Account --output text`
- (Optional) IAM Identity Center ID for user-name resolution
- An admin email address for the initial Cognito user
- Bedrock model access enabled in the target region for Claude Haiku 4.5 and Claude Sonnet 4.6
- (Cross-account only) a profile for the source account, and the source bucket's KMS key ARN if it is SSE-KMS — see the [deploy guide](docs/deploy.md#scenario-b--cross-account)
- (If using the optional GitLab integration) network reachability and certificate trust between the AgentCore runtime and your GitLab instance, plus a one-time cold-window note on the deploy that runs the mapping migration — see [GitLab integration prerequisites](docs/deploy.md#gitlab-integration-prerequisites)

### Deploy

```bash
# First deploy — generates the gitignored samconfig.toml interactively.
# Answer "yes" to "Save arguments to configuration file".
sam build && sam deploy --guided

# After the first deploy, samconfig.toml exists and the make targets work:
make deploy            # Full deploy (infra + frontend)
make deploy-infra      # SAM build + deploy
make deploy-frontend   # Build + S3 sync + CloudFront invalidation

# Verify deployment
aws cloudformation describe-stacks --stack-name kiro-cost-analyzer \
  --query 'Stacks[0].StackStatus' --output text
# Expected: CREATE_COMPLETE

# Print the CloudFront domain
aws cloudformation describe-stacks --stack-name kiro-cost-analyzer \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomainName'].OutputValue" --output text

# Local development
make dev
```

Cross-account setups (source bucket or IAM Identity Center in another account)
and the optional Git-Kiro correlation agent have their own steps — see the full
[deploy guide](docs/deploy.md). Running cost estimates for light and heavy
workloads: [docs/cost.md](docs/cost.md).

## Uninstall

> **Warning.** The following commands **permanently delete all data** in your S3 buckets. This action is **irreversible**. Ensure you have backups of any data you wish to retain before proceeding. After cleanup, you may see final charges for the current billing period; CloudWatch Logs are retained for 90 days and continue to incur storage costs until deleted.

```bash
# 1. Empty the data bucket (required before stack deletion)
aws s3 rm s3://$(aws cloudformation describe-stacks \
  --stack-name kiro-cost-analyzer \
  --query "Stacks[0].Outputs[?OutputKey=='DataBucketName'].OutputValue" \
  --output text) --recursive

# 2. Empty the website bucket
aws s3 rm s3://$(aws cloudformation describe-stacks \
  --stack-name kiro-cost-analyzer \
  --query "Stacks[0].Outputs[?OutputKey=='WebsiteBucketName'].OutputValue" \
  --output text) --recursive

# 3. Empty the logs bucket
aws s3 rm s3://kiro-cost-analyzer-logs-$(aws sts get-caller-identity --query Account --output text) --recursive

# 4. Delete the CloudFormation stack
sam delete --stack-name kiro-cost-analyzer --region sa-east-1 --no-prompts

# 5. (Optional) Delete the Amazon Bedrock AgentCore agent
cd agent/app/GitCorrelationAgent && agentcore delete --agent-name GitCorrelationAgent

# 6. (Optional) Delete the cross-account role stack in the source account
aws cloudformation delete-stack \
  --stack-name kiro-cross-account-role \
  --profile SOURCE_ACCOUNT_PROFILE

# 7. (Optional) Delete the Identity Store role stack in the IDC account
aws cloudformation delete-stack \
  --stack-name kiro-identity-store-role \
  --profile IDC_ACCOUNT_PROFILE
```

> DynamoDB tables have deletion protection disabled by default. If you enabled it manually, disable it before stack deletion. The `sam delete` command handles the Cognito User Pool, CloudFront distribution, and all other resources automatically.

## Tests

```bash
# Backend (Python)
python -m pytest tests/ -v

# Frontend (TypeScript)
cd frontend && npm run test
```

## What this sample demonstrates

End-to-end patterns you can lift into your own work:

- A serverless ingestion pipeline using **AWS Step Functions** with a **Distributed Map Express** child workflow to fan out file processing without hitting Map Inline limits.
- **Amazon DynamoDB single-table design** with atomic counters, sort-key normalization, and hybrid storage (large items offloaded to Amazon S3).
- **Amazon Bedrock AgentCore** orchestrating provider-aware Git tools (GitHub via OAuth through the AgentCore Gateway, GitLab via a direct authenticated HTTPS call) alongside a Kiro data tool via Lambda, for on-demand semantic correlation across GitHub and GitLab repositories.
- A **Cognito-fronted React SPA** with Cloudscape, full i18n via `react-i18next`, and locale-aware formatters.
- **Cross-account access patterns** for Amazon S3 source buckets and IAM Identity Center via AWS STS AssumeRole.
- A formal **STRIDE threat model** with the corresponding mitigations applied in `template.yaml` and the sample code — see [docs/security.md](docs/security.md).

## Built with Kiro

This sample was built end-to-end with [Kiro](https://kiro.dev) using a spec-driven development flow. The codebase, infrastructure, i18n catalogs, threat model, and most of the prose in this README and `docs/` were produced in collaboration with Kiro.

The repository contains roughly **20 specs** under [`.kiro/specs/`](.kiro/specs/), each composed of `requirements.md` (user stories with `SHALL/WHEN/THEN` acceptance criteria), `design.md` (components, interfaces, data models, correctness properties), and `tasks.md` (an implementation plan back-traceable to requirements). Codebase conventions live in [`.kiro/steering/development-standards.md`](.kiro/steering/development-standards.md) so Kiro applies them consistently across sessions and contributors.

To extend or contribute using Kiro, [CONTRIBUTING.md](CONTRIBUTING.md#using-kiro-when-contributing) explains what fits a spec, what fits a vibe-coding session, and what to keep out of the agent loop.

## Documentation

| Document | Description |
|---|---|
| [Features](docs/features.md) | Full feature walkthrough with screenshots |
| [Architecture](docs/architecture.md) | Diagrams, ETL flow, DynamoDB schema, project structure, design decisions |
| [Deploy Guide](docs/deploy.md) | Installation, cross-account setup, Makefile reference |
| [Cost Estimate](docs/cost.md) | Light and heavy workload cost scenarios |
| [Security](docs/security.md) | Defense-in-depth controls and threat model |
| [Changelog](docs/changelog.md) | Version history and release notes |

## Contributing

Contributions are welcome — please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening an issue or pull request.

This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct). See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Security

Please report security issues per [SECURITY.md](SECURITY.md). Do **not** open a public GitHub issue for security findings.

## License

This project is licensed under the MIT-0 License. See [LICENSE](LICENSE) for the full text.
