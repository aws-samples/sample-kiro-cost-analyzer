# Requirements Document

## Introduction

This feature reconciles the local `UserNamesTable` cache against IAM Identity Center on every ETL run, marking users that have been removed from IDC as "tombstoned" while preserving their historical name and userId. Read paths that surface actionable lists (tier optimization recommendations and inactive-subscriber detection) hide tombstoned users. The historical Users tab continues to show them, badged with "Removed from IDC" so admins can correlate past costs with the deletion event.

The motivating scenario: an admin removed two test users from Identity Center but left ~50 days of historical activity in the Analytics_Table. Those users continued to surface in the Recommendations tab and in the Inactive Subscribers list, polluting both with rows for accounts that no longer exist. There was no way to distinguish "user inactive" from "user no longer exists", and no place where the missing-from-IDC signal lived.

## Glossary

- **ETL_Pipeline**: The Step Functions state machine that processes Kiro usage data on a schedule.
- **Reconcile_Users_Step**: A new state at the tail of the ETL state machine that compares the live IDC user set with the `UserNamesTable` cache and updates per-user status flags.
- **UserNamesTable**: The DynamoDB table caching `userId → (displayName, userName)` mappings, populated by the `name_resolver`.
- **Identity_Center**: AWS IAM Identity Center, the source of truth for which users actually exist.
- **Tombstone**: A logical marker (`status: "TOMBSTONED"`) on a `UserNamesTable` row indicating the user no longer exists in IDC. The row itself is preserved so historical analytics keep their human-readable names.
- **Active_User**: A user whose `UserNamesTable` row has `status: "ACTIVE"` (or no `status` field — the default).
- **Recommendations_View**: The admin Recommendations tab, listing actionable tier optimization recommendations and inactive subscribers.
- **Users_View**: The admin Users tab, listing every user that has ever generated activity (historical view).

---

## Requirements

### Requirement 1: ETL reconciles UserNamesTable against IDC

**User Story:** As a product owner, I want the ETL to detect users removed from Identity Center on each run, so that downstream views can hide accounts that no longer exist.

#### Acceptance Criteria

1. WHEN the ETL_Pipeline finishes its data ingestion phase, THE ETL_Pipeline SHALL invoke the Reconcile_Users_Step before terminating.
2. THE Reconcile_Users_Step SHALL list every user currently present in Identity_Center via `identitystore:ListUsers` with full pagination.
3. THE Reconcile_Users_Step SHALL scan every item in the UserNamesTable.
4. WHEN a UserNamesTable row's `userId` is present in the IDC user set AND the row's `status` is missing or `"ACTIVE"`, THE Reconcile_Users_Step SHALL update the row's `lastSeenInIdc` field to the current ISO date (no other field changes).
5. WHEN a UserNamesTable row's `userId` is present in the IDC user set AND the row's `status` is `"TOMBSTONED"`, THE Reconcile_Users_Step SHALL restore the row by setting `status` to `"ACTIVE"`, clearing `tombstonedAt`, and updating `lastSeenInIdc`.
6. WHEN a UserNamesTable row's `userId` is absent from the IDC user set AND the row's `status` is missing or `"ACTIVE"`, THE Reconcile_Users_Step SHALL mark the row as tombstoned by setting `status` to `"TOMBSTONED"` and `tombstonedAt` to the current ISO date.
7. WHEN a UserNamesTable row's `userId` is absent from the IDC user set AND the row's `status` is already `"TOMBSTONED"`, THE Reconcile_Users_Step SHALL leave the row unchanged.
8. THE Reconcile_Users_Step SHALL never delete a UserNamesTable row — historical name lookups for old PROMPT# and STATS#DAILY# items must continue to work.

### Requirement 2: Fail-safe behavior on IDC errors

**User Story:** As an admin, I want the reconcile step to fail closed and never falsely tombstone users, so that a transient IDC permission or throttling error never produces a wave of incorrect "Removed from IDC" badges.

#### Acceptance Criteria

