# Implementation Plan: Git Repo Edit and Token Rotation

## Overview

Fullstack implementation of issue #13: `PATCH /api/git/repos/{repoId}` on the backend (partial metadata update + in-place token rotation via the existing `ssmTokenPath`), plus an edit mode on `GitRepoForm` and an edit action on the repos table.

## Tasks

- [x] 1. Backend — repository layer
  - [x] 1.1 Add `update_repo_config_fields(repo_id, fields)` to `layers/shared/git_shared/git_repository.py`
    - Targeted `UpdateExpression` with attribute-name aliases (reserved words)
    - _Requirements: 1.1_
  - [x]* 1.2 Add repository-layer tests in `tests/test_git_repository.py`
    - Updates only provided fields; other attributes untouched
    - _Requirements: 1.1_

- [x] 2. Backend — PATCH handler
  - [x] 2.1 Add `handle_update_repo(repo_id, body, claims, dynamodb_resource=None, ssm_client=None)` to `backend/handlers/git_repo_handler.py`
    - 404 on unknown repo; 400 on empty/no-op body; reuse `_validate_url`, `SUPPORTED_PROVIDERS`, 10–500 token bound
    - SSM `put_parameter(Overwrite=True)` at the existing `ssmTokenPath` when `accessToken` present, BEFORE the DDB update
    - Response in `handle_list_repos` item shape (`tokenConfigured`, never the token or `ssmTokenPath`); log field names only
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 2.2 Add the PATCH dispatcher branch in `backend/handler.py`
    - `_GIT_REPO_DETAIL_PATTERN` match, `_is_admin` gate, `_status_code` convention
    - _Requirements: 1.7_
  - [x]* 2.3 Write handler tests in `tests/test_git_repo_handler.py`
    - **Property 1: Identity stability** — repoId/createdAt/createdBy/ssmTokenPath unchanged after PATCH
    - **Property 2: Partiality** — absent fields retain values; token changes iff accessToken present (verify via SSM `get_parameter`)
    - **Property 3: Secret hygiene** — token in no response and no log output
    - Example cases: 404, empty body, invalid url/provider/token, SSM failure aborts metadata, dispatcher routing + 403
    - **Validates: Requirements 1.1–1.7, 2.1–2.5**

- [x] 3. Checkpoint — Backend verification
  - Run `pytest tests/test_git_repo_handler.py tests/test_git_repository.py`
  - Run the backend english-only guard (`tests/test_backend_english_only.py`)
  - Ask the user if there are any questions

- [x] 4. Frontend — API client
  - [x] 4.1 Add `patch<T>(path, body)` to `frontend/src/api/client.ts` and `updateGitRepo(repoId, patch)` + `GitRepoPatch` type to `frontend/src/api/gitApi.ts`
    - _Requirements: 3.7_

- [x] 5. Frontend — form edit mode and table action
  - [x] 5.1 Add `editTarget` prop and edit mode to `frontend/src/components/GitRepoForm.tsx`
    - Prefill name/url/provider; token optional with edit description; mode-aware title/submit; validate() skips token in edit mode
    - _Requirements: 3.2, 3.3, 3.4, 3.6, 4.1_
  - [x] 5.2 Wire `repoEditTarget` state, edit icon button, and `handleUpdateRepo` in `frontend/src/pages/GitSettingsPage.tsx`
    - Blank token → patch without `accessToken`; success message + list refresh
    - _Requirements: 3.1, 3.2, 3.4, 3.5_
  - [x] 5.3 Add the 6 new i18n keys to `en.json` and `pt-BR.json`
    - `gitRepoForm.editTitle`, `gitRepoForm.error.update`, `gitRepoForm.field.token.editDescription`, `gitRepoForm.submitEdit`, `gitSettings.repos.action.edit`, `gitSettings.repos.success.updated`
    - _Requirements: 4.1, 4.2_
  - [x]* 5.4 Update/add frontend tests
    - Edit prefill; blank-token submit omits `accessToken`; success refresh (GitRepoForm.test.tsx / GitSettingsPage.test.tsx conventions)
    - **Validates: Requirements 3.2, 3.4, 3.5**

- [x] 6. Checkpoint — Full verification and deploy
  - Frontend build (`npm run build`) and tests; locale parity check
  - Deploy backend (`make deploy-infra`, requires samconfig.toml) and frontend (`make deploy-frontend`)
  - Ask the user to validate: edit metadata, rotate token, blank-token edit keeps current token
  - _Requirements: all_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Backend deploy is required (new route + handler) — unlike frontend-only issues
- The repo has no committed `samconfig.toml`; one must be created locally for `make deploy-infra` (stack `kiro-cost-analyzer`, region `sa-east-1`)
