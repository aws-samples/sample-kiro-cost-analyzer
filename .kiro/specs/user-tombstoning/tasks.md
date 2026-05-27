# Implementation Tasks — User Tombstoning

## Phase 1 — Pure logic + tests (no AWS)

- [x] **Task 1.1**: Implement `etl/user_reconciler.py` with `classify_row` and `build_update_kwargs` as pure functions. _Requirements: 1.4, 1.5, 1.6, 1.7, 1.8_
- [x] **Task 1.2**: Property-based tests in `tests/test_user_reconciler.py` covering idempotence (P1), history preservation (P3), and restore round-trip (P4). _Requirements: 1.4, 1.5, 1.6, 1.7, 1.8_

## Phase 2 — Lambda + state machine wiring

- [x] **Task 2.1**: `etl/reconcile_users_handler.py` orchestrates `ListUsers` (paginated) → scan UserNamesTable → classify rows → batch UpdateItem. _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3_
- [x] **Task 2.2**: `tests/test_reconcile_users_handler.py` integration tests with moto: happy path, IDC error, IDC empty, partial UpdateItem failure. _Requirements: 2.1, 2.2, 2.3, P2_
- [x] **Task 2.3**: SAM template — new `ReconcileUsersFunction` with the same IAM as `ParseFunction`. _Requirements: 1.1, 1.2_
- [x] **Task 2.4**: SAM template — extend the ETL state machine with the `ReconcileUsers` step (Catch all errors, terminate cleanly). _Requirement: 2.4_

## Phase 3 — Read paths

- [x] **Task 3.1**: `backend/repository/analytics_repository.py` — extend the UserNamesTable lookup to project `status` and `tombstonedAt`. Add `lookup_user_metadata` helper. _Requirement: 4.3_
- [x] **Task 3.2**: `backend/handlers/recommendation_handler.py` — exclude tombstoned users from both the windowed and lifetime user lists before invoking the engine. _Requirement: 4.1_
- [x] **Task 3.3**: `backend/handlers/usage_handler.py` and `backend/handlers/user_details_handler.py` — propagate `tombstoned: boolean` on each user payload. _Requirement: 4.2_
- [x] **Task 3.4**: `tests/test_recommendation_handler.py` — add cases verifying tombstoned users are excluded. _Requirements: 4.1, P2_
- [x] **Task 3.5**: `tests/test_usage_handler.py` — add a case verifying `tombstoned: boolean` is forwarded. _Requirement: 4.2_

## Phase 4 — Frontend

- [x] **Task 4.1**: `frontend/src/types/index.ts` — extend `UserUsage` with `tombstoned?: boolean`. _Requirement: 4.2_
- [x] **Task 4.2**: `frontend/src/components/UsageTable.tsx` — render the `Removed from IDC` badge with a Popover tooltip when `user.tombstoned === true`. _Requirements: 5.1, 5.2_
- [x] **Task 4.3**: `frontend/src/locales/{en,pt-BR}.json` — three new keys under `users.tombstone.*` (badge label, tooltip header, tooltip body). _Requirement: 5.3_

## Phase 5 — Documentation

- [x] **Task 5.1**: `docs/changelog.md` — `Unreleased` entry summarizing the feature. _Steering 8.4_
- [x] **Task 5.2**: This spec exists. _Steering 2.1_
