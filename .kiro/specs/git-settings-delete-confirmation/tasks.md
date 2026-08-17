# Implementation Plan: Git Settings Delete Confirmation Modal

## Overview

Frontend-only implementation of issue #11: add confirmation modals before deleting repositories and mappings on `GitSettingsPage`, mirroring the `UsersPage` pattern. The delete endpoints already exist; no backend changes.

## Tasks

- [x] 1. Add modal translation keys
  - [x] 1.1 Add the 8 `gitSettings.repos.deleteModal.*` and `gitSettings.mappings.deleteModal.*` keys to `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json`
    - Insert in alphabetical order inside the existing `gitSettings.mappings.*` and `gitSettings.repos.*` blocks
    - Texts per the design.md table (title, warning, confirm, submit)
    - Keep full parity between both locales
    - _Requirements: 3.1, 3.3_

- [x] 2. Implement repository delete confirmation modal
  - [x] 2.1 Add `repoDeleteTarget` and `deletingRepo` state to `frontend/src/pages/GitSettingsPage.tsx`
    - `const [repoDeleteTarget, setRepoDeleteTarget] = useState<GitRepository | null>(null)`
    - Repos table remove button now calls `setRepoDeleteTarget(item)` instead of `handleDeleteRepo`
    - _Requirements: 1.1_
  - [x] 2.2 Refactor `handleDeleteRepo` to operate on the state target
    - Read `repoDeleteTarget.repoId`, guard with `if (!repoDeleteTarget) return`
    - `setDeletingRepo(true/false)` around the call; `setRepoDeleteTarget(null)` in `finally`
    - Keep the existing error/success handling
    - _Requirements: 1.3, 1.5_
  - [x] 2.3 Add the repository `<Modal>` block to the JSX
    - Copy the Delete Confirmation Modal structure from `UsersPage` (warning Alert + target in bold + Cancel/Confirm footer)
    - Show target `name` in bold and `url`; `common.cancel` on the link button; `loading={deletingRepo}` on the primary
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.1, 3.2_

- [x] 3. Implement mapping delete confirmation modal
  - [x] 3.1 Add `mappingDeleteTarget` and `deletingMapping` state to `frontend/src/pages/GitSettingsPage.tsx`
    - Mappings table remove button now calls `setMappingDeleteTarget(item)`
    - _Requirements: 2.1_
  - [x] 3.2 Refactor `handleDeleteMapping` to operate on the state target
    - Read `userId`/`provider` from the target; clear the target in `finally`
    - _Requirements: 2.3, 2.5_
  - [x] 3.3 Add the mapping `<Modal>` block to the JSX
    - Show target `userId`, `gitUsername`, and `provider` in bold
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2_

- [x] 4. Update and write tests
  - [x] 4.1 Update the existing deletion tests in `GitSettingsPage.test.tsx`
    - Icon click now opens the modal; deletion only after primary button click
    - _Requirements: 1.1, 2.1_
  - [x]* 4.2 Write test for Property 1
    - **Property 1: No deletion without confirmation**
    - Clicking the icon then canceling/dismissing results in zero calls to `deleteGitRepo`/`deleteGitMapping`
    - **Validates: Requirements 1.1, 1.4, 2.1, 2.4**
  - [x]* 4.3 Write test for Property 2
    - **Property 2: Deletion confirms exactly the displayed target**
    - Confirming calls the API with the exact identifiers of the clicked row's item
    - **Validates: Requirements 1.3, 2.3**
  - [x]* 4.4 Write test for Property 3
    - **Property 3: Modal identifies the target**
    - Modal body contains name+url (repo) or userId+gitUsername+provider (mapping)
    - **Validates: Requirements 1.2, 2.2**

- [x] 5. Checkpoint — Verify build, tests, and locale parity
  - Ensure the build compiles without errors (`tsc -b && vite build` via make)
  - Ensure all tests pass (`npm test`)
  - Ensure key parity between `en.json` and `pt-BR.json` (`npm run check:locales`)
  - Ask the user if there are any questions

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- No backend changes — delete endpoints already exist (issue #11, out of scope)
