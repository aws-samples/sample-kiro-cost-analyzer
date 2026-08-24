# Tasks — Git Token Permission Validation

Implementation plan. Each checkpoint leaves the tree deployable. Optional tasks marked `*`.

Requirements referenced per task as `_Requirements: N.M_`.

---

## Checkpoint 1 — Validation engine (backend, no routing yet)

- [ ] **1.1** Create `backend/handlers/git_token_validation_handler.py` with the module docstring, try/except imports for `git_shared.git_url_parser.parse_repo_url`, `git_shared.git_providers.SUPPORTED_PROVIDERS` / `SSM_TOKEN_PATH_PREFIX`, `git_shared.git_repository.GitRepository`, and `shared.structured_logger.StructuredLogger` — following the fallback-import convention in steering §4.1.
  - _Requirements: 2.1_

- [ ] **1.2** Define the check constants (`CHECK_REPO_ACCESS`, `CHECK_COMMITS`, `CHECK_PULL_REQUESTS`, `CHECK_ORDER`), the `REQUIRED_PERMISSION` map, `GITHUB_API_BASE = "https://api.github.com"`, `_GITLAB_API_PATH = "/api/v4"`, and `_REQUEST_TIMEOUT_SECONDS = 10`.
  - _Requirements: 2.1, 4.1, 5.1_

- [ ] **1.3** Implement `_status_for(http_status) -> str` per the design's mapping table, and a private `_ValidationInputError` exception carrying a message for the 400 path.
  - _Requirements: 2.4_

- [ ] **1.4** Implement `_assert_public_https_host(base_url)` exactly as designed: https-only, hostname present, `socket.getaddrinfo` resolution, and rejection when any resolved address is loopback / link-local / private / reserved / unspecified / multicast. Raise `_ValidationInputError` on every rejection.
  - _Requirements: 5.2, 5.3, 5.4_

- [ ] **1.5** Implement `_build_check_requests(provider, location) -> list[tuple[check_id, url, params]]` producing the three GitHub or three GitLab targets. GitHub URLs are built against the `GITHUB_API_BASE` constant, never against the submitted host; GitLab project paths are `quote(project_path, safe="")`.
  - _Requirements: 2.1, 2.2, 5.1_

- [ ] **1.6** Implement `_run_checks(provider, location, token, requests_module=None)` — dependency-injected `requests` for testability per steering §4.1. For GitLab, call `_assert_public_https_host` first. Per check: GET with `allow_redirects=False`, `timeout=_REQUEST_TIMEOUT_SECONDS`, provider auth header (`Authorization: token {t}` + GitHub accept header; `PRIVATE-TOKEN: {t}` for GitLab). Map to a status slug; `requests.RequestException` → `unreachable` with `httpStatus: None`. Never read or log the response body.
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 5.5, 6.3_

- [ ] **1.7** Implement `_summarize(provider, checks) -> tuple[str, list[str]]` returning the `overall` verdict and the de-duplicated, `CHECK_ORDER`-preserving `requiredPermissions`.
  - _Requirements: 4.1_

- [ ] **1.8** Implement `handle_validate_token(body)` (ad-hoc): validate presence of `url`/`provider`/`accessToken`, provider membership in `SUPPORTED_PROVIDERS`, and `parse_repo_url` success — each failure returning `{"error": "ValidationError", "message": ..., "_status_code": 400}`. On success run the checks and return the response contract with `tokenMissing: False`.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 2.1_

- [ ] **1.9** Implement `handle_validate_stored_token(repo_id, dynamodb_resource=None, ssm_client=None)`: load the config via `GitRepository` (404 `NotFound` when absent), re-derive the location with `parse_repo_url` from the stored URL, read the SSM parameter with `WithDecryption=True`, and on an absent/empty parameter return `tokenMissing: True` with all three checks `unauthorized` / `httpStatus: None` and **no** outbound request.
  - _Requirements: 3.1, 3.2, 3.3, 3.5_

