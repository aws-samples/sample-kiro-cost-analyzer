# Cost Estimate

> Back to [README](../README.md)

The two scenarios below were estimated against `sa-east-1` pricing as of May 2026 and are intentionally rough — your actual bill depends on token mix, retention, and how busy your users are. The "heavy" scenario was sized against real telemetry from one heavy developer in the maintainers' deployment and extrapolated to 10 such users.

> Categorization runs automatically for every prompt ingested by the ETL. Correlation is on-demand and cached in DynamoDB for 7 days, so repeated requests for the same user/period cost nothing.

## Scenario A — light usage

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

## Scenario B — 10 heavy users, ETL hourly

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

## Reading the Scenario B numbers

The total is dominated by **prompt categorization**. At Haiku 4.5 pricing ($1 / $5 per 1M input/output tokens), 120K prompts × ~2K input tokens each works out to ~$240 of input and ~$30 of output — about 93% of the bill.

Everything else combined (compute, orchestration, storage, networking, on-demand correlation, logs) is **under $25/month**. Switching the ETL from daily to hourly added roughly $1 of Step Functions cost, not $30.

Two practical takeaways:

- **The ETL frequency knob is cheap.** Run it hourly if you want fresh data; the marginal cost is negligible.
- **The Bedrock categorization knob is the lever that matters.** If your prompt volume grows linearly, this line grows linearly too. Strategies that help: tighten the few-shot prompt to reduce input tokens, batch categorization, sample rather than categorize 100% of prompts, or fall back to a cheaper model for low-confidence cases.

Correlation cost stays bounded by the 7-day cache regardless of how many users open the Productivity page; in practice most teams trigger only a handful of unique analyses per week.
