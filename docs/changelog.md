# Changelog

> Back to [README](../README.md)

## Unreleased

### Documentation — Deploy guide restructured by scenario

- **`docs/deploy.md` rewritten** around the two real deployment topologies — *Scenario A (single account)* and *Scenario B (cross-account)* — each a complete, self-contained walkthrough instead of a single happy path plus an "optional" appendix. Establishes `sam deploy --guided` as the canonical first-run recipe that generates the gitignored `samconfig.toml` (after which the `make` targets work), and makes every raw `sam deploy` example complete with `--stack-name`, `--resolve-s3`, and `--capabilities`. Adds a callout distinguishing the `--stack-name` flag from the `StackName` template parameter. The cross-account flow now spells out the role-first ordering, a step to discover the source bucket's KMS key (`aws s3api get-bucket-encryption`), and `make deploy-agentcore` as an explicit step (same account as the app, project venv required). The Makefile-reference table now documents `KMS_KEY_ARN` as required for SSE-KMS source buckets (optional only for SSE-S3).
- **README install section** now leads with `sam deploy --guided` for the first deploy, and adds a cross-account/KMS prerequisite pointer.
- **Orphan reference fixes** — corrected the README CloudFront output query (`CloudFrontUrl` → `CloudFrontDomainName`, the actual stack output), the uninstall cross-account stack name (`kiro-cost-analyzer-source-role` → `kiro-cross-account-role`, the Makefile default), and the `docs/features.md` cross-account anchor.

### Fix — Clean-account provisioning for API Gateway and AgentCore

- **API Gateway account-level CloudWatch role** — the prod stage enables `AccessLogSetting`, which requires an account/region-global API Gateway CloudWatch Logs role. The template assumed it already existed, so a first deploy into a fresh account failed with `CloudWatch Logs role ARN must be set in account settings to enable logging` (and rolled back). `template.yaml` now provisions `AWS::ApiGateway::Account` + an IAM role with `AmazonAPIGatewayPushToCloudWatchLogs`, and the API `DependsOn` it. Note: `AWS::ApiGateway::Account` is a per-account/region singleton — on an account that already has a role configured, the stack takes ownership of that setting.
- **AgentCore deploy targets the right account** — `make deploy-agentcore` resolved the account with the configured profile but invoked the `agentcore` CLI without it, so the CLI used the default credential chain and could deploy into the wrong account. The Makefile now prefixes the `agentcore deploy` call with `AWS_PROFILE`/`AWS_REGION`/`AWS_DEFAULT_REGION` and echoes the target account/region.
- **AgentCore config no longer ships a stale agent identity** — the versioned `.bedrock_agentcore.yaml.template` hard-coded a specific `agent_id`/`agent_arn` from a previous deployment, so a fresh `agentcore deploy` attempted `UpdateAgentRuntime` on a non-existent runtime and failed with `ResourceNotFoundException`. Both fields are now `null` so the toolkit creates a new runtime. `s3_auto_create` flipped to `true` so the AgentCore sources bucket is created on first deploy instead of failing with `NoSuchBucket` on a clean account.

### Fix — ETL cross-account reads no longer silently degrade under SSM throttling

- **Bug** — during a high-concurrency ETL run (Distributed Map over 10k+ source files), some Parse invocations failed with `AccessDenied` on `s3:GetObject` against the cross-account source bucket, using the Lambda's *own* execution role instead of the configured cross-account role. Intermittent and silent — no error log pointed at the cause.
- **Root cause** — `etl/config.py:get_config()` issued six separate `ssm:GetParameter` calls per invocation with no caching. Under Distributed Map concurrency this exceeded the SSM `GetParameter` throughput limit (measured ~63 TPS against a ~40 TPS default). The optional reads (including `source-bucket-role-arn`) were wrapped in a mute `except Exception: <field> = ""`, so a throttled role-ARN read resolved to an empty string. An empty ARN makes `get_s3_client` return `None`, and the readers fall back to a default S3 client (the Lambda role) — producing a cross-account `AccessDenied`. The required `bucket_name` read (no try/except) had already succeeded, so logs showed a populated bucket and masked the failure.
- **Fix** — `get_config()` now performs a single batched `ssm:GetParameters` call, caches the result at module scope (one read per warm container instead of six per invocation), and uses an adaptive boto retry config. Transient SSM errors now propagate so Step Functions retries with backoff; the pipeline never degrades to single-account mode on a transient error. Genuinely absent optional parameters still resolve to `""`. `etl/parse_handler.py` no longer swallows config/AssumeRole errors — single-account fallback happens only when the role ARN is genuinely empty. The `parse` and `list-files` Lambda IAM policies in `template.yaml` gain `ssm:GetParameters` (a distinct action from `ssm:GetParameter`, required by the batched read).
- **Tests** — `tests/test_etl_config.py` rewritten for the batched read, per-container cache, and the new error-propagation contract (throttling raises; absent params resolve to `""`). `tests/test_parse_handler.py` gains two regression guards: the cross-account client must be forwarded to `read_prompt_file` (never `None` when an ARN is configured), and a config-read failure must propagate.

