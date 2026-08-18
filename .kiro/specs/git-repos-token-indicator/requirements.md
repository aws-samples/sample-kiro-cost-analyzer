# Requirements Document — Token Configured Indicator on Repos Table

## Introduction

This document specifies issue #14 (part of the Git settings usability pass #9): surface the existing `tokenConfigured` flag as a per-row status indicator on the repositories table in `GitSettingsPage`. The backend already returns the field (`handle_list_repos` / `handle_create_repo` / `handle_update_repo`) and the `GitRepository` TypeScript type already declares it — this is a frontend-only change. Today the access token is write-only with no feedback on whether one is stored.

## Glossary

- **Repos Table**: The repositories table on `frontend/src/pages/GitSettingsPage.tsx`.
- **Token Status**: Whether a repository has an access token stored (the boolean `tokenConfigured` from the list API).
- **StatusIndicator**: Cloudscape component used across the app for status rendering (`UsersPage`, `SettingsPage` patterns).

## Requirements

### Requirement 1: Token status column

**User Story:** As an administrator, I want to see at a glance which repositories have an access token configured, so that I can spot missing or unconfigured integrations without opening the edit form.

#### Acceptance Criteria

1. THE Repos Table SHALL display a token status column rendering a `StatusIndicator` per row, driven exclusively by the existing `tokenConfigured` field (no new API call).
2. WHEN `tokenConfigured` is true, THE indicator SHALL use the `success` type with a "Token configured" label.
3. WHEN `tokenConfigured` is false, THE indicator SHALL use the `warning` type with a "No token" label.

### Requirement 2: Internationalization

**User Story:** As a user of any supported locale, I want the token status in my language.

#### Acceptance Criteria

1. THE column header and both indicator labels SHALL resolve via `t()` with new keys in `en.json` and `pt-BR.json` with full parity.
