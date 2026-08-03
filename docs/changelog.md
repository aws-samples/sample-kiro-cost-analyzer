# Changelog

> Back to [README](../README.md)

## Unreleased

### Security — Removed the source-bucket hot-swap feature and its wildcard IAM grant

- **Fixed, not just documented.** The Settings page's bucket name, source prefix, and prompts prefix fields are now read-only. `PUT /api/config/bucket`, `PUT /api/config/prompts-prefix`, `handle_put_config_bucket`, `handle_put_config_prompts_prefix`, and the `ValidateSourceBucket` IAM statement (`s3:ListBucket` on `Resource: "arn:aws:s3:::*"`) are all removed.
- **Why now**: this closes out the `TODO` tracked in the `v3.3` entry below and in `docs/security.md` — the wildcard grant was carried as a documented, accepted trade-off because the endpoint needed to validate arbitrary admin-supplied bucket names via `HeadBucket`. Removing the endpoint removes the need for the grant.
- **Deploy-time trade-off**: `SourcePrefix` and `PromptsPrefix` are now required template parameters (no `Default`), matching `SourceBucketName`. An explicitly empty string is still accepted for a bucket-root deployment. Changing the source bucket, source prefix, or prompts prefix now requires a redeploy.
- **Tests** — removed `TestPutConfigBucket` (`tests/test_backend_handler.py`) and `TestHandlePutConfigBucket` (`tests/test_config_handler.py`); removed the corresponding write-path assertions from `frontend/src/pages/__tests__/SettingsPage.test.tsx` and `ptBrSnapshots.test.tsx`. Ten now-dead translation keys removed from `en.json`/`pt-BR.json`, verified with `npm run check:locales`.

### Security — Migrated `react-router-dom` to `react-router@8.3.0`, closing the RSC CSRF advisory

- **Root cause fix, not a documented exception.** The previous release (see v3.3 below) documented GHSA-qwww-vcr4-c8h2 as a non-applicable `npm audit` finding because `react-router-dom` had not yet published an `8.x` build depending on the patched `react-router@8.3.0`. It has not since — `react-router-dom` stopped publishing at `7.18.2`; from `8.x` onward, the project consolidated into a single `react-router` package. Migrated `frontend/package.json` from `react-router-dom@7.18.2` to `react-router@8.3.0` and updated every import (`App.tsx`, `main.tsx`, 4 components, 8 pages, 3 test files — 16 files total) from `'react-router-dom'` to `'react-router'`. All exports used (`BrowserRouter`, `MemoryRouter`, `Routes`, `Route`, `Navigate`, `useNavigate`, `useLocation`, `useParams`, `useSearchParams`) are unchanged in the unified package.
- **Pinned, not range-constrained**: `react-router` is declared as an exact version (`8.3.0`, no `^`) in `frontend/package.json`, per the Holmes CSR finding that a caret range on a security-motivated dependency bump allows an unreviewed future minor/patch to be pulled in silently.
- **Result**: `npm audit` now reports 0 vulnerabilities (down from 2 High entries for the same advisory, previously listed once per `react-router`/`react-router-dom` node). Removed the corresponding "known finding, not applicable" section from `docs/security.md` since the advisory no longer applies to any dependency in the tree.
- **Verified**: `tsc -b` clean, `vite build` succeeds, and the existing Vitest suite passes at the same rate as before the migration (152/155 — the 3 pre-existing failures are unrelated `waitFor` timing issues in a settings-modal test, confirmed via `git stash` against the pre-migration tree).

## v3.3 — GitLab Provider Support & Security Hardening (2026-08-01)

### Note — source-bucket hot-swap feature removal tracked and completed

This entry originally tracked the `ValidateSourceBucket` wildcard IAM finding as a `TODO`. The feature removal described here has since been completed — see the "Security — Removed the source-bucket hot-swap feature and its wildcard IAM grant" entry above.

### Security — Fourth Holmes CSR scan: `identity-store-role.yaml` IAM scoping fix, log field removed

Ran a fourth Holmes CSR scan. Two genuinely new findings, both fixed; the rest were the same false positives from the previous scan re-flagged under new file version IDs (marked again in Holmes with reasons):

