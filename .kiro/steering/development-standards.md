---
inclusion: always
---

# Development Standards — Kiro Cost Analyzer

This document describes the practices, conventions, and patterns adopted in this project. It MUST be followed in every code, infrastructure, and documentation contribution.

---

## 1. Project Overview

**Kiro Cost Analyzer (KCA)** is a serverless application for analyzing Kiro usage and costs. The architecture is composed of:

- **Backend**: Lambda API (Python 3.13) behind API Gateway + Cognito Authorizer
- **Frontend**: React + TypeScript SPA with Cloudscape Design System, internationalized via `react-i18next`
- **ETL**: Step Functions pipeline (Standard + Distributed Map Express) with Python Lambdas
- **Infrastructure**: AWS SAM (`template.yaml`) + CloudFormation
- **Data**: DynamoDB (Single-Table Design) + S3 + SSM Parameter Store

---

## 2. Way of Working — Spec-Driven Development

### 2.1 Development Flow

Every significant feature follows a spec-driven flow with three documents under `.kiro/specs/{feature-name}/`:

1. **`requirements.md`** — Functional requirements with User Stories and Acceptance Criteria in SHALL/WHEN/THEN format
2. **`design.md`** — Technical design with diagrams, interfaces, data models, error handling, and correctness properties
3. **`tasks.md`** — Implementation plan with tasks traceable to requirements, incremental validation checkpoints, and optional tasks marked with `*`

### 2.2 Spec Conventions

- Requirements use formal language: `THE {component} SHALL`, `WHEN {condition} THEN`, `IF {condition} THEN`
- Each task references the specific requirements it implements (e.g., `_Requirements: 1.1, 1.6_`)
- Intermediate checkpoints ensure incremental validation
- Test tasks marked with `*` are optional for a fast MVP
- Correctness properties are defined in the design and validated by property-based tests
- Specs may reference external files via `#[[file:<path>]]`

### 2.3 Language

- **UI text and top-level documentation (README, `docs/**`, user-facing docs): English only.** The repository ships a single English `README.md`. Additional UI locales are supported via the i18n layer; see section 4.2 and the spec at `.kiro/specs/i18n-english-default/`.
- **Brazilian Portuguese (pt-BR) is a first-class supported UI locale.** Every user-facing string that exists in English also exists in pt-BR in `frontend/src/locales/pt-BR.json`. The pt-BR translation lives only in the runtime catalog — there is no Portuguese README, no Portuguese spec, and no Portuguese top-level documentation.
- **Code** (variable names, functions, classes, technical comments, log messages, structured-logger fields): **English**.
- **Docstrings and module-level comments**: English.
- **Spec documents**: English (new specs from 2026-04 onward). Older pt-BR specs are not retranslated.
- **Commit messages, PR titles and descriptions**: English.

---

## 3. Project Structure

```
├── backend/                  # API Lambda (handler + handlers/ + repository/ + models/ + utils/)
├── etl/                      # ETL pipeline (handlers + processors/ + repository/ + utils/)
├── frontend/                 # React + TypeScript SPA (Cloudscape + i18n)
├── shared/                   # Code shared between backend and etl
├── custom_resources/         # CloudFormation Custom Resources
├── scripts/                  # Utility and build-time scripts (e.g., check-locales.ts)
├── tests/                    # Python tests (pytest + moto + hypothesis)
├── docs/                     # Documentation and diagrams
├── template.yaml             # SAM template (IaC)
├── source-account-role.yaml  # Helper template for cross-account IAM role
├── samconfig.toml            # SAM deploy configuration
├── Makefile                  # Deploy automation
└── conftest.py               # Global pytest configuration
```

### 3.1 Backend Layout (Python)

```
backend/
├── handler.py                # Entry point — API Gateway request router
├── handlers/                 # One handler per domain (usage, config, users, prompts, feedback, etc.)
├── repository/               # Data access layer (DynamoDB)
├── models/                   # Dataclasses for typing
└── utils/                    # Utilities (logging, normalization)
```

