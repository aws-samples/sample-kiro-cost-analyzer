# Design — CI Test Workflow

## 1. Shape of the change

Two files are added and two are edited. Nothing under `tests/`, `backend/`, `etl/`, `agent/` or `frontend/src/` is touched.

| File | Change | Why |
|---|---|---|
| `requirements-dev.txt` | new | The single manifest that satisfies every import in `tests/`. Composes the three deploy manifests and pins the three test-only libraries. |
| `.github/workflows/ci.yml` | new | Runs the two existing gates on pull requests and on pushes to `main`. |
| `CONTRIBUTING.md` | edited | Documents the install command; the two local gates are already listed but do not mention how to obtain `pytest`. |
| `docs/changelog.md` | edited | Entry under `## Unreleased`. |

## 2. The test dependency manifest

### 2.1 Composition was the intent, and it is not satisfiable

`tests/` imports both the test libraries and the runtime packages of every deployment unit. The intended shape composed the three deploy manifests with `-r`, so each stayed authoritative and a bump in one could not diverge from what CI installs.

That combination does not resolve. `pip install` exits with `ResolutionImpossible`:

| Manifest | Pin | Effective boto3 constraint |
|---|---|---|
| `backend/requirements.txt` | `boto3==1.43.4` | `==1.43.4` |
| `etl/requirements.txt` | `boto3==1.43.4` | `==1.43.4` |
| `agent/.../requirements.txt` | `bedrock-agentcore==1.19.0` | `>=1.43.31` |
| `agent/.../requirements.txt` | `strands-agents==1.50.2` | `>=1.26.0,<2.0.0` |

Each Lambda deployment package is built separately, so the three pins never meet at deploy time and this breaks no deploy. They do meet in a single test environment, and there they are mutually exclusive.

The agent's floor wins, because its packages are imported at collection time by six test modules and cannot be skipped, whereas `boto3` is API-compatible across this range for what the tests exercise. So the manifest references the agent and restates the other two:

```
-r agent/app/GitCorrelationAgent/requirements.txt

boto3>=1.43.31
requests==2.33.1

pytest==9.1.1
moto==5.2.3
hypothesis==6.167.1
```

This partially gives up Requirement 2.2 and cannot satisfy 2.3 as originally written; both are amended in `requirements.md`. The consequence to keep in view is a fidelity gap: the suite runs a newer `boto3` (resolved to 1.43.89) than `backend/` and `etl/` deploy with. Verified after the change: 1002 tests collected with zero collection errors, and the failure set is identical to the one produced under the older `boto3`, so the newer resolution introduces no regression.

Aligning `boto3` across the three deploy manifests would let this file return to pure composition. That is a change to deploy manifests and is deliberately not made here.

### 2.2 All three deploy manifests are required, including the agent's

The agent manifest is the non-obvious one, and omitting it breaks collection rather than a single test. Six test modules import agent code, and the imports resolve to packages that exist only in `agent/app/GitCorrelationAgent/requirements.txt`:

| Import site | Import | Provided by |
|---|---|---|
| `tests/test_agent_main.py` | `from pydantic import ValidationError` | `pydantic` |
| `tests/test_agent_main.py` → `agent.app.GitCorrelationAgent.main` | `from bedrock_agentcore.runtime import BedrockAgentCoreApp`, at module top level | `bedrock-agentcore` |
| `tests/test_agent_main.py` → `agent.app.GitCorrelationAgent.prompts` | `from pydantic import BaseModel, Field` | `pydantic` |
| `tests/test_github_tool.py`, `test_gitlab_tool.py`, `test_kiro_data_tool.py`, `test_ssm_token.py` | `agent.app.GitCorrelationAgent.tools.*` | same tree |

No test stubs `bedrock_agentcore` or `pydantic` in `sys.modules` — the only such stub in the suite is `boto3` in `tests/test_ssm_token.py`. So these are genuine import-time dependencies of collection, and a manifest that omits them fails before any assertion runs.

