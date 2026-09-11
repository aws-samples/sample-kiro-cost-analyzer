# Requirements — CI Test Workflow

The repository carries an extensive test suite that no automation ever runs. `tests/` holds 60+ pytest modules using `moto` and Hypothesis and covering the backend handlers, the ETL processors, the shared layers and the correlation agent; the frontend carries Vitest component tests plus a locale-parity check that the build already chains. The only GitHub Actions workflows today are `pr-title.yml`, `release.yml` and `publish-release.yml`, none of which executes a test. A pull request that breaks every assertion in the repository still presents a green check set to its reviewer, so the suite protects the project only to the extent that each contributor remembers to run it and reports honestly when it fails.

A second, related gap makes that suite hard to run even for a contributor who wants to. `pytest`, `moto` and Hypothesis are imported throughout `tests/` but pinned in no manifest anywhere in the repository — the three existing `requirements.txt` files describe only Lambda runtime dependencies. There is no `pyproject.toml`, `setup.cfg`, `tox.ini` or `pytest.ini`. A fresh clone therefore cannot reproduce the environment the suite needs without a contributor guessing at versions, and two contributors can easily test against different ones.

Closing both gaps requires no new tests and no change to any existing test. Everything the gates need already exists; it needs a manifest that describes it and a workflow that runs it.

## Glossary

- **Gate**: a command that fails the build when the code is wrong. This spec introduces no new gates; it automates the ones already present.
- **Backend gate**: `pytest` over `tests/`, covering backend, ETL, shared layers and agent code.
- **Frontend gate**: the `lint`, `test` and `build` scripts in `frontend/package.json`. `build` chains `check:locales`, so locale parity is inside this gate rather than beside it.
- **Test dependency manifest**: the single file a contributor or a CI runner installs to obtain everything `tests/` imports.
- **Deploy manifest**: one of the three existing `requirements.txt` files (`backend/`, `etl/`, `agent/app/GitCorrelationAgent/`), each describing the runtime dependencies of one deployment unit.
- **Hermetic suite**: a suite that reaches no network and no real AWS account, because `moto` intercepts the AWS calls and the HTTP clients are mocked.

## Requirement 1: The existing suites run on every proposed change

**User Story.** As a reviewer, I want both suites to have run before I read a pull request, so that a green check set means the tests actually passed rather than that nobody ran them.

### Acceptance Criteria

1.1. WHEN a pull request targets the default branch THEN the backend gate and the frontend gate SHALL both run.

1.2. WHEN a commit is pushed directly to the default branch THEN both gates SHALL run.

1.3. THE backend gate and the frontend gate SHALL run concurrently, so that neither waits on the other and each reports its own outcome independently.

1.4. IF either gate fails THEN the workflow SHALL report a failed check for that gate.

1.5. WHEN a new commit supersedes an in-flight run for the same ref THEN the superseded run SHALL be cancelled rather than run to completion.

1.6. THE workflow SHALL surface each gate as a separately named check, so that a maintainer can mark either one as required in branch protection.

## Requirement 2: A fresh clone can reproduce the test environment

**User Story.** As a contributor on a new machine, I want one documented command to install everything the suite needs, so that my local result and the CI result come from the same dependency set.

### Acceptance Criteria

2.1. THE repository SHALL provide a single test dependency manifest that, when installed, satisfies every import in `tests/`.

2.2. THE manifest SHALL obtain runtime dependencies by reference to the existing deploy manifests wherever those references resolve together, and SHALL restate a pin only where referencing them is unsatisfiable, with the reason recorded in `design.md`.

2.3. THE manifest SHALL provide every package that `tests/` imports at collection time, including those owned by the agent's deploy manifest.

2.4. THE manifest SHALL pin an exact version for each test-only dependency.

2.5. WHEN the manifest is installed into an empty virtual environment on a fresh clone THEN `pytest` SHALL collect every module in `tests/` with zero collection errors and the suite SHALL pass, with no further manual step beyond the environment variables named in Requirement 5.3.

2.6. THE manifest SHALL NOT introduce a Lambda runtime dependency that no deploy manifest already declares.

> **Amended after validation, then resolved.** 2.2 and 2.3 originally required referencing all three deploy manifests and restating nothing. That was unsatisfiable at the time: `backend/` and `etl/` pinned `boto3==1.43.4` while the agent's `bedrock-agentcore==1.19.0` requires `boto3>=1.43.31`, so `pip` exited with `ResolutionImpossible`, and 2.2 was widened to permit restating a pin where referencing was impossible. Task 6.6 has since aligned the deploy pins on `boto3==1.43.92`, so the manifest is pure composition and both criteria are met as originally written — 2.2's escape clause is now unused. It is kept rather than reverted so that a future conflict has a defined, documented outcome instead of an undefined one. See `design.md` §2.1.

## Requirement 3: The backend gate matches the deployed runtime

**User Story.** As a maintainer, I want the suite to run on the same Python version the Lambda functions use, so that a version-specific failure is caught in CI instead of after deploy.

### Acceptance Criteria