### Security — Frontend dependency vulnerabilities resolved (`npm audit`: 0)

- **Moderate (dev, non-breaking)** — bumped `brace-expansion` `5.0.5 → 5.0.6` (GHSA-jxxr-4gwj-5jf2, ReDoS-style resource consumption) and `postcss` `8.5.9 → 8.5.15` (GHSA-qx2v-qp2m-jg93, XSS via unescaped `</style>` in stringify output; pulls `nanoid 3.3.11 → 3.3.12`) via `npm audit fix`. Both are transitive dev dependencies (eslint / vite toolchain).
- **High (runtime)** — `amazon-cognito-identity-js@6.3.16` (latest) pins `js-cookie@2.2.1`, which is in the vulnerable range of GHSA-qjx8-664m-686j (prototype hijack in `assign()` enabling cookie-attribute injection). The 2.x line has no patch; the fix lands in `js-cookie@3.0.7+`. Added a package.json `overrides` entry forcing `js-cookie@^3.0.7` (resolves to `3.0.8`) instead of taking npm's suggested major **downgrade** of cognito to `1.24.0`. This app configures Cognito with the default `localStorage` backend (`AuthProvider.tsx` passes no `Storage` option), so the `CookieStorage` code path that consumes js-cookie is never instantiated — the override clears the advisory without affecting runtime behavior.
- **Build hygiene** — js-cookie 3.x dropped the default export cognito's unused `CookieStorage.js` imports, producing a benign `IMPORT_IS_UNDEFINED` Rollup warning. Added a narrowly scoped `onwarn` filter in `vite.config.ts` that suppresses only that exact warning (matched by code + module path) and lets all others through. Documented inline with the advisory reference and the dead-code rationale.

### Documentation — README slimmed down, deep content moved to `docs/`

- **README** — trimmed to a focused overview: what the project is, condensed feature list, stack, architecture pointer, install, uninstall, tests, what the sample demonstrates, and the *Built with Kiro* section. Removed the inline screenshot walkthrough, the two-scenario cost tables, and the standalone security-control table; these now live in dedicated docs and are linked from the README and the Documentation table.
- **`docs/features.md`** (new) — full feature walkthrough with all screenshots, moved out of the README.
- **`docs/cost.md`** (new) — light and heavy workload cost scenarios with the per-service breakdown and the "reading the numbers" analysis.
- **`docs/security.md`** (new) — defense-in-depth control table and threat-model pointer.

### Fix — Prompt categorization broken by guardrail region mismatch

- **Bug** — every prompt categorized as `Classification Error` after a fresh deploy. The Prompt History tab and the per-user category distribution chart rendered empty.
- **Root cause** — `CategorizePromptFunction` invoked Claude Haiku 4.5 via the `us.anthropic.*` cross-region inference profile, forcing the `Converse` call to land in `us-east-1`. The Bedrock guardrail (`AWS::Bedrock::Guardrail`) is regional and was created in the stack's deploy region (`sa-east-1`). The runtime call therefore hit `us-east-1` with a guardrail ID that does not exist there, returning `ValidationException: The guardrail identifier or version provided in the request does not exist.` The categorizer fell through to its `Classification Error` branch and every prompt got that label.
- **Fix** — switched `BEDROCK_MODEL_ID` to `global.anthropic.claude-haiku-4-5-20251001-v1:0` and `BEDROCK_REGION` to `!Ref AWS::Region`, so the model invocation lands in the same region as the guardrail. The IAM policy now includes the three resource ARNs the global cross-region inference profile requires (regional inference profile, regional foundation model, global foundation model with no region/account in the ARN), per the [Bedrock global CRIS docs](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html).

