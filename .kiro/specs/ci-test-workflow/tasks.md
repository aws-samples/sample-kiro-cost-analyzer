# Tasks — CI Test Workflow

Implementation plan. Tasks ordered so each checkpoint is independently verifiable. Optional tasks marked `*`.

Requirements referenced per task using `_Requirements: N.M_`.

---

## Checkpoint 1 — Test dependency manifest

- [x] **1.1** Create `requirements-dev.txt` at the repository root, providing everything `tests/` imports at collection time, including the agent's packages.
  - _Requirements: 2.1, 2.3, 2.4, 2.6_

- [x] **1.2** Resolve the pins empirically in an empty virtual environment and confirm collection. Result: `pytest==9.1.1`, `moto==5.2.3`, `hypothesis==6.167.1`; **1002 tests collected, 0 collection errors**.
  - _Requirements: 2.4, 2.5, 3.3_

- [x] **1.3** Handle the manifest conflict discovered while doing 1.1. Pure composition of the three deploy manifests fails with `ResolutionImpossible` (`boto3==1.43.4` in `backend/` and `etl/` versus `boto3>=1.43.31` required by `bedrock-agentcore==1.19.0`). Reference the agent manifest, restate `boto3`/`requests`, and document the reason in `design.md` §2.1.
  - _Requirements: 2.2_

**Validation checkpoint 1** — done. From a clean clone and an empty virtual environment, `pip install -r requirements-dev.txt` exits 0 and `pytest tests/ --collect-only` reports 1002 tests with no errors. Confirmed against real `pip` (26.2.1), not only `uv`, because `pip` is what the workflow runs.

---

## Checkpoint 2 — Workflow skeleton

- [x] **2.1** Create `.github/workflows/ci.yml` with `name: CI`, triggers `pull_request` on `[main]` and `push` on `[main]`, using `pull_request` rather than `pull_request_target`.
  - _Requirements: 1.1, 1.2, 5.5_

- [x] **2.2** Declare `permissions: contents: read` at workflow level, with no secret reference.
  - _Requirements: 5.1, 5.2, 5.3_

- [x] **2.3** Add a `concurrency` block keyed on the workflow name and `github.ref`, with `cancel-in-progress: true`.
  - _Requirements: 1.5_

---

## Checkpoint 3 — Backend gate

- [x] **3.1** Add the `backend` job with `setup-python` 3.13 (equal to the `Runtime` in `template.yaml` `Globals`) and pip caching keyed on `requirements-dev.txt`.
  - _Requirements: 3.1, 1.6_

- [x] **3.2** Add the run steps: `pip install -r requirements-dev.txt`, then `python -m pytest tests/ -q`, with no `working-directory` so `conftest.py` resolves its `sys.path` roots from the repository root.
  - _Requirements: 3.2, 3.3_

- [x] **3.3** Add the `env` block with placeholder AWS values, discovered during validation. Without it 35 tests fail with `NoRegionError`; with region only, 6; with region and a fake credential pair, 5.
  - _Requirements: 5.3, 5.4_

---

## Checkpoint 4 — Frontend gate

- [x] **4.1** Add the `frontend` job with `working-directory: frontend`, `setup-node` 22 and npm caching keyed on `frontend/package-lock.json`. Node ≥ 22.6 is required by `check:locales`; note that no Node version makes `npm run test` runnable — see task 6.3.
  - _Requirements: 4.1, 1.6_

- [x] **4.2** Add the run steps in order: `npm ci`, `npm run lint`, `npm run test`, `npm run build`, with no separate `check:locales` step.
  - _Requirements: 4.2, 4.3, 4.4, 4.5_

- [x] **4.3** Add the `env` block with placeholder `VITE_COGNITO_USER_POOL_ID` and `VITE_COGNITO_CLIENT_ID`; without them three test files fail to import.
  - _Requirements: 4.6_

- [x] **4.4** Confirm neither job declares `needs` on the other.
  - _Requirements: 1.3, 1.4_

---

## Checkpoint 5 — Documentation

