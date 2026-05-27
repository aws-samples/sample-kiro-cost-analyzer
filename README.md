# Kiro Cost Analyzer

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=white)](https://react.dev/)
[![AWS SAM](https://img.shields.io/badge/AWS-SAM-FF9900.svg?logo=amazonaws&logoColor=white)](https://aws.amazon.com/serverless/sam/)
[![Cloudscape](https://img.shields.io/badge/Cloudscape-Design%20System-232F3E.svg)](https://cloudscape.design/)

A serverless sample for analyzing Kiro Enterprise credit usage and developer impact. It processes activity reports and prompt logs through Step Functions, stores data in DynamoDB, resolves user names via IAM Identity Center, and surfaces aggregated metrics, tier-optimization recommendations, and AI-generated Git correlation in a React/Cloudscape SPA.

> This repository is an AWS sample provided under the [MIT-0 License](LICENSE) as reference architecture and starter code. Review and adapt it before any non-experimental use.

<!--
SCREENSHOT — hero
File: docs/screenshots/dashboard.png
Replace via the workflow in docs/screenshots/README.md (anonymize per the rules there).
-->
![Kiro Cost Analyzer dashboard — overview cards showing total credits, active users, daily average, and last-updated timestamp; a daily-usage timeline chart; and tier and client-type breakdowns segmented across the active period.](docs/screenshots/dashboard.png)

## Capabilities

### Dashboard and analytics

- **Account Overview** — Total credits consumed, daily/weekly timeline charts, breakdown by tier (Free/Pro/Enterprise) and client type (IDE/CLI/Web).
- **Per-User Usage Table** — Sortable, filterable table with search, pagination, and export to CSV/JSON.
- **Model Distribution** — Pie chart showing which AI models are being used and how often.
- **Trigger Distribution** — Breakdown of how prompts are initiated (manual, auto-complete, inline, etc.).

<!--
SCREENSHOT — per-user usage table
File: docs/screenshots/users.png
-->
![Per-user usage table on the Users tab showing user, email, subscription tier, total credits, overage credits, last-active date, and a status badge column. The toolbar above the table shows search, filter, and pagination controls.](docs/screenshots/users.png)

<!--
SCREENSHOT — tier and client-type breakdowns
File: docs/screenshots/breakdown-by-tier.png
-->
![Breakdown view segmenting account-wide credit consumption by subscription tier (Free, Pro, Pro Plus, Power) and by client type (IDE, CLI, Web), each rendered as a stacked bar with credit totals and percentage share.](docs/screenshots/breakdown-by-tier.png)

### Tier optimization

- **Upgrade/downgrade recommendations** — Projects monthly credit trajectory per user, identifies who would benefit from a tier change.
- **Annual savings calculator** — Estimates cost savings from right-sizing tiers across the organization.
- **Visual indicators** — Inline badges on user rows mark candidates for upgrade, downgrade, or already-optimal tier.

<!--
SCREENSHOT — tier optimization recommendations
File: docs/screenshots/recommendations.png
-->
![Tier optimization recommendations tab. A summary card displays total recommended changes, projected annual savings, and users analyzed. Below it, a table lists per-user recommendations with current tier, recommended tier, projected monthly cost delta, and a colored badge marking each row as upgrade, downgrade, or optimal.](docs/screenshots/recommendations.png)

### User engagement and segmentation

- **Engagement funnel** — Visual funnel segmenting users into Power / Active / Light / Idle / Dormant based on configurable thresholds.
- **Churn risk detection** — Flags users trending toward inactivity with declining usage patterns.
- **Dormant user detection** — Identifies users inactive for 30+ days with frequency badges and last-active timestamps.
- **Configurable thresholds** — Adjust engagement segment boundaries via the Settings page.

<!--
SCREENSHOT — engagement funnel and segmentation
File: docs/screenshots/user-engagement.png
-->
![User engagement view showing a five-stage funnel from total users down to power users alongside a segmentation panel that classifies the active user base into Power, Active, Light, Idle, and Dormant tiers, each with its count and percentage of the total.](docs/screenshots/user-engagement.png)

### AI-powered analysis

- **Git-Kiro correlation** — On-demand AI agent (Claude Sonnet 4.6 via Amazon Bedrock AgentCore) semantically correlates Kiro prompts with GitHub commits/PRs and produces an Impact Score (0–100) with per-item confidence.
- **Bilingual insights** — Insights are generated in English and Brazilian Portuguese in a single LLM call, so switching the UI locale renders the same recommendations in the active language with no additional cost.
- **Prompt categorization** — Automatic classification via Amazon Bedrock Claude Haiku 4.5 across 14 categories (Code Generation, Debugging, Refactoring, Documentation, Testing, etc.).
- **Feedback loop** — Users correct categories via modal; admins approve corrections; approved examples enrich the classifier's few-shot prompt dynamically.

<!--
SCREENSHOT — per-user productivity report with Git-Kiro Impact Score
File: docs/screenshots/user-activity-report-1.png
-->
![Per-user productivity report showing the Activity Overview cards (total interactions, prompts, days active, daily average), a daily activity timeline chart, an activities-by-category table, and the AI-generated Impact Score block with bilingual insights summarizing the developer's recent work.](docs/screenshots/user-activity-report-1.png)

<!--
SCREENSHOT — bilingual AI-generated insights
File: docs/screenshots/insights.png
-->
![AI-generated insights panel from the productivity report showing the Impact Score progress bar with a Very High classification and a list of titled insights — Excellent Productivity, Excellent Thematic Coverage, Real Security Priority, and so on — each with a short paragraph explaining the observed pattern.](docs/screenshots/insights.png)

### Internationalization and UX

- **Multi-language** — English (default) plus Brazilian Portuguese, runtime switching with no page reload.
- **Dark mode** — Full Cloudscape dark theme support.
- **Locale-aware formatting** — Numbers, dates, and times formatted per active locale.
- **Cron humanizer** — Translates cron/rate expressions into human-readable schedule descriptions.

### Multi-account deployment

- **Cross-account S3** — AWS STS AssumeRole for reading logs from S3 buckets in other AWS accounts.
- **Cross-account Identity Center** — Resolves user names from IAM Identity Center in a separate account.
- **Defense-in-depth** — Cognito + API Gateway authorizer + JWT claim scoping + CSP headers + CORS restriction.

### Administration

- **ETL management** — Manual trigger, schedule configuration (cron/rate), execution history with status.
- **User management** — Cognito user CRUD, admin group assignment, custom attribute mapping.
- **Git repository config** — Add/remove GitHub repos for correlation analysis, user-to-git-username mapping.
- **Settings** — Source bucket, prefixes, cross-account role ARNs, engagement thresholds.

## What this sample demonstrates

The codebase is intended to illustrate end-to-end patterns you can lift into your own work, including:

- A serverless ingestion pipeline using **AWS Step Functions** with a **Distributed Map Express** child workflow to fan out file processing without hitting Map Inline limits.
- **Amazon DynamoDB single-table design** with atomic counters, sort-key normalization, and hybrid storage (large items offloaded to Amazon S3).
- **Amazon Bedrock AgentCore** orchestrating two MCP tools (GitHub via OAuth, Kiro data via Lambda) for on-demand semantic correlation.
- A **Cognito-fronted React SPA** with Cloudscape, full i18n via `react-i18next`, and locale-aware formatters.
- **Cross-account access patterns** for Amazon S3 source buckets and IAM Identity Center via AWS STS AssumeRole.
- A formal **STRIDE threat model** with the corresponding mitigations applied in `template.yaml` and the sample code.

## Who might find it useful

The sample assumes you are a Kiro Enterprise customer or you operate similar AI-developer-tool spend at scale. Typical readers:

- **Engineering managers** evaluating per-user usage, tier optimization, and engagement segmentation patterns.
- **Platform teams** running Kiro across multiple accounts who need cross-account ingestion (S3 + IAM Identity Center).
- **FinOps practitioners** looking at how AI spend can be tied to developer output.
- **Security teams** studying Cognito-fronted access, defense-in-depth, and threat-modeling artifacts.

You will get the most value from this sample if you are comfortable reading AWS SAM, Python, and TypeScript, and willing to adapt the code to your account, region, and operational requirements before relying on it.

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

## Built with Kiro

This sample is itself a worked example of [Kiro](https://kiro.dev) at work. The codebase, the infrastructure, the i18n catalogs, the threat model, and most of the prose in this README and the `docs/` folder were produced in collaboration with Kiro using a spec-driven development flow.

The repository contains roughly **20 specs** under [`.kiro/specs/`](.kiro/specs/), each composed of three documents:

- `requirements.md` — User stories with acceptance criteria in formal `SHALL/WHEN/THEN` form.
- `design.md` — Technical design: components, interfaces, data models, error handling, correctness properties.
- `tasks.md` — Implementation plan with each task back-traceable to a specific requirement.

Conventions for the codebase (Python idioms, React+Cloudscape patterns, DynamoDB single-table layout, i18n rules, security defaults) live in [`.kiro/steering/development-standards.md`](.kiro/steering/development-standards.md) so Kiro applies them consistently across sessions and contributors. Both the specs and the steering file are committed and reviewed alongside the code they describe.

Two takeaways for readers evaluating spec-driven development at scale:

- **Spec-first scales further than vibe-coding alone.** The specs in this repo span features as small as a "last 30 days" default and as large as the Git-Kiro correlation agent. The same flow handled both.
- **Steering keeps the agent honest.** The development standards file pre-commits decisions that are easy to drift on (English-only logs, i18n key parity, dependency-injected boto3 clients, Mermaid only for sequence diagrams). It is the contract that lets multiple contributors hand work back and forth without losing the project's consistency.

If you want to extend or contribute to this sample using Kiro, [CONTRIBUTING.md](CONTRIBUTING.md#using-kiro-when-contributing) has a short set of guidelines on what fits a spec, what fits a vibe-coding session, and what to keep out of the agent loop.

## Architecture

The diagram below illustrates the complete system architecture, showing the frontend React SPA, AWS services, ETL pipeline, and Git-Kiro correlation agent components.

![Architecture diagram showing the frontend React SPA connecting to Amazon API Gateway and AWS Lambda backend, which integrates with Amazon DynamoDB, Amazon S3, Amazon Cognito, and a Git-Kiro Correlation Agent using Amazon Bedrock AgentCore and Claude Sonnet 4.6](docs/architecture.png)

## Data Flow — ETL Pipeline

![ETL pipeline data flow diagram showing five phases: List Phase (Amazon EventBridge Scheduler triggering AWS Step Functions to list Amazon S3 objects), Parse and Write Phase (distributed AWS Lambda processing with Map Express writing to Amazon DynamoDB and Amazon S3), Record Status phase (AWS Lambda writing status to AWS Systems Manager), Categorization Phase (AWS Lambda using Amazon Bedrock Claude Haiku 4.5 for classification), and Reconcile Phase (AWS Lambda comparing the local user-name cache against IAM Identity Center)](docs/etl-data-flow.png)

## Data Flow — Git-Kiro Correlation

![Git-Kiro correlation data flow diagram showing four steps: Frontend requests correlation analysis, AWS Lambda checks Amazon DynamoDB cache, on cache miss invokes Amazon Bedrock AgentCore which fetches Git activity and Kiro data to perform semantic correlation via Claude Sonnet 4.6, results are persisted with 7-day TTL](docs/git-kiro-correlation-flow.png)

## Security

This sample applies defense-in-depth controls aligned with a STRIDE threat model:

| Control | Implementation |
|---|---|
| Authentication | Cognito User Pool with SRP, password policy (8+ chars, upper/lower/numbers) |
| Authorization | API Gateway Cognito Authorizer + server-side admin group check |
| User-scoping | Non-admins restricted to own data via `custom:kiro_user_id` JWT claim |
| CORS | Restricted to CloudFront domain (no wildcard) |
| CSP | Content-Security-Policy, HSTS, X-Frame-Options: DENY via CloudFront |
| Token security | 1h ID/access token, 7-day refresh token, GlobalSignOut on logout |
| Secrets | Git PATs in SSM SecureString (KMS), never exposed in API responses |
| Identity bridging | Cognito sub ↔ Kiro userId linked via custom attribute |
| Encryption | S3 AES-256 at rest, all connections TLS in transit |

> Reporting a vulnerability: see [SECURITY.md](SECURITY.md).

## Quick Start

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

### Deploy

```bash
# Full deploy (infrastructure + frontend)
make deploy

# Or step by step
make deploy-infra      # SAM build + deploy
make deploy-frontend   # Build + S3 sync + CloudFront invalidation

# Verify deployment
aws cloudformation describe-stacks --stack-name kiro-cost-analyzer \
  --query 'Stacks[0].StackStatus' --output text
# Expected: CREATE_COMPLETE

# Print the CloudFront URL
aws cloudformation describe-stacks --stack-name kiro-cost-analyzer \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" --output text

# Local development
make dev
```

> Full deploy guide with cross-account setup: [docs/deploy.md](docs/deploy.md).

## Cost Estimate

The two scenarios below were estimated against `sa-east-1` pricing as of May 2026 and are intentionally rough — your actual bill depends on token mix, retention, and how busy your users are. The "heavy" scenario was sized against real telemetry from one heavy developer in the maintainers' deployment and extrapolated to 10 such users.

> Categorization runs automatically for every prompt ingested by the ETL. Correlation is on-demand and cached in DynamoDB for 7 days, so repeated requests for the same user/period cost nothing.

### Scenario A — light usage

Workload assumption: ~260 files/day, ~20 active users, ETL once per day.

| Service | Estimated monthly cost |
|---|---|
| AWS Lambda (9 functions) | ~$1.50 |
| AWS Step Functions Standard | ~$0.10 |
| AWS Step Functions Express (Distributed Map) | ~$0.50 |
| Amazon DynamoDB (On-Demand) | ~$0.50 |
| Amazon Bedrock — Claude Haiku 4.5 (categorization) | ~$3.00 |
| Amazon Bedrock — Claude Sonnet 4.6 (correlation) | ~$3.50 |
| Amazon Bedrock AgentCore (Runtime) | ~$1.00 |
| Amazon API Gateway (REST) | ~$0.04 |
| Amazon S3 | ~$0.10 |
| Amazon CloudFront | ~$0.10 |
| Amazon Cognito | $0.00 (50K MAUs free tier) |
| AWS Systems Manager Parameter Store | $0.00 |
| Amazon EventBridge Scheduler | $0.00 |
| AWS KMS | ~$0.03 |
| Amazon CloudWatch Logs | ~$0.50 |
| **Total** | **~$11/month** |

### Scenario B — 10 heavy users, ETL hourly

Workload assumption: 10 heavy users at ~400 prompts/day each (120,000 prompts/month total), ETL running 24x/day, ~50 unique correlation analyses per week.

| Service | Estimated monthly cost | Notes |
|---|---|---|
| AWS Lambda | ~$1.73 | ~180K invocations, ~102K GB-s — categorization dominates |
| AWS Step Functions Standard | ~$0.81 | ~21,600 state transitions (720 ETL runs × ~30 transitions) |
| AWS Step Functions Express (Distributed Map) | ~$0.37 | ~14,400 child executions |
| Amazon DynamoDB (On-Demand) | ~$1.19 | ~1.08M writes (8 per prompt), ~945K RRU for dashboard reads |
| **Amazon Bedrock — Claude Haiku 4.5 (categorization)** | **~$270.00** | **120K prompts × ~2K input + ~50 output tokens** |
| Amazon Bedrock — Claude Sonnet 4.6 (correlation) | ~$12.00 | 200 analyses × ~10K input + ~2K output tokens |
| Amazon Bedrock AgentCore (Runtime) | ~$1.07 | 200 invocations, scales to zero between |
| Amazon API Gateway (REST) | ~$0.13 | ~30K requests |
| Amazon S3 | ~$1.00 | ~6 GB stored |
| Amazon CloudFront | ~$0.40 | |
| Amazon Cognito | $0.00 | 10 users — within free tier |
| AWS KMS | ~$0.03 | |
| Amazon CloudWatch Logs | ~$1.77 | ~3 GB ingested |
| AWS Systems Manager Parameter Store | $0.00 | Standard tier |
| Amazon EventBridge Scheduler | $0.00 | 1 schedule |
| **Total** | **~$290/month** | |

### Reading the Scenario B numbers

The total is dominated by **prompt categorization**. At Haiku 4.5 pricing ($1 / $5 per 1M input/output tokens), 120K prompts × ~2K input tokens each works out to ~$240 of input and ~$30 of output — about 93% of the bill.

Everything else combined (compute, orchestration, storage, networking, on-demand correlation, logs) is **under $25/month**. Switching the ETL from daily to hourly added roughly $1 of Step Functions cost, not $30.

Two practical takeaways:

- **The ETL frequency knob is cheap.** Run it hourly if you want fresh data; the marginal cost is negligible.
- **The Bedrock categorization knob is the lever that matters.** If your prompt volume grows linearly, this line grows linearly too. Strategies that help: tighten the few-shot prompt to reduce input tokens, batch categorization, sample rather than categorize 100% of prompts, or fall back to a cheaper model for low-confidence cases.

Correlation cost stays bounded by the 7-day cache regardless of how many users open the Productivity page; in practice most teams trigger only a handful of unique analyses per week.

## Tests

```bash
# Backend (Python)
python -m pytest tests/ -v

# Frontend (TypeScript)
cd frontend && npm run test
```

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/architecture.md) | Diagrams, ETL flow, DynamoDB schema, project structure |
| [Deploy Guide](docs/deploy.md) | Installation, cross-account setup, Makefile reference |
| [Changelog](docs/changelog.md) | Version history and release notes |

## Cleanup

To completely remove the Kiro Cost Analyzer stack and all associated resources:

> **Cost note.** After cleanup, you may see final charges for the current billing period. CloudWatch Logs are retained for 90 days and will continue to incur storage costs. Ensure all resources are deleted to avoid ongoing charges.

> **Warning.** The following commands will **permanently delete all data** in your S3 buckets. This action is **irreversible**. Ensure you have backups of any data you wish to retain before proceeding.

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
  --stack-name kiro-cost-analyzer-source-role \
  --profile SOURCE_ACCOUNT_PROFILE

# 7. (Optional) Delete the Identity Store role stack in the IDC account
aws cloudformation delete-stack \
  --stack-name kiro-identity-store-role \
  --profile IDC_ACCOUNT_PROFILE
```

> DynamoDB tables have deletion protection disabled by default. If you enabled it manually, you will need to disable it before stack deletion. The `sam delete` command handles Cognito User Pool, CloudFront distribution, and all other resources automatically.

## Contributing

Contributions are welcome — please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening an issue or pull request.

This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct). See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Security

Please report security issues per [SECURITY.md](SECURITY.md). Do **not** open a public GitHub issue for security findings.

## License

This project is licensed under the MIT-0 License. See [LICENSE](LICENSE) for the full text.