### State machine — categorization runs on every execution

- **Behavior change** — the `RecordStatusNoFiles` branch (no new files in S3) used to skip straight to the reconcile step, bypassing `ListUncategorized → CheckUncategorized → CategorizePrompts`. After the fix above, an admin can manually reset stale `category` values to `NOT_CATEGORIZED` to trigger a re-categorization without re-ingesting source data — but only if the categorization pass actually runs. `RecordStatusNoFiles` now flows through `ListUncategorizedPrompts` exactly like the normal "files processed" branch, so manual re-categorization works on any execution.

### Documentation — ETL pipeline updates

- `docs/architecture.md` — ETL section now describes five phases (List, Parse and Write, Record Status, Categorization, Reconcile). Added a "Reconcile phase (terminal step)" subsection pointing at `.kiro/specs/user-tombstoning/`. Added a `UserNamesTable` schema subsection documenting the new `status`, `tombstonedAt`, and `lastSeenInIdc` fields. Updated the `etl-data-flow.png` alt text to reflect five phases and the role of the categorization profile (Global CRIS to keep the call in-region with the guardrail). The exported `etl-data-flow.png` itself still shows four phases — re-exporting the `.drawio` source to add the Reconcile phase block is a manual draw.io step left to the maintainer.
- `README.md` — updated `etl-data-flow.png` alt text to mention five phases and the reconcile pass.
- `docs/deploy.md` — Bedrock Haiku 4.5 row mentions the global cross-region inference profile and the reason (guardrail co-location). Added a "re-categorize without re-ingesting source data" tip under section 3.

### Fix — Empty Prompt History on the Usage tab

Two independent bugs caused the Prompt History table to render "No prompts found" on the Usage tab even when the dataset contained prompts and the feature was enabled.

**Bug 1 — Self-lookup `userId` translation**

- **Symptom**: An admin opening their own profile at `/user/{cognitoSub}?tab=usage` got an empty Prompt History.
- **Root cause**: PROMPT# items in DynamoDB are keyed by the Kiro userId (Identity Center UUID), but the SPA navigated using the Cognito sub. `GET /api/prompts?userId={cognito-sub}` therefore queried a partition with no PROMPT# items.
- **Fix**: `backend/handler.py` now applies a narrow self-lookup translation on `GET /api/prompts` and `GET /api/prompts/{requestId}`. If the requested `userId` equals the caller's Cognito sub and the JWT carries a `custom:kiro_user_id` claim, the router swaps `userId` to that value before delegating. Substitution is sourced entirely from JWT claims signed by Cognito; the route stays admin-only and the authorization surface is unchanged.

**Bug 2 — Case-sensitive system category exclusion**

- **Symptom**: Even after the userId translation, the API returned only system items (`Empty`, `Classification Error`) and the frontend filtered them all out client-side, so the table still rendered empty.
- **Root cause**: `_SYSTEM_CATEGORIES` in `backend/handlers/prompts_handler.py` listed lowercase strings (`empty`, `not_categorized`, `classification error`), but the writer and the categorizer store mixed-case values (`Empty`, `NOT_CATEGORIZED`, `Classification Error`). DynamoDB `Attr.ne()` is case-sensitive, so the FilterExpression silently matched nothing and the handler returned 100 system items per page.
- **Fix**: aligned the constant casing to what the writer emits and updated the explicit-category check to compare against the same set.

**Tests**

- Six new cases in `tests/test_backend_handler.py::TestPromptsRoute` cover admin gating on both prompts routes, self-lookup translation on list and detail, pass-through when admins query a different user, and pass-through when the `custom:kiro_user_id` claim is absent.
- One new regression case in `tests/test_prompts_handler.py::TestHandleListPrompts::test_system_category_exclusion_casing_matches_written_values` pins the exclusion list casing.
- Two existing cases (`test_excludes_system_categories_by_default`, `test_allows_system_category_when_explicitly_requested`) updated to use the correct casing.

**Spec**

