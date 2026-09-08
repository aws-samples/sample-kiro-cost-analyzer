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

### 2.1 Why composition rather than a flat list

`tests/` imports both the test libraries and the runtime packages of every deployment unit. Restating those runtime pins in a second file would create two sources of truth: a `boto3` bump in `backend/requirements.txt` would leave CI installing the old one, and the divergence would surface as a confusing test failure rather than as a dependency error. Composing with `-r` keeps each deploy manifest authoritative (Requirement 2.2, 2.6).

```
# requirements-dev.txt
-r backend/requirements.txt
-r etl/requirements.txt
-r agent/app/GitCorrelationAgent/requirements.txt

pytest==<pin>
moto==<pin>
hypothesis==<pin>
```

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

The three test libraries are pinned to exact versions (Requirement 2.4), resolved by installing into an empty virtual environment and confirming the suite passes (task 1.2). Exact pins rather than floors because a Hypothesis or `moto` minor release changing default behaviour would otherwise turn into an unexplained CI failure on an unrelated pull request.

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

Script mapping, read from `frontend/package.json`:

| Step | Script | Covers |
|---|---|---|
| `npm run lint` | `eslint .` | lint |
| `npm run test` | `NODE_OPTIONS=--no-webstorage vitest --run` | Vitest component tests |
| `npm run build` | `npm run check:locales && tsc -b && vite build && npm run report:i18n-sizes` | locale parity, type-check, production build |

`build` is the step that satisfies Requirement 4.4 and 4.5 without a fourth command: its first link is `check:locales`, which fails on key divergence, wrong sort order or an empty value. `tsc -b` inside `build` is also the only type-check in the gate — `lint` does not type-check.

`npm ci` rather than `npm install` satisfies Requirement 4.2: it installs exactly the lockfile and fails if `package.json` and `package-lock.json` disagree.

### 3.4 Node 22, not 20 — the issue's stated version does not work

Issue #54 specifies Node 20. That would fail the `build` step. `check:locales` runs:

```
node --experimental-strip-types ../scripts/check-locales.ts
```

`--experimental-strip-types` was introduced in Node 22.6.0. On Node 20 it is an unrecognized option and the process exits before the script runs, so `build` — and with it Requirement 4.3 — fails on a correct catalog. `scripts/check-locales.ts` is genuine TypeScript, so removing the flag is not an option either; it is the mechanism that lets Node execute the `.ts` file at all. The flag was confirmed working on Node v22.23.2, the version this repository is developed against.

`frontend/package.json` declares no `engines` field and the repository has no `.nvmrc`, so nothing in the tree pins the version for a reader — which is how the issue arrived at 20. Node 22 is the current LTS line, satisfies the flag, and satisfies `vite@^8` and `vitest@^4` in `devDependencies`, both of which are past dropping Node 20. Requirement 4.1 is written against the toolchain's needs rather than a literal version for this reason.

An `engines` field or an `.nvmrc` would make the constraint explicit for contributors as well as CI. It is deliberately left out of this spec: it changes install behaviour for every contributor (`npm` warns, and `engine-strict` would hard-fail) and belongs in its own change rather than riding along with a CI workflow.

### 3.5 Action version pinning

Actions are referenced by major tag — `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4` — matching the convention already used by `pr-title.yml`, `release.yml` and `publish-release.yml`, all of which reference `@v4`/`@v5` tags.

Pinning to full commit SHAs is the stronger supply-chain posture and was considered. It is rejected here for consistency: this workflow should not introduce a second convention alongside three existing workflows, and a repository-wide move to SHA pinning is a separate change that should cover all four files at once. All three actions are first-party `actions/*`.

## 4. Correctness properties

These are the invariants a reviewer should check the workflow against; none requires a property-based test, since the artifact is configuration rather than code.

- **P1 — No privilege.** The workflow grants exactly `contents: read`, references no secret, and configures no AWS credential. Verifiable by reading the file.
- **P2 — Manifest completeness.** Installing `requirements-dev.txt` into an empty environment is sufficient for `pytest tests/` to collect and pass. Verified by task 1.2 and re-verified by CI on every run.
- **P3 — No duplicated pins.** No package pinned in a deploy manifest is pinned again in `requirements-dev.txt`.
- **P4 — Runtime coherence.** The Python version in `ci.yml` equals the `Runtime` in `template.yaml`.
- **P5 — Command parity.** The commands in `CONTRIBUTING.md` and in `ci.yml` differ only in verbosity flags.
- **P6 — Gate independence.** Neither job declares `needs` on the other, so a backend failure still produces a frontend verdict.

## 5. Out of scope

Carried from `requirements.md`: no new or modified tests, no branch-protection change, no coverage tooling, no release or deploy concern, no dependency-update automation. Additionally out of scope here: adding an `engines` field or `.nvmrc` (§3.4), and migrating the repository to SHA-pinned actions (§3.5).