1. IF `identitystore:ListUsers` raises an exception (any boto3 ClientError, throttling, network error, or auth failure), THEN THE Reconcile_Users_Step SHALL log the error with structured fields and return without modifying any UserNamesTable row.
2. IF the IDC user list is empty (zero users returned without an error), THEN THE Reconcile_Users_Step SHALL log the result and return without modifying any UserNamesTable row. An empty IDC tenant is far more likely to indicate a misconfigured query than every user being deleted simultaneously.
3. IF `identitystore:ListUsers` succeeds but a single UpdateItem call against the UserNamesTable fails, THEN THE Reconcile_Users_Step SHALL log the per-row failure and continue processing the remaining rows.
4. THE Reconcile_Users_Step SHALL not fail the parent state machine on its own errors — it runs with `Catch: ["States.ALL"]` swallowed to a terminal success state, so reconcile failures never block the pipeline.

### Requirement 3: New users are not eagerly inserted

**User Story:** As an engineer, I want the reconcile step to never write rows for users that have not generated activity, so that the UserNamesTable does not balloon with idle IDC accounts.

#### Acceptance Criteria

1. WHEN a `userId` is present in the IDC user set AND absent from the UserNamesTable, THE Reconcile_Users_Step SHALL NOT insert a new row. The existing `name_resolver` (invoked during parse) handles cache population; reconcile only updates rows that already exist.

### Requirement 4: Read paths filter tombstoned users on actionable views

**User Story:** As an admin viewing recommendations, I want users that no longer exist in IDC to disappear from actionable lists, so that I do not waste time considering tier changes for accounts I have already deleted.

#### Acceptance Criteria

1. WHEN the backend serves `GET /api/recommendations/tier-optimization`, THE Backend SHALL exclude any user whose UserNamesTable row has `status: "TOMBSTONED"` from both the `recommendations` array and the `inactiveSubscribers` array.
2. WHEN the backend serves `GET /api/usage` (the dashboard Users tab), THE Backend SHALL include every user that has stats — including tombstoned users — and SHALL include a `tombstoned: boolean` field on each user payload so the frontend can render the badge.
3. THE Backend SHALL treat a missing `status` field on a UserNamesTable row as `"ACTIVE"` for backward compatibility with rows written before this feature.

### Requirement 5: Frontend surfaces tombstone status in the historical view

**User Story:** As an admin reviewing the Users tab, I want a visible badge and tooltip on tombstoned users, so that I understand why their costs are visible but they are not in any actionable recommendation list.

#### Acceptance Criteria

1. WHEN the Users tab renders a user with `tombstoned: true`, THE Frontend SHALL display a Cloudscape `Badge` next to the display name with the label "Removed from IDC".
2. WHEN the user hovers over the "Removed from IDC" badge, THE Frontend SHALL show a tooltip explaining that the user no longer exists in Identity Center as of the most recent ETL run, and that their historical activity is preserved for cost attribution.
3. THE Frontend SHALL render the tombstone badge in both the `en` and `pt-BR` locales, using translation keys under `users.tombstone.*`.

---

## Correctness Properties

- **P1 Reconcile is idempotent**: running the Reconcile_Users_Step twice in a row with no IDC changes between runs SHALL leave the UserNamesTable byte-identical (modulo `lastSeenInIdc` timestamp).
- **P2 No false tombstones on IDC errors**: for any failure mode of `identitystore:ListUsers`, the count of rows whose `status` flips to `"TOMBSTONED"` during the run SHALL be exactly zero.
- **P3 Tombstone preserves history**: a row's `userId`, `displayName`, and `userName` SHALL be unchanged by tombstoning. Only `status`, `tombstonedAt`, and `lastSeenInIdc` are mutated.
- **P4 Restore is symmetric**: tombstoning a row and then restoring it produces a row equivalent to the pre-tombstone state, except for `lastSeenInIdc` (always updated) and the tombstone metadata (`status` back to `"ACTIVE"`, `tombstonedAt` cleared).