- **`identity-store-role.yaml` wildcard IAM Resource (High)** — the cross-account `IdentityStoreReadPolicy` granted `identitystore:DescribeUser`/`identitystore:ListUsers` on `Resource: "*"`, with an inline comment claiming "identitystore APIs do not support resource-level permissions." That claim was incorrect: the AWS-managed `AWSIdentityCenterExternalManagementPolicy` scopes the same two-action family to `arn:aws:identitystore::{account}:identitystore/{id}` plus the required companion `arn:aws:identitystore:::user/*`, confirmed via the AWS Identity Store service authorization reference. Fixed by scoping `Resource` to those two ARNs, parameterized by the existing `IdentityStoreId` template parameter. `IdentityStoreId` (previously informational-only, `Default: ""`) is now required — enforced with `AllowedPattern: "d-[0-9a-z]{10}"` in the template and a `$(error ...)` guard in the `make deploy-identity-store-role` target, since the policy now depends on a real value.
- **`git_repo_handler.py` logs repository URL (Medium)** — `handle_create_repo`'s success log included the configured `url`, which can carry internal hostnames or organization/project names. Removed; `repoId`/`provider` are sufficient to look the config up.
- **Tests** — `tests/test_identity_store_role_template.py` gains `test_policy_resource_is_scoped_to_configured_identity_store` and `test_identity_store_id_parameter_has_no_default` (7 cases total, up from 5). Full suite: 797 Python tests passing.

### Security — Third Holmes CSR scan: dependency bumps, test data cleanup, false-positive triage

Ran a third Holmes CSR scan after the `GITLAB_SSL_VERIFY` removal above. Findings and fixes:

- **`react` / `react-dom` (High)** — CVE-2026-23869 (React Server Components DoS, CVSS 7.5) affected `react`/`react-dom` `19.0.0-19.0.4`, `19.1.0-19.1.5`, `19.2.0-19.2.4`. `frontend/package.json` declared `^19.2.4`; the installed tree had already resolved to the patched `19.2.5`, so this was a stale declaration, not a live vulnerability. Bumped the declared floor to `^19.2.5` to match.
- **`js-cookie` override (High)** — same pattern: `package.json` declared the `overrides` entry as `^3.0.7`, but the installed tree had already resolved to the patched `3.0.8` (CVE-2026-46625, prototype pollution in `assign()`). Bumped the declared floor to `^3.0.8` to match. *(Superseded — the `overrides` entry is now pinned to the exact `3.0.8`, no caret; see the Holmes CSR fix noted under Unreleased.)*
- **`react-router-dom` (High, `npm audit`)** — GHSA-qwww-vcr4-c8h2 ("RSC Mode CSRF Bypass") affects `react-router` `>=7.12.0 <7.18.2` and `>=8.0.0 <8.3.0`. Bumped `react-router-dom` to `^7.18.2`, the latest published release and the patched floor of the affected 7.x line. `npm audit` still flags it because `react-router-dom` has not yet published an `8.x` release depending on the patched `react-router@8.3.0`, and its `7.18.2` build's own transitive resolution range nominally extends into the still-open `<8.3.0` window of the unpatched 8.x branch — not because a newer `react-router-dom` fix exists that this app is missing. **Not exploitable here regardless**: the vulnerability requires the `unstable_` RSC (React Server Components) APIs, which this app does not use anywhere (verified via `grep -r "unstable_\|RSC" frontend/src`, no matches) — it is a standard Cognito + Cloudscape client-rendered SPA using `react-router-dom`'s `BrowserRouter`/`Routes`. Documented as a known, non-applicable `npm audit` finding in `docs/security.md`, to be re-checked whenever `react-router-dom` next publishes a release. *(Superseded — `react-router-dom` was fully migrated to `react-router@8.3.0` (exact pin), see the Unreleased entry above; this dependency no longer exists in the codebase.)*
- **Real email domains in test fixtures (High, 2 sites)** — `tests/test_backend_handler.py` used `admin@co.com` and `a@b.com`; both `co.com` and `b.com` are real, registrable domains. Replaced with `admin@example.com` and `user@example.com`.
- **Unpinned `bedrock-agentcore-starter-toolkit` reference inside the changelog itself (Medium)** — an earlier entry in this changelog (documenting the v3.3 dependency-pinning fix) quoted the *old*, unpinned install command as narrative text, which a scanner reasonably flags as still-unpinned guidance if read in isolation. Pinned that quoted command to `==0.3.6` to match the actual fix.
- **Test assertion strengthened (Medium)** — `tests/test_config_handler.py::test_does_not_log_ssm_parameter_value` asserted only that the SSM parameter *path* never appears in logs, not that the parameter *value* (`"true"`/`"false"`) doesn't either. Added value-level assertions (parsing each JSON log line rather than substring-matching, to avoid false failures on unrelated JSON booleans) and a companion test for the `enabled=False` branch.
- **False positives triaged and marked** — 18 Bandit/Semgrep findings (B105/B106/B310/B506, `detected-aws-account-id`) confirmed as SSM parameter-path prefixes, test fixture marker strings, already-mitigated `urlopen()` scheme checks, and a `SafeLoader` subclass being misread as unsafe `yaml.load`. Marked false-positive in Holmes with reasons on each. The `s3:ListBucket` wildcard finding (already documented with a `holmes:suppress` comment in `template.yaml`) marked as an accepted trade-off.
- **Tests** — `tests/test_backend_handler.py` and `tests/test_config_handler.py` updated; full suite: 795 Python tests passing. `npm audit`: 0 vulnerabilities except the documented, non-applicable `react-router` RSC advisory above.

