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

2.2. THE manifest SHALL obtain runtime dependencies by reference to the existing deploy manifests rather than by restating their contents, so that a version bump in a deploy manifest cannot silently diverge from what CI installs.

2.3. THE manifest SHALL reference every deploy manifest whose packages `tests/` imports, including the agent's.

2.4. THE manifest SHALL pin an exact version for each test-only dependency.

2.5. WHEN the manifest is installed into an empty virtual environment on a fresh clone THEN the backend gate SHALL pass with no further manual step.

2.6. THE manifest SHALL NOT be the place where any Lambda runtime dependency is first introduced; each of those remains owned by its deploy manifest.

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

## Requirement 5: The workflow holds no privilege and no credential

**User Story.** As a maintainer of an `aws-samples` repository, I want the CI workflow to be incapable of writing to the repository or reaching an AWS account, so that it cannot be turned into an escalation path by a pull request from a fork.

### Acceptance Criteria

5.1. THE workflow SHALL request read access to repository contents and no other permission.

5.2. THE workflow SHALL NOT create, approve, comment on, or label a pull request or an issue.

5.3. THE workflow SHALL NOT reference any repository secret and SHALL NOT configure AWS credentials.

5.4. THE suite SHALL remain hermetic under CI, reaching no real AWS endpoint.

5.5. THE workflow SHALL NOT execute any code from a pull request in a context that has write access to the repository.

## Requirement 6: The local gates are documented

**User Story.** As a first-time contributor, I want the repository to tell me which commands to run before opening a pull request, so that CI confirms my change rather than discovering it.

### Acceptance Criteria

6.1. `CONTRIBUTING.md` SHALL document the command that installs the test dependency manifest.

6.2. `CONTRIBUTING.md` SHALL document the local backend gate and the local frontend gate as the pre-pull-request checks.

6.3. THE commands documented for local use SHALL be the same commands the workflow runs, allowing only a difference in output verbosity.

6.4. `docs/changelog.md` SHALL record this change under `## Unreleased`.

## Out of scope

- Writing new tests or modifying existing ones. This spec only executes what the repository already contains.
- Marking the two checks as required in branch protection. That is a repository-settings action performed by a maintainer, subject to organization policy, and cannot be expressed in a workflow file.
- Coverage measurement, coverage thresholds, and any reporting service.
- Deployment, packaging, and release automation, all of which the existing `release.yml` and `publish-release.yml` workflows already own.
- Dependency-update automation and vulnerability scanning.