### 3.2 ETL Layout (Python)

```
etl/
├── *_handler.py              # Lambda entry points (list, parse, writer, record_status, categorize, etc.)
├── processors/               # Processing logic (csv_processor, prompt_processor)
├── repository/               # DynamoDB write layer (analytics_writer)
└── utils/                    # Utilities (logging, name_resolver, sk_normalizer)
```

### 3.3 Frontend Layout (TypeScript/React)

```
frontend/src/
├── App.tsx                   # Main layout (AppLayout + routes)
├── main.tsx                  # Entry point (providers composition: I18nProvider → AuthProvider → App)
├── api/client.ts             # Generic HTTP client with auth
├── auth/                     # AuthProvider (Cognito) + useAuth hook
├── i18n/                     # i18n runtime (I18nProvider, useI18n, formatters, resolver)
├── locales/                  # Translation catalogs (en.json, pt-BR.json) + generated keys.d.ts
├── components/               # Reusable components (tables, cards, charts, LanguageSwitcher, etc.)
├── hooks/                    # Custom hooks (useLastUpdated, useSplitPanel)
├── pages/                    # Pages (one per route)
├── types/index.ts            # Centralized TypeScript interfaces
└── utils/                    # Utilities (cronHumanizer)
```

---

## 4. Coding Standards

### 4.1 Python (Backend + ETL)

#### Imports with fallback

All modules use try/except to support execution both as a Lambda (relative imports) and as tests (absolute imports):

```python
try:
    from repository.analytics_repository import AnalyticsRepository
except ImportError:
    from backend.repository.analytics_repository import AnalyticsRepository
```

#### Dependency injection

Handlers and repositories accept boto3 clients as optional parameters for testability:

```python
def handle_usage(query_params: dict, dynamodb_resource=None) -> dict:
    repo = AnalyticsRepository(table_name, dynamodb_resource=dynamodb_resource)
```

```python
class AnalyticsWriter:
    def __init__(self, table_name, data_bucket, dynamodb_resource=None, s3_client=None):
```

#### Structured logging

Use `StructuredLogger` (from `shared/structured_logger.py`) in every Lambda. Logs are emitted as JSON with consistent fields:

```python
logger = StructuredLogger("lambda-name", correlation_id)
logger.info("Starting parse", s3Key=key, fileType=file_type)
logger.error("Parse failed", errorType=type(exc).__name__, errorMessage=str(exc))
```

Mandatory fields: `timestamp`, `level`, `message`, `lambda`, `correlationId`. Log messages and field names are written in English.

#### Error handling

- ETL Lambdas: catch exceptions, log with stack trace, and re-raise (Step Functions manages retry)
- Backend API: catch `ClientError` for throttling (503), generic exceptions (500), invalid body (400)
- Never silence errors without logging them

#### User-facing strings in API responses

- Backend responses are English-only for every human-readable field (`message`, `description`, `humanReadable`, etc.).
- Stable machine codes (`status`, `error`, slugs, enum values) are untouched — they are identifiers, not prose.
- The frontend owns display translation. If a backend response needs to be shown in the user's locale, the frontend maps an English `status`/`error` slug to a translation key.
- Rationale and enumeration: see `.kiro/specs/i18n-english-default/design.md`.

#### Typing

- Use type hints on function signatures: `def handle_usage(query_params: dict) -> dict:`
- Use `from __future__ import annotations` for forward references
- Dataclasses in `backend/models/types.py` for domain types

#### Docstrings

- Modules: top-of-file docstring describing purpose and context
- Public classes and functions: docstring with description, Args, and Returns
- Format: Google-style
- Language: English

#### Environment variables

- Access via `os.environ.get("VAR_NAME", "default")`
- Names in UPPER_SNAKE_CASE
- Sensitive configuration via SSM Parameter Store (prefix `/kiro-cost-analyzer/`)

### 4.2 TypeScript/React (Frontend)

#### Design System