The narrower alternative — pinning only `pydantic` and `bedrock-agentcore` directly, skipping `strands-agents` and `bedrock-agentcore-starter-toolkit` — was rejected. It requires knowing which subset every current and future agent test transitively imports, it re-pins two packages that the deploy manifest already pins, and it saves only install time in a job that caches its wheels anyway.

### 2.3 Pin selection

`pytest==9.1.1`, `moto==5.2.3` and `hypothesis==6.167.1`, resolved by installing into an empty virtual environment and running the suite (task 1.2). Exact pins rather than floors because a Hypothesis or `moto` minor release changing default behaviour would otherwise turn into an unexplained CI failure on an unrelated pull request.

None of the five failures recorded in §6 is version-induced: they reproduce identically across the older and newer `boto3` resolutions, and their causes are a wall-clock dependency and an unset region, not library behaviour.

## 3. The workflow

### 3.1 Triggers, permissions, concurrency

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

`permissions: contents: read` at workflow level is the whole of Requirement 5.1: it replaces the default token scope for every job, so no step can write to the repository even if a future edit adds one. Requirement 5.2 follows from the absence of `pull-requests: write` rather than from a convention anyone must remember.

`pull_request` — not `pull_request_target` — is what satisfies Requirement 5.5. `pull_request` runs fork code against a read-only token with no secret access; `pull_request_target` would run the workflow with the base repository's privileges while checking out fork code, which is the escalation path this design must not open.

`concurrency` keyed on the ref satisfies Requirement 1.5. The key includes the workflow name so a future second workflow does not cancel this one's runs.

### 3.2 Backend job

```yaml
backend:
  name: backend
  runs-on: ubuntu-latest
  env:
    AWS_DEFAULT_REGION: us-east-1
    AWS_REGION: us-east-1
    AWS_ACCESS_KEY_ID: testing
    AWS_SECRET_ACCESS_KEY: testing
    AWS_SESSION_TOKEN: testing
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: '3.13'
        cache: pip
        cache-dependency-path: requirements-dev.txt
    - run: pip install -r requirements-dev.txt
    - run: python -m pytest tests/ -q
```

The `env` block is not optional and was not anticipated before validation. `botocore` resolves a region and a credential pair when a client is constructed, which happens before `moto` intercepts anything; on a runner there is no `~/.aws/config` to resolve them from. Measured on a clean environment: 35 failures with nothing set, 6 with only `AWS_DEFAULT_REGION`, 5 with the region and the fake credential pair. The values are deliberately fake and no test reaches a real endpoint, so the suite stays *offline* — but it is not *self-contained*, which is what Requirement 5.4 originally asserted. That requirement is amended.

`3.13` is not a free choice: `template.yaml` declares `Runtime: python3.13` in `Globals`, and Requirement 3.1 binds the gate to it. Requirement 3.4 makes the coupling a review obligation, since nothing enforces it mechanically.

No `working-directory` is set, so `pytest` runs from the repository root. This matters more than it appears: `conftest.py` builds `sys.path` from `os.path.dirname(__file__)`, inserting `layers/shared`, `backend`, `etl` and the root itself, which is what lets the tests use the same bare imports (`from shared.x`, `from handlers.y`) that Lambda sees at runtime. Running from any other directory would still find `conftest.py` but is a needless deviation from the documented local command (Requirement 3.3).

`-q` in CI against `-v` locally is the verbosity difference Requirement 6.3 explicitly permits: CI logs are read only when they fail, and a 60-module `-v` run buries the failure.

### 3.3 Frontend job

```yaml
frontend:
  name: frontend
  runs-on: ubuntu-latest
  defaults:
    run:
      working-directory: frontend
  env:
    VITE_COGNITO_USER_POOL_ID: us-east-1_TESTPOOL
    VITE_COGNITO_CLIENT_ID: testclientid1234567890
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with:
        node-version: '22'
        cache: npm
        cache-dependency-path: frontend/package-lock.json
    - run: npm ci
    - run: npm run lint
    - run: npm run test
    - run: npm run build
```