### Security — Removed the `GITLAB_SSL_VERIFY` TLS bypass entirely

- **Removed, not just defaulted-off.** The `GITLAB_SSL_VERIFY` opt-out introduced below (see "Fix — Self-hosted GitLab with a self-signed certificate could not be reached") and hardened in the Holmes remediation above is now removed from the codebase entirely — `gitlab_tool.py`'s `_ssl_verify_enabled()` function, the `verify=` kwarg on both `requests.get()` calls, and the `Makefile`'s `GITLAB_SSL_VERIFY` variable and `--env` passthrough are all gone. `requests` now always verifies certificates against the system trust store, with no environment variable or configuration path to disable it — matching the original design intent in `.kiro/specs/gitlab-provider-support/design.md` ("The tool does **not** expose a `verify=False` escape hatch").
- **Why**: two independent Holmes CSR scans flagged this as High severity even after the safe-by-default fix, because sample code that *can* disable TLS verification — regardless of default value or warning text — teaches the wrong pattern to anyone who copies it. The actual fix for a self-signed GitLab instance is a trusted certificate, not a bypass.
- **Unblocks this**: the self-hosted GitLab instance used during development now serves a Let's Encrypt certificate via the Omnibus package's built-in `letsencrypt['enable'] = true` support, reachable at a DNS name instead of a bare IP (Let's Encrypt does not issue certificates for IP addresses). `docs/deploy.md`'s "TLS certificate trust" section documents this path.
- **Tests** — `tests/test_gitlab_tool.py`'s `TestGitlabSslVerifyEnvVar` class (4 cases covering the opt-out) is removed; `test_certificate_verification_enabled_by_default` is replaced with `test_certificate_verification_never_disabled`, which asserts `verify` is never even passed as a kwarg to `requests.get()`.

### Fix — Self-hosted GitLab with a self-signed certificate could not be reached

- **Bug** — a GitLab correlation attempt against a self-hosted instance with a self-signed certificate failed every request with `SSLCertVerificationError: certificate verify failed: self-signed certificate`, surfacing as `GITLAB_REQUEST_FAILED`.
- **Fix** — `gitlab_tool.py` gains `_ssl_verify_enabled()`, reading the `GITLAB_SSL_VERIFY` environment variable (default: verification enabled) and passing the result as `verify=` on both the commits and merge-requests calls. When disabled, a `logger.warning` fires on every request naming the affected `repo_id`/`base_url`, so this is never a silent state in production observability. The `Makefile`'s `deploy-agentcore` target gained a matching `GITLAB_SSL_VERIFY` passthrough to `agentcore deploy --env`, so the setting persists on the AgentCore Runtime independently of how the Lambda side is deployed. (The Makefile's chosen default value, and the resulting security posture, are corrected below under "Security — Holmes CSR findings remediated".)
- **Tests** — `tests/test_gitlab_tool.py` gains `TestGitlabSslVerifyEnvVar` (4 cases: default-enabled, explicit `false`, case-insensitivity, and fail-safe on an unrecognized value).