- Use **Cloudscape Design System** exclusively (`@cloudscape-design/components`)
- Do not write custom CSS for components that already exist in Cloudscape
- Follow layout primitives: `AppLayout`, `SpaceBetween`, `Grid`, `Header`

#### Components

- One component per file, exported as default
- Props typed with explicit interfaces
- Page components live under `pages/`; reusable components under `components/`
- Local state with `useState`; effects with `useEffect`; memoization with `useCallback` / `useMemo`

#### Internationalization (i18n)

KCA is fully internationalized. The runtime uses `react-i18next` + `i18next`, composed with Cloudscape's `I18nProvider` so native component strings follow the active locale.

- **Supported locales**: `en` (default) and `pt-BR`. Both catalogs have identical key sets.
- **Catalog files**: `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json`.
- **Catalog shape**: flat JSON, dot-notation keys (`dashboard.header.title`, `common.buttons.save`, `cron.days.MON`). Keys are sorted alphabetically in each file.
- **No hardcoded UI strings.** Every user-facing string in `frontend/src/pages/**`, `frontend/src/components/**`, and `frontend/src/hooks/**` MUST resolve via `t(key)` from `useI18n()`.
- **Interpolation**: `{{name}}` placeholder syntax (i18next default). `t('hello.user', { name: 'Ana' })` resolves `"Hello, {{name}}!"` → `"Hello, Ana!"`.
- **Formatters**: for numbers, dates, and times, use the locale-aware helpers exposed by `useI18n()`:
  - `formatNumber(value, options?)` — replaces `toLocaleString('pt-BR')`
  - `formatDate(value, options?)` — replaces `toLocaleDateString('pt-BR')`
  - `formatTime(value, options?)` — replaces `toLocaleTimeString('pt-BR')`
  - `formatDateTime(value, options?)` — combined date + time
  Do NOT call `toLocaleString('pt-BR')`, `toLocaleDateString('pt-BR')`, or `toLocaleTimeString('pt-BR')` directly. This rule is enforced by ESLint.
- **Language switcher**: a `LanguageSwitcher` component lives in the top navigation. User preference persists to `localStorage` under the key `kiro_locale`.
- **Locale resolution chain on first load** (deterministic): `localStorage.kiro_locale` → `navigator.language` (normalized to a supported locale when possible) → `'en'`.
- **Fallback chain at runtime**: `catalog[activeLocale][key]` → `catalog['en'][key]` → `key` itself. Missing keys emit one `console.warn` per session in non-production builds.
- **Build-time check**: `scripts/check-locales.ts` runs before `tsc -b` in `npm run build`. It fails the build if:
  - the two catalogs have divergent key sets
  - any value is empty or non-string
  - either file is not alphabetically sorted
  On success, it emits `frontend/src/locales/keys.d.ts` containing a `TranslationKey` string-literal union, which `t()` consumes for autocomplete and type checking.
- **Cron humanizer**: `frontend/src/utils/cronHumanizer.ts` is locale-aware via the same catalog keys (`cron.rate.*`, `cron.cron.*`, `cron.days.*`). Call signature: `humanize(expression, t)`.
- **Brand strings** (`"Kiro Cost Analyzer"`, `"Kiro"`) are the same in every locale — they live in `brand.*` keys and must never be translated.

##### Adding a new locale

1. Create `frontend/src/locales/<locale-tag>.json` with the **exact same keys** as `en.json`.
2. Register the locale tag in `frontend/src/i18n/constants.ts` under `SUPPORTED_LOCALES`.
3. Add the locale to the `LanguageSwitcher` label map, using the language's own name as the display label (e.g., `"Español"`, not `"Spanish"`).
4. If Cloudscape ships a message bundle for the new locale, import it in the `I18nProvider`; otherwise accept Cloudscape's English defaults for native component strings.
5. Run `npm run build` — the key-parity check catches any missing key.

Authoritative reference: `.kiro/specs/i18n-english-default/`.

#### API Client

- Use the centralized client at `api/client.ts` (`get`, `post`, `put`, `del`)
- The JWT token is managed automatically via `localStorage`
- Errors are typed with `ApiError` (distinguishes `isServerError` vs `isClientError`)
- `401` responses trigger an automatic redirect to login

