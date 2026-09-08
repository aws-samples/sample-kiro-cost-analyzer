# Tasks — CI Test Workflow

Implementation plan. Tasks ordered so each checkpoint is independently verifiable. Optional tasks marked `*`.

Requirements referenced per task using `_Requirements: N.M_`.

---

## Checkpoint 1 — Test dependency manifest

- [ ] **1.1** Create `requirements-dev.txt` at the repository root. Compose the three deploy manifests with `-r backend/requirements.txt`, `-r etl/requirements.txt`, `-r agent/app/GitCorrelationAgent/requirements.txt`, then add `pytest`, `moto` and `hypothesis` with exact pins. Do not restate any package already pinned by a deploy manifest.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

- [ ] **1.2** Resolve the three pins empirically: create an empty virtual environment, `pip install -r requirements-dev.txt`, run `python -m pytest tests/ -q` from the repository root, and record the resolved versions back into the file. Confirm collection succeeds for the six agent test modules, which are the ones that fail if the agent manifest reference is missing.
  - _Requirements: 2.5, 3.3_

**Validation checkpoint 1**: from a clean clone and an empty virtual environment, `pip install -r requirements-dev.txt && python -m pytest tests/ -q` passes with no other manual step.

---

## Checkpoint 2 — Workflow skeleton

- [ ] **2.1** Create `.github/workflows/ci.yml` with `name: CI`, triggers `pull_request` on `[main]` and `push` on `[main]`. Use `pull_request`, never `pull_request_target`.
  - _Requirements: 1.1, 1.2, 5.5_

- [ ] **2.2** Declare `permissions: contents: read` at workflow level. Add no other permission and reference no secret.
  - _Requirements: 5.1, 5.2, 5.3_

- [ ] **2.3** Add a `concurrency` block keyed on the workflow name and `github.ref`, with `cancel-in-progress: true`.
  - _Requirements: 1.5_

**Validation checkpoint 2**: `actionlint .github/workflows/ci.yml` (or the GitHub Actions editor) reports no syntax error; the file declares no job yet.

---

## Checkpoint 3 — Backend gate

- [ ] **3.1** Add the `backend` job on `ubuntu-latest`: `actions/checkout@v4`, then `actions/setup-python@v5` with `python-version: '3.13'`, `cache: pip` and `cache-dependency-path: requirements-dev.txt`. The version must equal the `Runtime` declared in `template.yaml` `Globals`.
  - _Requirements: 3.1, 1.6_

- [ ] **3.2** Add the run steps: `pip install -r requirements-dev.txt`, then `python -m pytest tests/ -q`. Set no `working-directory`, so the suite runs from the repository root and `conftest.py` resolves its `sys.path` roots.
  - _Requirements: 3.2, 3.3_

**Validation checkpoint 3**: on a scratch branch, the `backend` check appears and passes.

---

## Checkpoint 4 — Frontend gate

- [ ] **4.1** Add the `frontend` job on `ubuntu-latest` with `defaults.run.working-directory: frontend`: `actions/checkout@v4`, then `actions/setup-node@v4` with `node-version: '22'`, `cache: npm` and `cache-dependency-path: frontend/package-lock.json`. Node 22 is required, not 20 — `check:locales` invokes `node --experimental-strip-types`, added in Node 22.6.0 (see `design.md` §3.4).
  - _Requirements: 4.1, 1.6_

- [ ] **4.2** Add the run steps in order: `npm ci`, `npm run lint`, `npm run test`, `npm run build`. Do not add a separate `check:locales` step — `build` already chains it.
  - _Requirements: 4.2, 4.3, 4.4, 4.5_

- [ ] **4.3** Confirm the two jobs declare no `needs` on each other, so they run concurrently and report independently.
  - _Requirements: 1.3, 1.4_

**Validation checkpoint 4**: on the same scratch branch, `backend` and `frontend` both appear, start at the same time, and both pass.

---

## Checkpoint 5 — Documentation

- [ ] **5.1** In `CONTRIBUTING.md`, under the existing "Validate your change locally before opening the PR" list, add the install step `pip install -r requirements-dev.txt` ahead of the backend command. Keep the documented local commands identical to the workflow's apart from verbosity.
  - _Requirements: 6.1, 6.2, 6.3_

- [ ] **5.2** Add an entry to `docs/changelog.md` under `## Unreleased` describing the new workflow, the new manifest, and the Node 22 requirement.
  - _Requirements: 6.4_

**Validation checkpoint 5**: a reader following only `CONTRIBUTING.md` from a clean clone can run both gates successfully.

---

## Checkpoint 6 — Verification and hand-off

- [ ] **6.1** Deliberately break one assertion on a scratch branch and confirm the corresponding check fails; revert. Repeat for the other gate.
  - _Requirements: 1.4_

- [ ] **6.2*** Push a second commit to the open scratch pull request and confirm the first run is cancelled rather than completing.
  - _Requirements: 1.5_

- [ ] **6.3*** Confirm no step in either job logs an AWS credential or attempts a real AWS endpoint, evidencing the suite stayed hermetic under CI.
  - _Requirements: 5.4_

- [ ] **6.4** Hand off to a maintainer: the `backend` and `frontend` checks now exist and can be marked required in branch protection. This is a repository-settings action, subject to organization policy, and is out of scope for this spec.
  - _Requirements: 1.6_

**Validation checkpoint 6**: a failing test produces a red check; the scratch branch and its pull request are deleted.

---

## Definition of done

- Both gates run on every pull request to `main` and every push to `main`, in parallel, as separately named checks.
- A clean clone reproduces the suite from `requirements-dev.txt` alone.
- The workflow holds `contents: read` only, references no secret, and configures no AWS credential.
- `CONTRIBUTING.md` and `docs/changelog.md` are updated in the same pull request.
- No file under `tests/`, `backend/`, `etl/`, `agent/` or `frontend/src/` was modified.
