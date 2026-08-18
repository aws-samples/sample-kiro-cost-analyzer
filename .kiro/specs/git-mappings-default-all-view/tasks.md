# Implementation Plan: Default All-Mappings View

## Overview

Fullstack (issue #12): paginated `GET /api/git/mappings` on the backend, all-users view by default on the frontend with the user selector as optional filter.

## Tasks

- [x] 1. Backend
  - [x] 1.1 Add `list_all_mappings(limit, last_key)` to `layers/shared/git_shared/git_repository.py` (paginated scan, internal page loop)
    - _Requirements: 1.1, 1.2_
  - [x] 1.2 Add `handle_list_all_mappings(query_params)` to `backend/handlers/git_mapping_handler.py` (limit clamp, base64 token, 400 on malformed)
    - _Requirements: 1.1, 1.2, 1.5_
  - [x] 1.3 Add the `GET /api/git/mappings` dispatcher branch (admin-gated) in `backend/handler.py` and the `GitMappingsListAll` event in `template.yaml`
    - _Requirements: 1.1, 1.3, 1.4_
  - [x]* 1.4 Backend tests in `tests/test_git_mapping_handler.py`
    - **Property 1: Pagination completeness** / **Property 2: Filter equivalence** / **Property 3: Limit bound**
    - Examples: empty table, malformed lastKey 400, limit clamp
    - **Validates: Requirements 1.1–1.5**

- [x] 2. Frontend
  - [x] 2.1 Add `listAllGitMappings` to `frontend/src/api/gitApi.ts`
    - _Requirements: 1.1_
  - [x] 2.2 Rework `GitSettingsPage.tsx`: fetch-all on load, `mappingsLastKey` + Load more, Select as optional filter (clear → all view), delete refreshes active view
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 2.3 Add the 3 i18n keys (en + pt-BR)
    - _Requirements: 3.1_
  - [x]* 2.4 Frontend tests: default fetch on load, filter switch, load-more visibility
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

- [x] 3. Checkpoint — pytest + frontend build/tests + full deploy (`make deploy` — backend changed) + user validation

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Backend deploy required (new route) — full `make deploy`, not just frontend