- [ ] **1.10** Add the structured audit log: one `logger.info` per validation carrying `provider`, `overall`, the per-check status slugs, and `repoId` on the stored path. Assert by inspection that no statement interpolates the token, and that exception handling logs only `type(exc).__name__`.
  - _Requirements: 6.1, 6.3, 6.4_

**Validation checkpoint 1**: module imports cleanly (`python -c "import backend.handlers.git_token_validation_handler"`), no route reachable yet, nothing deployed.

---

## Checkpoint 2 — Backend tests

- [ ] **2.1** Create `tests/test_git_token_validation_handler.py` with a fake `requests` module (a stub exposing `get`, a `RequestException` class, and a call recorder) injected through the handler's parameter — no monkeypatching of the real library, no network.
  - _Requirements: (test infrastructure)_

- [ ] **2.2** Check-table tests: assert the exact URL and params of all three checks for GitHub (against `api.github.com`) and for GitLab (against `https://gitlab.example.com`, project path percent-encoded). This is the regression guard against drifting away from the agent's provider tools.
  - _Requirements: 2.1, 2.2, 5.1_

- [ ] **2.3** The incident scenario: `repo_access` 200 / `commits` 403 / `pull_requests` 403 → `overall == "partial"`, `requiredPermissions == ["contents:read", "pull_requests:read"]`.
  - _Requirements: 2.3, 4.1_

- [ ] **2.4** All-200 → `overall == "ok"` and `requiredPermissions == []`; empty JSON list bodies on commits/pulls still `ok`.
  - _Requirements: 2.7_

- [ ] **2.5** Status-mapping tests for 401/403/404/429/500 and for `RequestException` → `unreachable` with `httpStatus is None`; and the all-fail case → `overall == "failed"`.
  - _Requirements: 2.4, 2.5_

- [ ] **2.6** GitLab de-duplication: a fully failing GitLab token yields exactly `["read_api"]`.
  - _Requirements: 4.1_

- [ ] **2.7** SSRF gate tests — `http://gitlab.example.com`, `https://127.0.0.1`, `https://169.254.169.254`, `https://10.0.0.5`, and an unresolvable host (patched `getaddrinfo` raising `gaierror`) each return `_status_code == 400` AND leave the fake requests recorder empty.
  - _Requirements: 5.2, 5.3, 5.4_

- [ ] **2.8** GitHub host pinning: a submitted `https://evil.example/o/r` produces calls whose URLs all start with `https://api.github.com/`.
  - _Requirements: 5.1_

- [ ] **2.9** Assert every recorded call passed `allow_redirects=False` and a numeric `timeout`.
  - _Requirements: 5.5_

- [ ] **2.10** Input-validation tests: each of missing/blank `url`, `provider`, `accessToken`; `provider="bitbucket"`; and an unparseable URL → 400 `ValidationError` with zero outbound calls.
  - _Requirements: 1.2, 1.3, 1.4_

- [ ] **2.11** Stored-path tests with `moto` for DynamoDB + SSM: unknown `repoId` → 404 `NotFound`; a stored repo with no SSM parameter → `tokenMissing is True`, three `unauthorized` checks, zero outbound calls; a stored repo with a parameter → checks run against the stored URL's coordinates.
  - _Requirements: 3.1, 3.2, 3.3_

- [ ] **2.12** Credential non-disclosure: run a validation with a sentinel token, then assert the sentinel appears in neither `json.dumps(response)` nor any record captured from the logging handler.
  - _Requirements: 6.1, 6.2_

- [ ] **2.13 \*** Hypothesis property tests (≥100 iterations, steering §7.2) for the design's properties 1–3: check totality, verdict determinism, and permission soundness over arbitrary status-code triples.
  - _Requirements: 2.1, 4.1_

**Validation checkpoint 2**: `python -m pytest tests/test_git_token_validation_handler.py -v` green.

---

## Checkpoint 3 — Routing and infrastructure