The two `VITE_` values are read by `src/auth/AuthProvider.tsx` at module load, which constructs a `CognitoUserPool` eagerly. Without them three test files fail to import with `Both UserPoolId and ClientId are required`. A Cognito pool id and app-client id are not secrets, and these are placeholders in any case.

Script mapping, read from `frontend/package.json`:

| Step | Script | Covers |
|---|---|---|
| `npm run lint` | `eslint .` | lint |
| `npm run test` | `NODE_OPTIONS=--no-webstorage vitest --run` | Vitest component tests |
| `npm run build` | `npm run check:locales && tsc -b && vite build && npm run report:i18n-sizes` | locale parity, type-check, production build |

`build` is the step that satisfies Requirement 4.4 and 4.5 without a fourth command: its first link is `check:locales`, which fails on key divergence, wrong sort order or an empty value. `tsc -b` inside `build` is also the only type-check in the gate — `lint` does not type-check.

`npm ci` rather than `npm install` satisfies Requirement 4.2: it installs exactly the lockfile and fails if `package.json` and `package-lock.json` disagree.

### 3.4 Node version — the issue's 20 is wrong, and 22 is necessary but not sufficient

Two independent constraints come from `frontend/package.json`, and only one of them is satisfiable by choosing a version.

**`check:locales` needs Node ≥ 22.6.** It runs `node --experimental-strip-types ../scripts/check-locales.ts`, and that flag was introduced in Node 22.6.0. `scripts/check-locales.ts` is genuine TypeScript, so the flag is what lets Node execute the file at all and cannot simply be dropped. On the Node 20 the issue specifies, it is an unrecognized option and the process exits before the script runs, failing `build` on a correct catalog. Confirmed working on Node v22.23.2 and on v24.20.0.

**`test` cannot run on any version.** The script is `NODE_OPTIONS=--no-webstorage vitest --run`, and `--no-webstorage` does not exist. Verified directly: `bad option` on both v22.23.2 and v24.20.0, as a CLI flag and via `NODE_OPTIONS`. The only flag in that family is `--experimental-webstorage`, which is opt-**in** — Web Storage is already off by default, so the script is disabling something that was never on, using a flag no release provides. `npm run test` exits 9 regardless of Node version. Choosing 24 instead of 22 does not help.

So Node 22 is the right choice for the two gates that can pass (`lint`, `build`), and the `test` gate is blocked on a `package.json` fix that this spec does not make — see §5.

`frontend/package.json` declares no `engines` field and the repository has no `.nvmrc`, so nothing in the tree pins the version for a reader, which is how the issue arrived at 20. Requirement 4.1 is written against the toolchain's needs rather than a literal version for this reason. Adding `engines` or `.nvmrc` would make the constraint explicit for contributors too; it is left out because it changes install behaviour for everyone (`npm` warns, `engine-strict` hard-fails) and belongs in its own change.

### 3.5 Action version pinning

Actions are referenced by major tag — `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4` — matching the convention already used by `pr-title.yml`, `release.yml` and `publish-release.yml`, all of which reference `@v4`/`@v5` tags.

Pinning to full commit SHAs is the stronger supply-chain posture and was considered. It is rejected here for consistency: this workflow should not introduce a second convention alongside three existing workflows, and a repository-wide move to SHA pinning is a separate change that should cover all four files at once. All three actions are first-party `actions/*`.

## 4. Correctness properties

These are the invariants a reviewer should check the workflow against; none requires a property-based test, since the artifact is configuration rather than code.