#### Authentication

- Cognito via `amazon-cognito-identity-js`
- `AuthProvider` is a Context Provider at the root
- `useAuth()` hook for auth state
- Tokens stored in `localStorage` under keys prefixed `kiro_`
- Expired tokens are refreshed automatically

#### Types

- All interfaces centralized in `types/index.ts`
- Interfaces mirror the backend API contracts exactly
- Use `interface` (not `type`) for data objects

---

## 5. Data Patterns — DynamoDB Single-Table Design

### 5.1 Key Schema

| Entity | PK | SK |
|---|---|---|
| User daily stats | `USER#{userId}` | `STATS#DAILY#{date}` |
| Model distribution | `USER#{userId}` | `STATS#MODEL#{normalizedModelId}` |
| Trigger distribution | `USER#{userId}` | `STATS#TRIGGER#{normalizedTrigger}` |
| Category distribution | `USER#{userId}` | `STATS#CATEGORY#{normalizedCategory}` |
| Prompt metadata | `USER#{userId}` | `PROMPT#{timestamp}#{requestId}` |
| Global daily stats | `GLOBAL` | `STATS#DAILY#{date}` |
| Tier breakdown | `GLOBAL` | `STATS#TIER#{tier}#{date}` |
| Client type breakdown | `GLOBAL` | `STATS#CLIENT#{clientType}#{date}` |
| ETL execution status | `ETL_STATUS` | `EXEC#{executionName}` |

### 5.2 Sort Key Normalization

Use `normalize_sk_value()` from `shared/sk_normalizer.py` to produce DynamoDB-safe slugs:
- Lowercase → trim → replace special characters with hyphens → collapse hyphens → truncate at 128 chars.

### 5.3 Atomic Counters

Distributions (model, trigger, category) use `UpdateItem ADD` for atomic counting plus `SET if_not_exists` to preserve the original raw value:

```python
UpdateExpression="ADD #count :one SET rawValue = if_not_exists(rawValue, :raw)"
```

### 5.4 Hybrid Storage

Prompts with combined content > 4 KB are stored in S3 (`prompts-content/{requestId}.json`) instead of inline in DynamoDB. The `contentInS3` field indicates the strategy.

---

## 6. Infrastructure and Deploy

### 6.1 AWS SAM

- Template at `template.yaml` with `Transform: AWS::Serverless-2016-10-31`
- Runtime: `python3.13`; Architecture: `x86_64`
- Deploy configuration in `samconfig.toml` (default region: `sa-east-1`)
- Parameters via `parameter_overrides` in `samconfig.toml`

### 6.2 Makefile

- `make deploy` — Full deploy (infra + frontend)
- `make deploy-infra` — SAM build + deploy
- `make deploy-frontend` — Generates `.env.production` from CloudFormation outputs, builds, syncs to S3, invalidates CloudFront
- `make deploy-source-role` — Deploys the cross-account IAM role in the source account
- `make dev` — Local frontend development server

### 6.3 Security

- Cognito User Pool with SRP authentication
- API Gateway with `CognitoAuthorizer`
- Admin endpoints protected by `Admins` group membership check
- S3 buckets with `PublicAccessBlockConfiguration` enabled
- CloudFront with OAC (Origin Access Control)
- Least-privilege IAM policies (specific actions per resource)

### 6.4 Configuration Variables

Dynamic configuration via SSM Parameter Store:
- `/kiro-cost-analyzer/bucket-name` — Source S3 bucket
- `/kiro-cost-analyzer/source-prefix` — CSV prefix
- `/kiro-cost-analyzer/prompts-prefix` — Prompt log prefix
- `/kiro-cost-analyzer/identity-store-id` — IAM Identity Center
- `/kiro-cost-analyzer/etl-status` — Status of the last ETL execution
- `/kiro-cost-analyzer/source-bucket-role-arn` — Cross-account IAM role ARN (optional)

---

## 7. Testing