- `.kiro/specs/prompt-history-visibility/design.md` documents the userId translation under "Self-lookup `userId` translation" in the `backend/handler.py` section.

### Refactor — Single source of truth for system prompt categories

- **New module** `layers/shared/shared/categories.py` defines `CATEGORY_EMPTY`, `CATEGORY_NOT_CATEGORIZED`, `CATEGORY_CLASSIFICATION_ERROR`, and the aggregate `SYSTEM_CATEGORIES` frozenset. The literals in this module ARE the on-disk shape of the `category` field on PROMPT# items.
- **Producers updated** — `etl/writer_handler.py` (fresh-prompt write), `etl/prompt_categorizer.py` (empty-prompt short-circuit and error fallback), and `etl/list_uncategorized_handler.py` (DynamoDB scan filter) now import from `shared.categories` instead of inlining string literals.
- **Consumer updated** — `backend/handlers/prompts_handler.py::_SYSTEM_CATEGORIES` is now a re-export of `SYSTEM_CATEGORIES`.
- **Agent comment** — `agent/app/GitCorrelationAgent/tools/kiro_data.py` still inlines `"Empty"` (the agent runs in a separate AgentCore deployment and doesn't import the Lambda layer), but a comment now points at the canonical source so the two stay in sync on changes.
- **Tests** — new `tests/test_categories.py` with 9 cases pinning the literal values, the frozenset shape, and producer-consumer parity through source inspection. Existing `tests/test_prompts_handler.py` gains `test_system_categories_constant_is_sourced_from_shared` to ensure the handler's alias points at the shared frozenset.

### Cleanup

- Removed `tests/test_feedback_handler.py`, an orphan from commit `f1fb5b6` ("remove prompt content visibility and feedback feature") that referenced the long-deleted `backend/handlers/feedback_handler` module and broke `pytest` collection.
- Updated `tests/test_csv_parser.py::test_unknown_format_returns_empty_and_logs` to assert the new schema-validation log message introduced in `8094cf1`. The parser still fails closed; only the log text changed.

### Tooling — Wipe and reingest data

- New `make reingest-data` starts a fresh execution of the `${STACK_NAME}-etl-state-machine` Step Functions state machine and prints the console URL plus a CLI poll command. Account ID is resolved at runtime via `aws sts get-caller-identity` so the target works across deployments.
- New `make wipe-and-reingest` chains `nuke-data` (dependency, prompts for `yes` confirmation) followed by `reingest-data`. Useful after schema changes that require rebuilding analytics from the source CSV/prompt bucket.
- `scripts/nuke_all_tables.py` now reads `REGION` and `STACK_NAME` from the environment (defaulting to the original hard-coded values) so the Makefile can pass `make`'s `STACK_NAME ?=` and `REGION ?=` overrides through to the script. Existing `make nuke-data` behavior is unchanged for the default stack.

### User tombstoning — reconcile UserNamesTable against Identity Center

- **New ETL state** — `ReconcileUsers` runs at the end of every ETL state machine execution. Lists every user currently present in IAM Identity Center via `identitystore:ListUsers` (paginated), scans the `UserNamesTable` cache, and updates each row's `status` / `tombstonedAt` / `lastSeenInIdc` fields based on whether the user still exists in IDC.
- **Fail-safe behavior** — any `ListUsers` exception (auth, throttling, network) aborts the run silently with `status=error` and `tombstoned=0`. An empty IDC user list also aborts (treats it as misconfiguration). Per-row UpdateItem failures are logged and skipped — never abort the whole reconcile. The state machine wraps the new step in `Catch: ["States.ALL"]` so reconcile failures cannot block the data ingestion pipeline.
- **Schema extension** — `UserNamesTable` rows gain three optional fields: `status` (`"ACTIVE"` or `"TOMBSTONED"`), `tombstonedAt` (ISO date when status flipped), `lastSeenInIdc` (last successful presence confirmation). Read paths default missing `status` to `"ACTIVE"` so pre-feature rows continue working without migration.
- **Read-side filtering** — `GET /api/recommendations/tier-optimization` excludes tombstoned users from both the upgrade/downgrade `recommendations` array and the `inactiveSubscribers` array. `GET /api/usage` includes them with a `tombstoned: boolean` field so the frontend can render the badge.
- **Frontend** — Users tab renders a Cloudscape `Badge` with label "Removed from IDC" next to the display name when `user.tombstoned === true`, wrapped in a `Popover` that explains the tombstone semantics (historical activity preserved, excluded from actionable lists). Localized in `en` and `pt-BR`.
- **New SAM resource** — `ReconcileUsersFunction` Lambda with IAM scoped to `identitystore:ListUsers` + `dynamodb:Scan|UpdateItem` on the `UserNamesTable` only. State machine policy gains permission to invoke this Lambda.
- **Tests** — `tests/test_user_reconciler.py` (12 cases) pins the four-outcome decision matrix and the on-wire UpdateItem expression shape. `tests/test_reconcile_users_handler.py` (5 cases, moto-backed) covers the happy path, the lazy upgrade of pre-feature rows, IDC errors producing zero false tombstones (Property P2), and the empty-list refusal. `tests/test_recommendation_handler.py` gains a tombstone-filtering case.
- **Spec** — `.kiro/specs/user-tombstoning/` documents the design, the four correctness properties (idempotence, no false tombstones on errors, history preservation, restore symmetry), and the open questions around TTL and scheduling.


### Recommendation engine — active-day projection and inactive-subscriber detection


- **Active-day projection** — `compute_recommendations` now projects monthly usage from active days rather than calendar days: `projected_monthly_usage = (total_credits / days_active) × 30`. A user with 50 credits across 2 active days in a 30-day window is now projected at 750 credits/month instead of 50, which surfaces the upgrade signal for sporadic high-intensity users while still surfacing downgrades for users whose intensity sits comfortably under the next-lower tier.
- **Skip empty-window users** — users with `days_active == 0` are skipped instead of dividing by zero. This matches the case where a user's last activity falls outside the requested date range.
- **Inactive subscribers (new view)** — `compute_inactive_subscribers` flags paid users who have not generated activity in the last 30 days, sourced from `Activity_Summary.lastActiveDate`. Each entry carries `currentMonthlyCost`, `daysInactive`, `lastActiveDate`, and `annualWastedCost = currentMonthlyCost × 12`. The list is sorted by `annualWastedCost` descending so the most expensive idle seats appear first. Users with no `Activity_Summary` at all (paid tier but no activity ever recorded) are flagged unconditionally with `daysInactive=null`.
- **Lifetime, not windowed** — the inactive list is computed from a second, unwindowed `scan_user_stats` so dormant users (whose last activity falls outside the date picker) are still visible. The two scans are merged: windowed for projection, lifetime for tier presence.
- **API contract** — `GET /api/recommendations/tier-optimization` responses gain `period: { startDate, endDate, daysWindow }`, `inactiveSubscribers: [...]`, and `inactiveSummary: { totalInactive, totalAnnualWastedCost, thresholdDays }`.
- **Frontend** — Recommendations tab shows the analysis window as a description under "Optimization Summary": "Based on usage from {start} to {end} — {days} days. Projection assumes the user keeps the intensity of their active days." A new `<InactiveSubscribersTable />` renders below the upgrade/downgrade table with columns User, Current Tier, Last activity, Days inactive, Annual cost if inactivity continues. Localized in `en` and `pt-BR`.
- **Tests** — `tests/test_recommendation_engine.py` (16 cases total) covers active-day projection, the empty-window skip, calendar-window invariance, the regression scenario that prompted the active-day change, and 7 cases for `compute_inactive_subscribers` (threshold inclusivity, missing summary, corrupt date string, untracked tier, and ordering by wasted cost). `tests/test_recommendation_handler.py` (6 cases) covers the `period` block defaults, `daysActive` propagation, the inactive response block shape, and the unwindowed lifetime scan invariant.
- **Spec** — `.kiro/specs/tier-optimization-recommendations/design.md` updated: `UserUsageData` gains `days_active`, Property 3 (Projection linearity) reframed around active-day projection, and the API contract documents the new `period`, `inactiveSubscribers`, and `inactiveSummary` blocks.

### Documentation — Capabilities-first README and additional insights screenshot

- **Capabilities-first layout** — moved the `## Capabilities` section in the root `README.md` to immediately after the hero, so readers see what the app does (with screenshots) before reading the architectural framing. The remaining sections (What this sample demonstrates, Stack, Built with Kiro, Architecture, Security, Quick Start, Cost, Cleanup) keep the same order.
- **Bilingual insights screenshot** — added `docs/screenshots/insights.png` showing the AI-generated insights panel from the productivity report, surfaced under the AI-powered analysis sub-section of Capabilities. The accompanying bullet calls out that insights are generated in English and Brazilian Portuguese in a single LLM call.
- **users.png refresh** — replaced with a redacted capture (synthetic identities only).
- Updated `docs/screenshots/README.md` filename table.

### Documentation — README screenshots refresh

- **README screenshots** — replaced the four placeholder stubs with six real captures covering the hero (`dashboard.png`), the per-user usage table (`users.png`), the tier and client-type breakdowns (`breakdown-by-tier.png`), the tier optimization recommendations tab (`recommendations.png`), the user engagement funnel and segmentation panel (`user-engagement.png`), and the per-user productivity report with the Git-Kiro Impact Score (`user-activity-report-1.png`). Updated `docs/screenshots/README.md` filename table to match.

### Bilingual correlation insights

- **Bilingual insights** — Git-Kiro correlation analyses now emit insights in both English (`en`) and Brazilian Portuguese (`pt-BR`) in a single LLM call. Response shape `insights: { en: string[], "pt-BR": string[] }` with parallel ordering (index `i` is the same insight in each language). The frontend selects the list via the active locale and falls back to `en` when missing.
- **Status slug contract** — backend correlation responses replace the human-readable `message` prose with stable English `status` slugs (`GIT_MAPPING_MISSING`, `GITHUB_TOKEN_MISSING`, `GITHUB_AUTH_FAILED`, `GITHUB_RATE_LIMIT`, `INSUFFICIENT_DATA`, `AGENT_TIMEOUT`, `AGENT_ERROR`). The frontend maps each slug to a translation key under `productivity.correlation.status.*` and renders a Cloudscape `Alert` of appropriate severity (info / warning / error).
- **Write-side coercion in the worker** — `correlation_worker.lambda_handler` now coerces the agent's `insights` payload to the canonical bilingual map before calling `put_analysis`, so DynamoDB items are written in the new shape directly. Read-side coercion in `AnalyticsRepository.get_latest_analysis` remains as a fallback for pre-deploy items.
- **Legacy cache coercion** — `AnalyticsRepository.get_latest_analysis` coerces pre-deploy `insights: List<String>` items to `{ "en": [], "pt-BR": <legacy list> }` on read. The underlying DynamoDB item is never mutated; legacy entries drain via the existing 7-day TTL.
- **i18n** — 7 new keys per locale under `productivity.correlation.status.*` (679 total, parity verified).
- **Cost** — bilingual output adds ≈10-15% output tokens per analysis (~$0.017 vs ~$0.015 per Claude Sonnet call).
- **Spec**: `.kiro/specs/agent-git-correlation/` (Requirement 8).

### Open-source readiness

- **Open-source readiness** — added MIT-0 `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SECURITY.md` at the repository root in preparation for publishing to `aws-samples`
- **Single-source documentation** — removed `README.pt-BR.md`; English `README.md` is now the canonical top-level documentation. The Brazilian Portuguese UI locale remains a first-class supported locale via `frontend/src/locales/pt-BR.json`
- **README rewrite** — added a brief "AWS sample" framing, badges, services-by-layer stack table, "What this sample demonstrates" / "Who might find it useful" sections, and explicit prerequisites including Bedrock model availability per region.
- **Architecture doc expansion** — `docs/architecture.md` now opens with a table of contents, summarizes the four runtime surfaces, includes two Mermaid sequence diagrams (ETL happy path and correlation cache miss), absorbs the DynamoDB schema and project structure that previously lived only in the now-removed Portuguese README, and adds a "Design decisions" section explaining the Distributed Map Express choice, single-table DynamoDB, AgentCore over direct `InvokeModel`, the two-Bedrock-model split, Cloudscape, the `sa-east-1` default, and the i18n model
- **Deploy doc — region matrix** — `docs/deploy.md` adds a "Region and model availability" section with an explicit Bedrock-model checklist and the steps required to deploy outside `sa-east-1`
- **Cost estimate refresh** — `README.md` Cost section rebuilt against `sa-east-1` pricing as of May 2026, sized from real telemetry of one heavy developer in the maintainers' deployment. Adds a second "10 heavy users + hourly ETL" scenario that totals ~$290/month, with prose calling out that ~93% of the cost is Bedrock Haiku 4.5 categorization and that ETL frequency is a near-free knob (~+$1 hourly vs daily)
- **"Built with Kiro" narrative** — `README.md` adds a section documenting that the sample was produced end-to-end with Kiro using a spec-driven flow (~20 specs under `.kiro/specs/`, conventions in `.kiro/steering/`). `CONTRIBUTING.md` adds a "Using Kiro when contributing" section with: a decision table for spec-driven vs vibe-coding vs no-agent contributions; the spec workflow; patterns that work well (point at steering early, separate plan from execution, use sub-agents for context gathering); what to keep out of the agent loop (final security review, cost decisions, public messaging); and three example prompts. Steering section 8.5 calls out the "Built with Kiro" narrative as a load-bearing section that must stay in sync with the actual `.kiro/specs/` and `.kiro/steering/` contents
- **README screenshots** — added four screenshot slots (hero, per-user usage table, tier-optimization recommendations, Git-Kiro correlation Impact Score) with descriptive alt text and HTML capture instructions inline. Placeholder PNGs ship under `docs/screenshots/` so the layout renders correctly until a maintainer drops in real captures. `docs/screenshots/README.md` documents the canonical filenames, dimensions (1600x900 or 1920x1080, PNG, light theme), anonymization rules, and when to re-shoot
- **Removed internal UI/UX analysis** — `docs/ui-ux-analysis.md` (internal review document with private deployment URLs and product critique) deleted
- **Steering update** — `.kiro/steering/development-standards.md` updated to reflect English-only top-level documentation; pt-BR is preserved as a runtime UI locale only. Added section 8.5 "Documentation maintenance" covering when to update docs, sample-first tone (no product-pitch phrasing, no decorative emojis), integrity rules (no orphan references, match the deployed reality), and diagram conventions (draw.io for architecture; Mermaid for sequence diagrams only)

## v3.2 — CSV Model Distribution & Schema Validation (2026-05-25)

- **Model message ingestion** — dynamic `*_messages` columns from Kiro CSV reports are now extracted and stored as a `modelMessages` Map attribute on `STATS#DAILY#` items (reduces N reads of `STATS#MODEL#` items to 0 extra reads for model distribution)
- **New_User flag** — `New_User` column extracted and persisted as `newUser` boolean (only when `true`)
- **CSV schema validation** — new `csv_schema_validator.py` module validates headers before row processing; critical columns (UserId, Date, Credits_Used) reject the file; non-critical issues warn but continue; dynamic model columns recognized as valid
- **Legacy format support** — minimal validation for `by_user_analytic` format (Date + UserId) as safety net
- **Backward compatible** — existing items without `modelMessages` continue to work; API returns the field automatically via existing `_convert_decimals` recursion
- **Spec**: `.kiro/specs/csv-model-distribution/`

## v3.1.2 — Prompt History Visibility (2026-05-22)

- **Admin-controlled prompt display** — dual-gate access control (Admins group + feature toggle via SSM)
- **Backend** — `_FeatureFlagCache` with 300s TTL (fail-closed on SSM errors); `GET /api/prompts` (paginated, category filter); `GET /api/prompts/{requestId}` (full content with S3 support); `PUT /api/config/prompt-history-enabled` (toggle)
- **Frontend** — `PromptHistoryToggle` in Settings > Prompts tab; `PromptsTable` with pagination, category filter, 100-char truncation; `PromptDetailPanel` in SplitPanel; conditional rendering (admin + feature enabled)
- **Security** — no prompt content or SSM values in logs (strict log safety)
- **i18n** — full en + pt-BR support for all new strings
- **Spec**: `.kiro/specs/prompt-history-visibility/`

## v3.1.1 — Security Review Findings (2026-05-22)

- **TLS enforcement** — removed stale `S3_BUCKET_SSL_REQUESTS_ONLY` guard suppressions from all 4 S3 buckets (DenyInsecureTransport policies were already in place)
- **Guard/checkov/noqa documentation** — added inline justification comments to all suppressions in `template.yaml` and ETL handlers; created `.threatmodel/suppressions-registry.md`
- **GitCorrelationAgent log sanitization** — exception logging now extracts only `Error.Code` and `Error.Message` from ClientError, preventing potential credential/path leakage in CloudWatch Logs
- **Threat model mitigations** — formal justifications added to all 5 "Will Not Action" mitigations (M-0003, M-0006, M-0007, M-0008, M-0009)
- **DynamoDB STD documentation** — `docs/architecture.md` updated with complete key schema (17 entities, attributes, GSI)

## v3.1 — Tier Optimization Recommendations (2026-05-08)

- **Recommendation engine** — pure-function module with Decimal arithmetic; projects monthly usage, computes overage costs, finds optimal upgrade tier, identifies downgrade candidates
- **Backend endpoints** — `GET /api/recommendations/tier-optimization`, `GET/PUT /api/config/tier-pricing`; pricing stored in SSM
- **Recommendations tab** — Dashboard tab with summary card, filterable table, setup prompt
- **User table badges** — "↑ Upgrade" / "↓ Downgrade" inline badges with detail modal
- **Pricing Settings panel** — admin-only form with pre-populated defaults (PRO/PRO_PLUS/POWER)
- **Date range integration** — uses Dashboard date picker (default: last 30 days)
- **i18n** — 54 new keys (658 total), en + pt-BR parity verified

## v3.0 — Git-Kiro Correlation Agent (2026-05-05)

- Replaced periodic Git Sync pipeline with on-demand AI agent on Amazon Bedrock AgentCore
- Claude Sonnet 4.6 performs semantic correlation via GitHub Tool + Kiro Data Tool (MCP)
- GitHub-only (removed GitLab, Bitbucket, CodeCommit connectors)
- New `GET /api/productivity/{userId}/correlation` with DynamoDB cache (7-day TTL)
- Frontend rewritten with Impact Score, correlations table, insights panel

## v2.9 — Navigation consolidation & Lambda Layer (2026-05-04)

- Dashboard consolidated (Overview + Users tabs)
- User detail with tabs (Usage + Productivity + Git)
- Single `SharedLayer` with all cross-cutting code
- Removed all `try/except ImportError` fallback blocks

## v2.8 — Productivity & Git Analysis (2026-04-28)

- Productivity page with daily timeline, category breakdown, hourly distribution
- Four Git provider connectors with unified format
- Git sync pipeline (Step Functions, daily at 00:30 UTC)
- Impact Index via Pearson correlation
- Git settings page (admin-only) with repo CRUD and user mappings

## v2.7 — ETL error propagation (2026-04-26)

- ETL child executions no longer silently succeed on Lambda exceptions
- `ToleratedFailurePercentage: 100` + `CheckEtlErrors` Choice state
- RecordStatus properly counts failures and reports to SSM

## v2.6 — i18n and English as default locale (2026-04-25)

- Full internationalization via react-i18next + i18next
- English default, pt-BR first-class supported locale
- User settings modal (language + visual mode)
- Dark mode with "Browser default" option
- Locale-aware formatters replacing all `toLocaleString` calls

## v2.5 — Cross-Account S3 Access (2026-04-23)

- STS AssumeRole for source buckets in another account
- Helper template `source-account-role.yaml`
- `make deploy-source-role` target
- Settings UI for role ARN configuration

## v2.4 — Category Feedback Loop (2026-04-23)

- Users correct categories, admins review, corrections enrich the classifier
- FeedbackTable in Amazon DynamoDB
- Approved corrections update prompts and export few-shot examples to Amazon S3

## v2.3 — Classifier improvement (2026-04-18)

- Model: Nova 2 Lite → Claude Haiku 4.5 (accuracy: ~13% → ~95%)
- MaxConcurrency raised to 50
- Retry scoped to transient errors only

## v2.2 — AI Prompt Categorization (2026-04-17)

- PromptCategorizer with 14 categories via Amazon Bedrock
- Standard Map with MaxConcurrency=20
- Category badges and distribution chart in frontend

## v2.1 — UI/UX Quick Wins + Tier 2 (2026-04-16)

- "Last 30 days" default period
- CSV export fix
- Branding on login page
- ETL schedule display
- Skeleton loading, SplitPanel for prompts