3.1. THE backend gate SHALL run on the Python version declared as the Lambda runtime in `template.yaml`.

3.2. THE backend gate SHALL install the test dependency manifest and then execute `pytest` over `tests/`.

3.3. THE backend gate SHALL execute the suite from the repository root, so that the `sys.path` roots established by `conftest.py` resolve as the tests expect.

3.4. IF the declared Lambda runtime in `template.yaml` changes THEN the version used by the backend gate SHALL be updated in the same pull request.

## Requirement 4: The frontend gate runs the toolchain the frontend requires

**User Story.** As a contributor changing the frontend, I want lint, tests, type-checking and the locale parity check all enforced automatically, so that a broken catalog or a type error cannot reach the default branch.

### Acceptance Criteria

4.1. THE frontend gate SHALL run on a Node version that satisfies every tool the frontend scripts invoke, including the TypeScript-stripping runtime flag used by `check:locales`.

4.2. THE frontend gate SHALL install dependencies from the committed lockfile without resolving new versions.

4.3. THE frontend gate SHALL run the `lint`, `test` and `build` scripts declared in `frontend/package.json`.

4.4. THE frontend gate SHALL rely on `build` to invoke `check:locales`, rather than invoking the locale check as a separate step.

4.5. IF the catalogs `en.json` and `pt-BR.json` diverge in key set, sort order, or contain an empty value THEN the frontend gate SHALL fail.

4.6. THE frontend gate SHALL supply placeholder values for the Cognito pool and client identifiers the application reads at module load, so that test files importing the auth provider can be collected.

> **Amended after validation.** 4.3 is currently unsatisfiable through no fault of the workflow: the `test` script is `NODE_OPTIONS=--no-webstorage vitest --run`, and `--no-webstorage` exists in no Node release, so the script exits 9 on every version. The workflow still invokes it, so the defect is visible rather than hidden; fixing `package.json` is out of scope here. 4.6 was added because three test files fail to import without it. See `design.md` §3.3, §3.4 and §5.

## Requirement 5: The workflow holds no privilege and no credential

**User Story.** As a maintainer of an `aws-samples` repository, I want the CI workflow to be incapable of writing to the repository or reaching an AWS account, so that it cannot be turned into an escalation path by a pull request from a fork.

### Acceptance Criteria

5.1. THE workflow SHALL request read access to repository contents and no other permission.

5.2. THE workflow SHALL NOT create, approve, comment on, or label a pull request or an issue.

5.3. THE workflow SHALL NOT reference any repository secret and SHALL NOT configure a real AWS credential. IF the suite requires AWS environment variables to construct a client THEN the workflow SHALL supply literal placeholder values in plain text.

5.4. THE suite SHALL reach no real AWS endpoint and no network host under CI.

5.5. THE workflow SHALL NOT execute any code from a pull request in a context that has write access to the repository.

> **Amended after validation.** 5.4 originally asserted the suite was hermetic in the sense of self-contained. It is not: `botocore` resolves a region and a credential pair at client construction, before `moto` intercepts, and a runner has no `~/.aws/config`. Without placeholders 35 tests fail with `NoRegionError`. The suite is *offline* but not *self-contained*, and one test is not even offline-safe — see `design.md` §3.2 and §5.

## Requirement 6: The local gates are documented

**User Story.** As a first-time contributor, I want the repository to tell me which commands to run before opening a pull request, so that CI confirms my change rather than discovering it.

### Acceptance Criteria

6.1. `CONTRIBUTING.md` SHALL document the command that installs the test dependency manifest.

6.2. `CONTRIBUTING.md` SHALL document the local backend gate and the local frontend gate as the pre-pull-request checks.

6.3. THE commands documented for local use SHALL be the same commands the workflow runs, allowing only a difference in output verbosity.

6.4. `docs/changelog.md` SHALL record this change under `## Unreleased`.

## Out of scope

- Writing new tests for behaviour this spec does not change. The only tests added are the regression guard for the injected clock and the tab-activation helper the existing locale tests needed.
- Aligning the `boto3` pin across the three deploy manifests, which would let the dev manifest return to pure composition (`design.md` §2.1).
- Marking the two checks as required in branch protection. That is a repository-settings action performed by a maintainer, subject to organization policy, and cannot be expressed in a workflow file.
- Promoting `react-hooks/set-state-in-effect` and `react-refresh/only-export-components` back to `error`. Both are `warn` for the reasons recorded in `eslint.config.js` and `design.md` §5.1; each needs its own change.
- Coverage measurement, coverage thresholds, and any reporting service.
- Deployment, packaging, and release automation, all of which the existing `release.yml` and `publish-release.yml` workflows already own.
- Dependency-update automation and vulnerability scanning.

> **Amended after validation.** This list originally excluded fixing the pre-existing defects that the gates revealed, and stated that CI would land red as a result. They were fixed in this branch instead — leaving a repository permanently red would have made the gate worthless as a signal, and marking the checks required would then have blocked every pull request. `design.md` §5 records each root cause and fix.
