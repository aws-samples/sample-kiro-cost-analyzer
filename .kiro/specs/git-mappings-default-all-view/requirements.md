# Requirements Document — Default All-Mappings View

## Introduction

This document specifies issue #12 (part of the Git settings usability pass #9): the mappings table on `GitSettingsPage` currently shows nothing until an administrator picks a user, because the only listing endpoint is per-user (`GET /api/git/mappings/{userId}`). This change adds a paginated "list all mappings" backend endpoint and makes the all-users view the page default, demoting the user selector from prerequisite to optional filter.

## Glossary

- **Mapping**: A user-Git association item (`PK=USER#{userId}`, `SK=GITMAP#{provider}`) with `userId`, `provider`, `gitUsername`, `createdAt`.
- **All-Mappings Endpoint**: New `GET /api/git/mappings` (no userId) returning mappings across all users with cursor pagination.
- **Pagination Token**: Opaque token round-tripping DynamoDB's `LastEvaluatedKey` between responses and requests.
- **User Filter**: The existing user `Select` on the page, now optional.

## Requirements

### Requirement 1: List-all endpoint

**User Story:** As an administrator, I want an API that lists every user-Git mapping, so that the UI can show the full picture without requiring a user first.

#### Acceptance Criteria

1. THE backend SHALL expose `GET /api/git/mappings` returning mappings across all users.
2. THE endpoint SHALL support a `limit` query parameter (default 50, max 100) and cursor pagination via a `lastKey` token, returning the next token when more results exist.
3. THE endpoint SHALL be admin-gated exactly like the other git routes (403 for non-admins).
4. THE existing per-user route `GET /api/git/mappings/{userId}` SHALL remain unchanged.
5. IF the `lastKey` token is malformed, THEN THE endpoint SHALL return 400 `ValidationError`.

### Requirement 2: All-mappings view by default

**User Story:** As an administrator, I want to see all mappings when I open the page, so that reviewing the org's Git associations does not require guessing user by user.

#### Acceptance Criteria

1. WHEN the Git settings page loads, THE mappings table SHALL fetch and display the all-users view with no user pre-selected.
2. THE mappings table SHALL offer a "load more" affordance when the response carries a pagination token.
3. WHEN a user is selected in the User Filter, THE table SHALL switch to the existing per-user listing.
4. WHEN the User Filter is cleared, THE table SHALL return to the all-users view.
5. THE delete confirmation flow SHALL keep working in both views, refreshing the active view after a deletion.

### Requirement 3: Internationalization

**User Story:** As a user of any supported locale, I want the new UI texts in my language.

#### Acceptance Criteria

1. Any new UI strings (e.g. load-more button, all-users empty state) SHALL resolve via `t()` with keys present in `en.json` and `pt-BR.json` with full parity.
