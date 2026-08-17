# Requirements Document — Git Settings Delete Confirmation Modal

## Introduction

This document specifies the requirements for adding confirmation modals before deleting Git repositories and user-Git mappings on the Git settings page (`GitSettingsPage`). Today, `handleDeleteRepo` and `handleDeleteMapping` fire immediately from an icon button with no confirmation — an accidental click silently removes a configured integration with no undo. The change mirrors the delete confirmation modal pattern already used in `UsersPage` (issue #11, part of the usability pass #9). Frontend-only scope: the delete endpoints already exist.

## Glossary

- **GitSettingsPage**: Git settings page (`frontend/src/pages/GitSettingsPage.tsx`) containing the repositories and mappings tables.
- **Repository**: A configured Git repository record, identified by `repoId`, with `name` and `url`.
- **Mapping**: An association between a Kiro user (`userId`) and a Git identity (`gitUsername` + `provider`).
- **Confirmation Modal**: Cloudscape `<Modal>` with a warning `Alert`, the target identified in bold, and Cancel/Confirm buttons, following the `UsersPage` pattern.
- **Delete Target**: React state (`repoDeleteTarget` / `mappingDeleteTarget`) holding the item pending confirmation; `null` means no modal is open.

## Requirements

### Requirement 1: Confirmation before deleting a repository

**User Story:** As an administrator, I want to confirm the deletion of a Git repository in a modal that identifies the repository, so that an accidental click does not remove a configured integration.

#### Acceptance Criteria

1. WHEN the user clicks the remove icon of a repository, THE GitSettingsPage SHALL open a confirmation modal without executing any delete call.
2. THE repository Confirmation Modal SHALL display the target repository's `name` and `url` in bold.
3. WHEN the user clicks the modal's confirm button, THE GitSettingsPage SHALL call `deleteGitRepo(repoId)` with the target's `repoId` and, on success, refresh the repositories list and close the modal.
4. WHEN the user cancels or dismisses the modal, THE GitSettingsPage SHALL close the modal with no side effect (no API call).
5. IF the delete call fails, THEN THE GitSettingsPage SHALL display the existing error message (`gitSettings.repos.error.delete`) and close the modal.

### Requirement 2: Confirmation before deleting a mapping

**User Story:** As an administrator, I want to confirm the deletion of a user-Git mapping in a modal that identifies the mapping, so that an accidental click does not undo a configured association.

#### Acceptance Criteria

1. WHEN the user clicks the remove icon of a mapping, THE GitSettingsPage SHALL open a confirmation modal without executing any delete call.
2. THE mapping Confirmation Modal SHALL display the target mapping's `userId`, `gitUsername`, and `provider` in bold.
3. WHEN the user clicks the modal's confirm button, THE GitSettingsPage SHALL call `deleteGitMapping(userId, provider)` with the target's data and, on success, refresh the mappings list and close the modal.
4. WHEN the user cancels or dismisses the modal, THE GitSettingsPage SHALL close the modal with no side effect (no API call).
5. IF the delete call fails, THEN THE GitSettingsPage SHALL display the existing error message (`gitSettings.mappings.error.delete`) and close the modal.

### Requirement 3: Modal internationalization

**User Story:** As a user of any supported locale, I want the confirmation modals to appear in my language, so that the destructive action is understood without ambiguity.

#### Acceptance Criteria

1. THE Confirmation Modal SHALL resolve all texts via `t()` using the new keys `gitSettings.repos.deleteModal.*` and `gitSettings.mappings.deleteModal.*`.
2. THE cancel button SHALL reuse the existing `common.cancel` key.
3. THE new keys SHALL exist in `en.json` and `pt-BR.json` with full parity (identical key sets in both files).
4. WHEN the active locale changes, THE Confirmation Modal SHALL display the texts of the new locale.