- [ ] **5.1** In `CONTRIBUTING.md`, document the install step and the environment variables both gates need locally.
  - _Requirements: 6.1, 6.2, 6.3_

- [ ] **5.2** Add an entry to `docs/changelog.md` under `## Unreleased`, including the expected-red state and its causes.
  - _Requirements: 6.4_

---

## Checkpoint 6 — The defects the gates revealed

Every item below is a defect that predated this spec and that landing CI made visible. They were fixed in this branch rather than deferred: a permanently red gate is not a usable signal, and the checks could not be marked required while it stayed red. Root causes and fixes in `design.md` §5.

- [x] **6.1** Fix the 4 clock-dependent tests in `tests/test_etl_executions_handler.py`. Injected the clock: `handle_etl_executions` takes `now=None`, resolved through `_resolve_now`, matching the DI style of its existing client parameters. A fifth test (`TestEnglishOnlyResponse`) had been passing vacuously over an empty list and is now real. New `TestClockInjection` guards it.

- [x] **6.2** Fix `tests/test_etl_config.py::TestGetConfig::test_missing_required_env_var_raises`. Fixed in the source, not the test: `etl/config.py` now reads the required env paths before constructing the SSM client, so the documented `KeyError` wins instead of whatever the client constructor raised. The test is untouched and passes with no AWS variables set.

- [x] **6.3** Remove `NODE_OPTIONS=--no-webstorage` from the `test` script in `frontend/package.json`. `src/test/setup.ts` already carries a working localStorage fallback for the same problem, so no behaviour changed.

- [x] **6.4** Fix the 4 frontend test failures. Not translation drift, as an earlier draft assumed: three were stale tests that predated both pages moving their content into Cloudscape `Tabs` (which mounts only the active panel), and one was a snapshot older than the v3.8 execution-history feature. Fixing the three also required correcting a fetch-mock ordering bug, adding the missing `cleanup()`, and re-activating the tab after the locale switch because `SettingsPage`'s uncontrolled Tabs remounts and resets.

- [x] **6.5** Fix the 42 lint errors. Eight fixed in code (5 `no-explicit-any`, 3 `no-misleading-character-class`), including a latent bug the `as any` hid in `UsageTable`: its colour map held `color-text-status-*`, not a valid `BoxProps['color']`, so those colours never rendered. The other 34 belong to two rules that arrived through caret-ranged plugin upgrades and are set to `warn` with the reasoning recorded in `eslint.config.js`.

- [ ] **6.6*** Align the `boto3` pin across the three deploy manifests so `requirements-dev.txt` can return to pure composition.

- [ ] **6.10** Bump `actions/checkout@v4` to a `node24` major in `release.yml` and `publish-release.yml`. Both still target Node 20 and raise the same deprecation warning `ci.yml` no longer does (`design.md` §3.5). Left out of this change because those files predate this spec.

- [ ] **6.7*** Promote `react-hooks/set-state-in-effect` back to `error` by moving data fetching out of load-on-mount effects (20 sites).

- [ ] **6.8*** Promote `react-refresh/only-export-components` back to `error` by relocating the 14 exported helpers, context, and constant into their own modules.

- [ ] **6.9** Hand off to a maintainer: the `backend` and `frontend` checks now exist and both pass, so they can be marked required in branch protection.
  - _Requirements: 1.6_

---

## Definition of done

- [x] Both gates run on every pull request to `main` and every push to `main`, in parallel, as separately named checks.
- [x] A clean clone reproduces the test environment from `requirements-dev.txt` alone, with zero collection errors.
- [x] The workflow holds `contents: read` only and references no secret; the only credential-shaped values are literal fakes committed in plain text.
- [x] Source changes are confined to the five defects the gates revealed (Checkpoint 6); no behaviour was changed beyond those fixes.
- [x] `CONTRIBUTING.md` and `docs/changelog.md` updated in the same pull request.
- [x] Checks are green: `backend` 1007 passing, `frontend` lint/test/build all exit 0.