### 7.1 Python

- Framework: **pytest** with **moto** for AWS mocks
- Tests in `tests/` with `test_{module_name}.py` convention
- Each module has a corresponding test file
- Use `@mock_aws` from moto to simulate AWS services
- Dependency injection to swap boto3 clients in tests
- Fixtures to set up mocked DynamoDB tables
- Helpers for inserting test data (e.g., `_put_daily_stat()`)

### 7.2 Property-Based Testing

- Libraries: **Hypothesis** (Python) / **fast-check** (TypeScript)
- Used to validate universal correctness properties
- Minimum **100 iterations** per property
- Examples: output always valid, truncation, resilience to errors, percentage calculations, locale resolution totality, formatter locale coherence, catalog key parity

### 7.3 TypeScript/React

- Framework: **Vitest** + **Testing Library** + **jsdom**
- Configuration in `vite.config.ts` (`test` section)
- Setup in `frontend/src/test/setup.ts`
- Run with `npm run test` (uses `vitest --run` for a single execution)

### 7.4 Test Organization

- Unit tests: one file per module, testing isolated functions with mocks
- Integration tests: verify full flow with mocked DynamoDB
- Schema tests: verify that API responses match TypeScript interfaces
- **i18n regression tests**: pt-BR rendering is byte-for-byte identical to the baseline when `locale = 'pt-BR'`. A banned-strings regex on backend handler tests guards the English-only backend invariant.

---

## 8. General Conventions

### 8.1 Naming

| Context | Convention | Example |
|---|---|---|
| Python functions | snake_case | `handle_usage`, `_compute_summary` |
| Python classes | PascalCase | `AnalyticsRepository`, `StructuredLogger` |
| Python constants | UPPER_SNAKE_CASE | `MAX_BATCH_SIZE`, `CORS_HEADERS` |
| Python private functions | `_` prefix | `_build_response`, `_extract_claims` |
| React components | PascalCase | `SummaryCards`, `UsageTable`, `LanguageSwitcher` |
| React hooks | camelCase with `use` prefix | `useAuth`, `useLastUpdated`, `useI18n` |
| TypeScript interfaces | PascalCase | `UsageResponse`, `UserUsage`, `I18nContextValue` |
| Translation keys | dot-notation, lowercase areas | `dashboard.header.title`, `common.buttons.save` |
| Environment variables | UPPER_SNAKE_CASE | `ANALYTICS_TABLE`, `DATA_BUCKET` |
| DynamoDB keys | PascalCase with `#` separator | `USER#{userId}`, `STATS#DAILY#{date}` |
| SAM resources | PascalCase | `BackendFunction`, `AnalyticsTable` |

### 8.2 Dependencies