- **P1 — No privilege.** The workflow grants exactly `contents: read` and references no repository secret. It does set `AWS_*` variables, but their values are literal fakes committed in plain text, not credentials (§3.2).
- **P2 — Collection completeness.** Installing `requirements-dev.txt` into an empty environment is sufficient for `pytest tests/` to collect every module with zero collection errors. Verified: 1002 tests collected. *Passing* is a separate matter — see §5.
- **P3 — Minimal restatement.** Only `boto3` and `requests` are restated from a deploy manifest, and only because pure composition does not resolve (§2.1). Nothing else is duplicated.
- **P4 — Runtime coherence.** The Python version in `ci.yml` equals the `Runtime` in `template.yaml`.
- **P5 — Command parity.** The commands in `CONTRIBUTING.md` and in `ci.yml` differ only in verbosity flags.
- **P6 — Gate independence.** Neither job declares `needs` on the other, so a backend failure still produces a frontend verdict.
- **P7 — Offline.** No test reaches a real AWS endpoint or the network; `moto` intercepts the AWS calls and the HTTP clients are mocked.

## 5. Known pre-existing failures — CI is red on landing

The workflow was validated locally against `main` before landing. Three of the four gate commands fail, and every failure predates this spec and is caused by repository code, not by the workflow. Adding CI does not create these; it reveals them. They are recorded here so a reviewer is not surprised by a red check set.

| Gate | Exit | Result |
|---|---|---|
| `pytest tests/` | 1 | 997 pass, 5 fail |
| `npm run lint` | 1 | 42 errors |
| `npm run test` | 9 | does not execute |
| `npm run build` | 0 | passes |

**Backend — 4 expired time bombs.** `backend/handlers/etl_executions_handler.py:152` computes its cutoff from real wall-clock time (`datetime.now(timezone.utc) - timedelta(days=days)`), while `tests/test_etl_executions_handler.py:26` hardcodes `_NOW = datetime(2026, 8, 20, ...)` and never freezes the clock. With the default 5-day window, every fixture execution fell outside the cutoff once real time passed 2026-08-25, and the handler correctly returns an empty list (`assert 0 == 1`). Affected: `TestHappyPath::test_two_executions_one_enriched`, `TestRunningExecution::test_running_execution_fields`, `TestNoMatchingExecRecord::test_no_record_counters_are_none`, `TestWindowFiltering::test_cutoff_excludes_old_and_stops_paging`. The fix is to inject or freeze the clock; both change tests and are out of scope.

**Backend — 1 non-hermetic test.** `tests/test_etl_config.py::TestGetConfig::test_missing_required_env_var_raises` does `patch.dict(os.environ, {}, clear=True)` and then calls `get_config()`, which builds a real boto3 SSM client. Clearing the environment also removes the region, so `NoRegionError` is raised instead of the expected `KeyError`. It passes only where `~/.aws/config` supplies a region, which is why it passes on a developer machine and cannot pass on a runner. The `env` block in §3.2 does not help: the test clears it.

**Frontend — `test` script is unrunnable.** `--no-webstorage` exists in no Node release (§3.4), so `npm run test` exits 9 everywhere. `CONTRIBUTING.md` has been documenting this as a local gate, which means nobody has been running the Vitest suite. Run directly, with the two `VITE_` variables set, it is 205 passing and 4 failing across 2 files — 3 in `src/__tests__/localeSwitchIntegration.test.tsx` (pt-BR strings such as `ARN da Role do Identity Store` not found) and 1 stale snapshot in `src/pages/ptBrSnapshots.test.tsx`, all consistent with pt-BR catalog drift.

**Frontend — 42 lint errors:** 20 `react-hooks/set-state-in-effect`, 14 `react-refresh/only-export-components`, 5 `@typescript-eslint/no-explicit-any`, 3 `no-misleading-character-class`.

None of this is fixed here, because `requirements.md` puts test and source changes out of scope and the fixes span four unrelated defects. Each warrants its own issue and its own pull request. Until they land, `backend`, and the `lint` and `test` steps of `frontend`, are expected red.

## 6. Out of scope

Carried from `requirements.md`: no new or modified tests, no branch-protection change, no coverage tooling, no release or deploy concern, no dependency-update automation. Additionally out of scope here: adding an `engines` field or `.nvmrc` (§3.4), migrating the repository to SHA-pinned actions (§3.5), aligning `boto3` across the three deploy manifests (§2.1), and every defect listed in §5.