- [ ] **3.1** In `backend/handler.py`, add `_GIT_REPO_VALIDATE_TOKEN_PATH = "/api/git/repos/validate-token"` and `_GIT_REPO_VALIDATE_TOKEN_PATTERN = re.compile(r"^/api/git/repos/([^/]+)/validate-token$")` at module level, next to the existing git patterns.
  - _Requirements: 1.1, 3.1_

- [ ] **3.2** Add the ad-hoc dispatch block for `POST` on the literal path, gated by `_is_admin`, positioned **before** the `_GIT_REPO_DETAIL_PATTERN` block so `validate-token` is not parsed as a `repoId`.
  - _Requirements: 1.1, 1.5_

- [ ] **3.3** Add the stored dispatch block for `POST` matching `_GIT_REPO_VALIDATE_TOKEN_PATTERN`, gated by `_is_admin`, using the `_status_code` pop convention.
  - _Requirements: 3.1, 3.4_

- [ ] **3.4** In `template.yaml`, add two Events to `BackendFunction`: `GitRepoValidateToken` (`POST /api/git/repos/validate-token`) and `GitRepoValidateStoredToken` (`POST /api/git/repos/{repoId}/validate-token`). No IAM change is required — `SSMGitTokensAccess` and `KMSForGitTokens` already grant the decrypting read, and the function is not in a VPC so outbound HTTPS works as-is.
  - _Requirements: 1.1, 3.1_

- [ ] **3.5** Add routing tests to the existing backend handler test suite (or the new file): the literal path routes to the ad-hoc handler and not to the detail pattern; a non-admin caller gets 403 on both routes.
  - _Requirements: 1.5, 3.4_

**Validation checkpoint 3**: `sam validate` passes; full Python suite shows no new failures against the pre-existing baseline.

---

## Checkpoint 4 — Frontend

- [ ] **4.1** Add `GitTokenCheckId`, `GitTokenCheckStatus`, `GitTokenCheck`, and `GitTokenValidation` to the Git section of `frontend/src/types/index.ts`.
  - _Requirements: 7.1, 7.2_

- [ ] **4.2** Add `validateGitToken` and `validateStoredGitToken` to `frontend/src/api/gitApi.ts`.
  - _Requirements: 1.1, 3.1_

- [ ] **4.3** Create `frontend/src/components/GitTokenValidationModal.tsx`: `Alert` severity by verdict (`error` for `failed`, `warning` for `partial`), a per-check `StatusIndicator` list with translated labels, the `tokenMissing` variant rendered distinctly, and the remediation block showing GitHub fine-grained names **and** the classic `repo` scope, or GitLab's `read_api`. Permission names are rendered untranslated inside translated sentences.
  - _Requirements: 4.3, 4.4, 7.5_

- [ ] **4.4** Wire the button into `GitRepoForm.tsx` after the token `FormField`: disabled unless `url`, `provider`, and `accessToken` are all non-empty; `loading` while in flight and non-re-entrant; inline `StatusIndicator type="success"` on `ok`, modal otherwise.
  - _Requirements: 7.1, 7.3, 7.4, 7.5_

- [ ] **4.5** Wire the per-row action into `GitSettingsPage.tsx`'s actions cell, with `validatingRepoId` / `validationResult` state and the modal rendered once at page level.
  - _Requirements: 7.2, 7.3, 7.4, 7.5_

- [ ] **4.6** Add the parallel `en.json` / `pt-BR.json` keys at their correct alphabetical positions: check labels (`repo_access`, `commits`, `pull_requests`), status labels (all seven slugs), verdict headings, the remediation sentences per provider and token type, the `tokenMissing` message, the button label, and error fallbacks.
  - _Requirements: 7.6_

- [ ] **4.7** Create `frontend/src/components/__tests__/GitTokenValidationModal.test.tsx`: alert severity per verdict, each check row rendered with its status, GitHub failure shows both token-type remediations, GitLab failure shows `read_api`, and `tokenMissing` renders its own message.
  - _Requirements: 4.3, 4.4, 7.5_