- Backend/ETL: `boto3` only (provided by the Lambda runtime)
- Frontend: Cloudscape, React, React Router, amazon-cognito-identity-js, `i18next`, `react-i18next`
- Dev: pytest, moto, hypothesis (Python); vitest, @testing-library/*, fast-check (TypeScript)
- Keep dependencies minimal; prefer stdlib and the AWS SDK

### 8.3 Git and Versioning

- Atomic commits per feature/fix
- Feature branches when practical
- Never commit secrets or credentials
- `.gitignore` covers `node_modules/`, `__pycache__/`, `dist/`, `.aws-sam/`, `.tmp-issues/`
- Commit messages and PR descriptions in English

### 8.4 Changelog

- **Location**: `docs/changelog.md`
- **Format**: reverse-chronological entries with version, title, and date (`## vX.Y — Title (YYYY-MM-DD)`)
- **Rule**: Every commit to `main` that introduces a user-visible change, infrastructure change, or security fix MUST include a corresponding changelog entry. This includes feature additions, bug fixes, security hardening, dependency updates, and breaking changes.
- **Granularity**: One entry per logical change set (a feature branch merged = one entry). Group related sub-items as bullet points under the version header.
- **Language**: English.
- **Releases are automated**: entries accumulate under `## Unreleased`. To cut a release, run the **Release** workflow (Actions → Release → choose bump type + title): it bumps the root `VERSION` file, promotes `Unreleased` to a versioned heading via `scripts/promote_changelog.py`, and opens a Release PR. Merging that PR triggers `publish-release.yml`, which creates the annotated `vX.Y` git tag and a GitHub Release whose notes are the promoted section. Never hand-edit version headings or the `VERSION` file outside this flow. The frontend displays the deployed version in the header (injected from `VERSION` at build time).

### 8.5 Documentation maintenance

The public documentation under `README.md` and `docs/**` is a living artifact. It MUST evolve with the codebase, not lag behind it. Outdated docs are worse than missing docs — they actively mislead readers of an `aws-samples` repository.

**When to update docs.** In the same pull request, update the relevant doc whenever you change:

- a deployment command, parameter name, or `Makefile` target;
- a CloudFormation Output, an environment variable, or an SSM parameter path;
- the DynamoDB key schema, a backend route, or an event payload;
- a region default, a Bedrock model identifier, or a region-availability requirement;
- a cost driver visible in the README estimate (new Lambda, new managed service, new always-on resource);
- the project structure (file moves, renames, top-level directory additions).

**Tone and framing.**

- **Sample-first tone.** Write as a sample, not a product. Avoid "managed", "production-ready", "enterprise-grade", "out of the box", "no SLA / no warranty / no support" disclaimer paragraphs, and any phrasing that promises behavior. State what the code does and how to read it. Cost figures are estimates with the workload assumption stated.
- **English-only.** The English `README.md` is canonical. There is no Portuguese README and no parallel translation of `docs/**`. The only translated content lives in `frontend/src/locales/*.json`.
- **No decorative emojis.** Avoid emojis in headings, bullets, and prose across `README.md`, `docs/**`, `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md`. They render inconsistently across viewers and read informally for the audience. Status badges from `shields.io` are fine; inline character "icons" (📊, 🔐, ✅, ⚠) are not.

**Integrity rules.**

- **No orphan references.** A doc that names a file path, command, IAM action, CloudFormation Output, environment variable, or spec MUST reference something that exists in the current commit. Run `grep` after any rename, move, or deletion.
- **Match the deployed reality.** Outputs, parameter names, region defaults, and stack names in the docs must match `template.yaml` and `samconfig.toml`. If you renamed a CloudFormation Output, update the corresponding `aws cloudformation describe-stacks --query` example.
- **Reviewable links.** When you cite a spec under `.kiro/specs/` from a public doc, confirm the file exists at the same path in the same commit.

**Diagram conventions.**

- **draw.io** is the canonical tool for architecture and data-flow diagrams. Commit the `.drawio` source alongside the exported `.png`. Keep `alt` text descriptive (used by screen readers and image search).
- **Mermaid** is reserved for sequence diagrams and small state machines, where the textual source in the markdown file is easier to review and amend in PRs than a re-exported PNG. Avoid Mermaid `flowchart`/`graph` for architecture — the auto-layout becomes unreadable past 6–7 nodes.

**Changelog parity.** Every doc reorganization, README rewrite, or documentation-only fix gets an entry under `Unreleased` in `docs/changelog.md`, later promoted to a versioned heading. See section 8.4.

**"Built with Kiro" narrative.** This sample was built end-to-end with Kiro using the spec-driven flow described in section 2. The README's *Built with Kiro* section and the *Using Kiro when contributing* section in `CONTRIBUTING.md` document that origin and the workflow others can apply. Treat these two sections as load-bearing:

- They MUST stay in sync with the actual contents of `.kiro/specs/` and `.kiro/steering/`. If you delete or restructure those folders, update the README and the contributing guide in the same PR (the rules in this section apply).
- They MUST keep the spec count roughly accurate. The README quotes a number of specs; check it against `ls .kiro/specs/` before editing the README.
- They MUST NOT inflate the claim. Do not promise that Kiro produced 100% of the code or that no human review happened. The honest framing is "built in collaboration with Kiro using a spec-driven flow", which is what is in the README today.
