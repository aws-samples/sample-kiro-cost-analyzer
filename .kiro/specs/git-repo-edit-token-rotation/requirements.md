# Requirements Document — Git Repo Edit and Token Rotation

## Introduction

This document specifies the requirements for issue #13: allow editing a Git repository's metadata (name, url, provider) and rotating its access token in place, without the current delete-and-recreate workaround that changes `repoId` and drops `createdAt`/history. This requires a new backend endpoint (`PATCH /api/git/repos/{repoId}`) — the handler currently exposes only create, list, and delete — plus an edit mode on the existing `GitRepoForm` and an edit action on the repos table.

## Glossary

- **Repository Config**: The DynamoDB item `PK=GITREPO#{repoId}, SK=CONFIG` holding `name`, `url`, `provider`, `ssmTokenPath`, `status`, `createdAt`, `createdBy`.
- **Token Rotation**: Overwriting the SSM SecureString at the repository's existing `ssmTokenPath` with a new token value, keeping `repoId` and `ssmTokenPath` stable.
- **Patch Body**: A JSON object with any subset of `{ name, url, provider, accessToken }`.
- **Edit Mode**: `GitRepoForm` rendered with an existing repository prefilled (name/url/provider) and an optional token field.

## Requirements

### Requirement 1: PATCH endpoint updates metadata in place

**User Story:** As an administrator, I want to correct a repository's name, url, or provider via the API, so that a typo fix does not destroy the repository's identity and history.

#### Acceptance Criteria

1. WHEN a PATCH request is received at `/api/git/repos/{repoId}` with a valid Patch Body, THE backend SHALL update only the provided fields on the Repository Config, leaving `repoId`, `createdAt`, `createdBy`, and `ssmTokenPath` unchanged.
2. IF the target `repoId` does not exist, THEN THE backend SHALL return 404 with the `NotFound` error shape.
3. WHEN `url` is provided, THE backend SHALL validate it with the existing `_validate_url` rule and return 400 `ValidationError` on failure.
4. WHEN `provider` is provided, THE backend SHALL validate it against `SUPPORTED_PROVIDERS` and return 400 `ValidationError` on failure.
5. IF the Patch Body is empty or contains none of the allowed fields, THEN THE backend SHALL return 400 `ValidationError`.
6. THE PATCH response SHALL use the same field shape as `handle_list_repos` items (including `tokenConfigured`), and SHALL never include the token value or `ssmTokenPath`.
7. THE PATCH route SHALL be admin-gated exactly like the existing git repo routes (403 for non-admins).

### Requirement 2: Token rotation in place

**User Story:** As an administrator, I want to rotate a repository's access token by submitting a new one, so that a leaked token can be replaced without recreating the repository.

#### Acceptance Criteria

1. WHEN `accessToken` is present in the Patch Body, THE backend SHALL overwrite the SSM SecureString at the existing `ssmTokenPath` (using `Overwrite=True`), keeping the same parameter path.
2. WHEN `accessToken` is present, THE backend SHALL validate it with the existing 10–500 character bound and return 400 `ValidationError` on failure.
3. WHEN `accessToken` is absent from the Patch Body, THE backend SHALL NOT touch the stored token.
4. THE backend SHALL never write the token value to logs (log `repoId` and field names only).
5. IF the SSM write fails, THEN THE backend SHALL return 500 without persisting any metadata changes from the same request.

### Requirement 3: Edit mode on the repository form

**User Story:** As an administrator, I want an Edit action on the repositories table that opens the form prefilled, so that I can fix metadata or rotate the token from the UI.

#### Acceptance Criteria

1. THE repositories table actions column SHALL offer an edit icon button alongside the existing remove button.
2. WHEN the edit button is clicked, THE GitSettingsPage SHALL open `GitRepoForm` in Edit Mode with `name`, `url`, and `provider` prefilled from the target repository.
3. THE Edit Mode token field SHALL be optional, with a description indicating that leaving it blank keeps the current token.
4. WHEN the Edit Mode form is submitted with a blank token, THE frontend SHALL send a Patch Body without `accessToken`.
5. WHEN the Edit Mode form is submitted successfully, THE GitSettingsPage SHALL refresh the repositories list and show a success message.
6. THE Edit Mode SHALL reuse the existing per-field validation, except that the token is not required.
7. THE frontend SHALL expose `updateGitRepo(repoId, patch)` in `gitApi.ts` calling the PATCH endpoint.

### Requirement 4: Internationalization

**User Story:** As a user of any supported locale, I want the edit UI in my language, so that the workflow is clear.

#### Acceptance Criteria

1. THE Edit Mode strings (title, submit, token description, edit action label, success message, error message) SHALL resolve via `t()` with new keys in the existing `gitRepoForm.*` and `gitSettings.repos.*` namespaces.
2. THE new keys SHALL exist in `en.json` and `pt-BR.json` with full parity.