### Security — Holmes CSR findings remediated

Ran a Content Security Review (CSR) scan (Holmes) against the full repository after the GitLab provider work above. Findings and fixes:

- **TLS verification insecure-by-default (High)** — the Makefile's `deploy-agentcore` target shipped `GITLAB_SSL_VERIFY ?= false`, so cloning this sample and running `make deploy-agentcore` deployed with GitLab certificate verification disabled by default. Default flipped to `GITLAB_SSL_VERIFY ?= true`; the opt-out for a genuinely self-signed GitLab instance is now an explicit, documented override (`make deploy-agentcore GITLAB_SSL_VERIFY=false`), never a silent default. `gitlab_tool.py`'s docstring, its runtime warning log, `docs/deploy.md`, `docs/security.md`, and `docs/architecture.md` all now state explicitly that this override **must not be used in production** — it removes protection against man-in-the-middle attacks on the connection carrying the `PRIVATE-TOKEN` credential, and exists only for sample/demo/lab environments where installing a trusted certificate on a self-hosted instance is not practical.
- **Sensitive data in logs (High/Medium, 8 sites)** — `github_tool.py` and `gitlab_tool.py` logged the full exception object (`exc=%s`) and up to 500 chars of HTTP response bodies on request failures; `agent/app/GitCorrelationAgent/main.py` logged the full `StructuredOutputException` (which can echo the model's malformed output, itself derived from user prompts); `custom_resources/mapping_migrator.py` and `etl/categorize_prompt_handler.py` logged `str(exc)` from DynamoDB/categorization failures (can carry userIds, Git usernames, or prompt content); `etl/writer_handler.py` used bare `print(traceback.format_exc())` instead of structured logging. All eight sites now log only the exception's class name (`errorType`), never the exception body, stack trace, or raw response text.
- **Unfiltered structured-logger kwargs (Medium)** — `shared/structured_logger.py`'s `_emit` forwarded every caller-supplied `**kwargs` value verbatim into the JSON log entry. Added `_redact_sensitive()`: any kwarg whose *key* matches `token|password|secret|credential|authorization|apikey|private[_-]?key` (case-insensitive) has its value replaced with `"[REDACTED]"` before serialization. Ordinary fields (`s3Key`, `recordCount`, `errorType`, etc.) pass through unchanged — this does not require callers to adopt an allowlist, only adds a defense-in-depth backstop.
- **Real email domains in sample data (High, 4 sites)** — `frontend/src/locales/en.json` and `pt-BR.json` used `your@email.com`/`user@company.com` (en) and `seu@email.com`/`usuario@empresa.com` (pt-BR) as placeholder text — `email.com` and `company.com`/`empresa.com` are real, registrable domains. All four replaced with the RFC 2606 reserved `example.com`. `docs/screenshots/README.md` also named a real personal email address in its own guidance about not doing exactly that; genericized.
- **Unpinned dependencies (Medium, 6 files)** — `agent/app/GitCorrelationAgent/requirements.txt` and `pyproject.toml` used `>=` ranges for `strands-agents`, `pydantic`, and `boto3`; `backend/requirements.txt` and `etl/requirements.txt` had no version constraints at all for `boto3`/`requests`; the `bedrock-agentcore-starter-toolkit` install instructions in `Makefile` and `docs/deploy.md` had no version pin. All six now pin exact tested versions (`==`).
- **Console logging in production frontend code (Low)** — removed a `console.log` in `PromptsTable.tsx` that ran behind an `import.meta.env.DEV` guard; low risk on its own, but the pattern invites a future edit to log a full response object instead of a count.
- **Accepted and documented, not fixed** — `template.yaml`'s `ValidateSourceBucket` IAM statement grants `s3:ListBucket` on `Resource: "arn:aws:s3:::*"`. This is a deliberate trade-off, not an oversight: `PUT /api/config/bucket` validates admin-supplied, potentially cross-account bucket names via `HeadBucket` (which requires `s3:ListBucket`, with no narrower IAM action), and the bucket name is arbitrary request-time input, not known at deploy time — see `.kiro/specs/cross-account-s3-access/`. Scoping the resource would either break the cross-account validation this endpoint exists for, or require a naming convention the feature does not have. A `holmes:suppress` comment documents the rationale in place.
- **Tests** — `tests/test_structured_logger.py` gains a `TestStructuredLoggerRedaction` class (7 cases) covering redaction of sensitive-looking keys, case-insensitivity, and pass-through of ordinary fields. `tests/test_writer_handler.py` updated for the `_write_csv_record`/`_write_prompt_record` signature change (now take a `logger` parameter). Full suite: 798 Python tests, 140 frontend tests passing.

### Fix — Correlation agent could silently cache an unrecoverable "Analysis could not be processed" result

- **Bug** — the Git-Kiro correlation agent's LLM occasionally emitted a final response whose JSON was syntactically invalid (e.g. an unquoted property name). The entrypoint correctly caught the parse failure and substituted a fallback (`impactScore: null`, generic "Analysis could not be processed" insight), but that fallback was then persisted and returned exactly like a normal successful analysis — with no error status slug — so the frontend's retry affordance never appeared and the user was stuck with a null-score result.
- **Root cause** — `agent/app/GitCorrelationAgent/main.py` asked the model to hand-format a JSON blob in free text and then parsed that text with `parse_agent_output`. Any malformed JSON in that text was a silent, structurally-undetectable failure one layer downstream from where it occurred.
- **Fix** — the entrypoint now passes `structured_output_model=CorrelationAnalysis` (a new Pydantic model in `prompts.py`, added alongside the existing `OUTPUT_SCHEMA` dict) to the Strands `Agent` call. Strands converts the schema into a tool specification the model is constrained to call and returns the already-validated result via `result.structured_output`, removing the malformed-JSON failure mode at the source rather than only detecting it after the fact. The only remaining fallback trigger is `strands.types.exceptions.StructuredOutputException`, raised by the SDK after its own internal validation retries are exhausted. See DD-6 in `.kiro/specs/agent-git-correlation/design.md`.
- **Tests** — `tests/test_agent_main.py` gains coverage for the `CorrelationAnalysis` model's field constraints (score range, correlation cap, confidence bounds, required bilingual insight keys) and for `_fallback_analysis()`'s shape.

### Documentation — Git diagrams and prose updated for the second Git provider

- `docs/git-correlation.drawio` — added the GitLab egress path (a `GitLab Tool` node calling a `GitLab Instance` node directly over HTTPS, mirroring the existing `GitHub Tool` → `GitHub API` pair's style) fed from the same `Amazon Bedrock AgentCore` node as the GitHub path. Updated `docs/architecture.md`'s alt text for `git-kiro-correlation-flow.png` to mention both providers. The exported `git-kiro-correlation-flow.png` itself still shows the GitHub-only flow — re-exporting the `.drawio` source is a manual draw.io step left to the maintainer.
- `docs/architecture.drawio` — added a `GitLab Tool` node and a `GitLab Instance` node inside the `Git-Kiro Correlation Agent` swimlane, wired from `Amazon Bedrock AgentCore` alongside the existing GitHub path. Updated `docs/architecture.md` and `README.md`'s alt text for `architecture.png` to mention both providers. The exported `architecture.png` itself still shows the GitHub-only agent group — re-exporting the `.drawio` source is the same deferred manual step.
- `docs/architecture.md` — the "Correlation agent" row, the "Git-Kiro correlation agent" narrative section, and its sequence diagram now describe provider-tagged repository descriptors and the GitLab Tool's direct REST API v4 call (no AgentCore Gateway hop, `PRIVATE-TOKEN` auth) alongside the unchanged GitHub Tool path. Added a "GitLab token scopes" subsection next to the existing "GitHub token permissions" table — the two use different authentication mechanisms (`PRIVATE-TOKEN` vs. OAuth-style bearer token) and different scope vocabularies, so they are documented as separate tables rather than merged. The "Why Bedrock AgentCore" design decision now names all three tools.
- `docs/features.md` — the Git-Kiro correlation and Git repository config bullets no longer read as GitHub-only.
- `docs/security.md` — the "Encryption" control row no longer claims all connections use TLS; a self-hosted GitLab instance configured over plain `http` is a documented, requirement-driven exception (Requirement 10.3 of `.kiro/specs/gitlab-provider-support/`).
- No changes were needed in `docs/deploy.md` (already provider-aware from an earlier task in this change set) or `docs/cost.md` / `CONTRIBUTING.md` / `SECURITY.md` / `CODE_OF_CONDUCT.md` (no Git-provider assertions found).

### Tooling — `make deploy-all` orchestrator and a clearer AgentCore preflight

- **`make deploy-all`** runs the full path in order — infrastructure, frontend, then the correlation agent — and validates the AgentCore prerequisites up front (via a new `check-agentcore-env` target) so it fails fast instead of after infra and frontend have already deployed. `make deploy` is unchanged (infra + frontend only) for users who do not want the agent.
- **`deploy-agentcore` preflight reordered and rewritten.** It now checks for an active virtualenv **first** — the `agentcore` CLI ships inside the project venv, so "CLI not found" without a venv was misleading — then checks the CLI, each with actionable setup steps (`python3 -m venv .venv` → `source .venv/bin/activate` → `pip install bedrock-agentcore-starter-toolkit==0.3.6`). `docs/deploy.md` documents `make deploy-all` in the Makefile reference.

### Fix — Correlation agent returned nothing: ARN now resolved by stable name, owned by the stack

- **Bug** — invoking the Git-Kiro correlation agent produced no result. The `kiro-cost-analyzer-correlation-worker` Lambda failed every invocation with `ResourceNotFoundException: No endpoint or agent found with qualifier 'DEFAULT' for agent '...runtime/GitCorrelationAgent-bnVS1RFwhi'`, and retried in a tight loop (~14 firings in ~40s) against an ARN that no longer existed. The AgentCore runtime had been recreated (new ID `...-nLdOow7N8j`), so no invocation ever reached it — its `otel-rt-logs` stream was empty.
- **Root cause** — the AgentCore runtime ID carries a server-generated 10-char suffix (`-bnVS1RFwhi`) that changes every time the toolkit recreates the runtime, which `make deploy-agentcore` did on every run (it regenerates `.bedrock_agentcore.yaml` with `agent_id: null`, forcing a create). The worker's `AGENT_RUNTIME_ARN` was hard-coded with that volatile suffix in `template.yaml` (two places), so each recreation left the IaC pointing at a dead runtime. The committed suffix was also account-specific — invalid for any other `aws-samples` consumer.
- **Fix** — the env var is renamed `CORRELATION_AGENT_RUNTIME_ARN` and is no longer hard-coded. `template.yaml` exposes a `CorrelationAgentRuntimeArn` parameter (default `"NONE"`) wired into both the backend and worker Lambdas via `!Ref`, plus a matching stack Output. `make deploy-agentcore` now resolves the runtime ARN by its **stable name** (`GitCorrelationAgent`) via `list-agent-runtimes` after deploying, then syncs it into the live stack with a surgical `update-stack --use-previous-template` that sets only `CorrelationAgentRuntimeArn` and preserves every other parameter with `UsePreviousValue` (robust to the gitignored `samconfig.toml` and to parameter drift). The worker now fails fast with a clear message when the ARN is still `"NONE"` (agent not deployed) instead of calling a non-existent runtime, and still clears the pending flag so the UI never hangs on "processing".
- **Tests** — `tests/test_correlation_worker.py` updated for the renamed env var and gains `test_unconfigured_runtime_arn_fails_clean`, which asserts the worker never calls AgentCore when the ARN is unconfigured yet still clears the pending flag.

### Refactor — Drop the redundant `StackName` template parameter

- `template.yaml` used a `StackName` parameter solely as a resource-name prefix (`!Sub "${StackName}-..."`, ~38 usages). That duplicated CloudFormation's built-in `AWS::StackName` pseudo-parameter and forced operators to pass the stack name twice (`--stack-name` *and* `StackName=`), which diverge silently if mistyped — the trap behind the earlier "Missing option --stack-name" confusion. All `${StackName}` references now use `${AWS::StackName}`, and the `StackName` parameter is removed from `Parameters`. Deploy examples in `docs/deploy.md` drop the `StackName=` override accordingly. Verified no-op via a no-execute changeset against the live stack: every resource reported `Replacement: False` (the resolved names are identical to the deployed stack, e.g. `kiro-cost-analyzer-analytics`).

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
- **Cost** — bilingual output adds ≈10-15% output tokens per analysis (~$0.017 vs ~$0.015 per Claude Sonnet call; rough estimate from token-count comparison at the time of this change, not a formal benchmark).
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