**Validation checkpoint 4**: `npm run build` passes (which runs `check-locales.ts`, proving key parity and sorting) and `npm run test` is green.

---

## Checkpoint 5 — Deploy and live verification

- [ ] **5.1** `make deploy` (per the project rule: always through the Makefile).
  - _Requirements: (deployment)_

- [ ] **5.2** Live-verify the incident case is now self-diagnosing: temporarily point a repository at a token lacking `contents:read`, run the row action, and confirm the modal names Contents as the missing permission. Restore the good token afterwards.
  - _Requirements: 2.3, 4.3_

- [ ] **5.3** Live-verify the happy path against `vsbatista/agentic-city` with its now-corrected token: three green checks, `overall: ok`, no modal.
  - _Requirements: 7.4_

- [ ] **5.4** Live-verify the GitLab path against the registered `dlt-v2` repository.
  - _Requirements: 2.1_

- [ ] **5.5** Confirm in CloudWatch that the validation audit log carries the verdict and check slugs and that the token literal is absent.
  - _Requirements: 6.1, 6.4_

---

## Checkpoint 6 — Documentation

- [ ] **6.1** Add a `docs/changelog.md` entry under `Unreleased` describing the feature and the incident it addresses.
  - _Requirements: (documentation, steering §8.4)_

- [ ] **6.2** Add a short note to `agent/app/GitCorrelationAgent/tools/github_tool.py` and `gitlab_tool.py` module docstrings stating that the operation set is mirrored by the check table in `git_token_validation_handler.py`, so a future addition there is reflected here. This is the mitigation for the coupling flagged in design.md.
  - _Requirements: (maintainability)_

---

## Task → Requirement traceability matrix

| Task | Requirements |
|---|---|
| 1.1 | 2.1 |
| 1.2 | 2.1, 4.1, 5.1 |
| 1.3 | 2.4 |
| 1.4 | 5.2, 5.3, 5.4 |
| 1.5 | 2.1, 2.2, 5.1 |
| 1.6 | 2.2–2.7, 5.5, 6.3 |
| 1.7 | 4.1 |
| 1.8 | 1.1–1.4, 1.6, 2.1 |
| 1.9 | 3.1, 3.2, 3.3, 3.5 |
| 1.10 | 6.1, 6.3, 6.4 |
| 2.2 | 2.1, 2.2, 5.1 |
| 2.3 | 2.3, 4.1 |
| 2.4 | 2.7 |
| 2.5 | 2.4, 2.5 |
| 2.6 | 4.1 |
| 2.7 | 5.2, 5.3, 5.4 |
| 2.8 | 5.1 |
| 2.9 | 5.5 |
| 2.10 | 1.2, 1.3, 1.4 |
| 2.11 | 3.1, 3.2, 3.3 |
| 2.12 | 6.1, 6.2 |
| 2.13 \* | 2.1, 4.1 |
| 3.1 | 1.1, 3.1 |
| 3.2 | 1.1, 1.5 |
| 3.3 | 3.1, 3.4 |
| 3.4 | 1.1, 3.1 |
| 3.5 | 1.5, 3.4 |
| 4.1 | 7.1, 7.2 |
| 4.2 | 1.1, 3.1 |
| 4.3 | 4.3, 4.4, 7.5 |
| 4.4 | 7.1, 7.3, 7.4, 7.5 |
| 4.5 | 7.2, 7.3, 7.4, 7.5 |
| 4.6 | 7.6 |
| 4.7 | 4.3, 4.4, 7.5 |
| 5.2 | 2.3, 4.3 |
| 5.3 | 7.4 |
| 5.4 | 2.1 |
| 5.5 | 6.1, 6.4 |

Requirement 1.5 (admin gate) is enforced by tasks 3.2 and 3.3 and verified by 3.5. Requirement 4.2 (no prose in the backend payload) is enforced by omission — no task adds a human-readable field to the response — and is observable in the contract in design.md.
