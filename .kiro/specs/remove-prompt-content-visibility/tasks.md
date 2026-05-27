# Implementation Plan: Remove Prompt Content Visibility

## Overview

This plan removes all prompt content visibility from the KCA application — the prompts table, detail panel, feedback workflow, and backend API endpoints — then reorganizes the distribution charts to use the freed space. The approach is: backend removal first (safe, no frontend depends on missing routes), then frontend component deletion, then layout reorganization, then type/translation cleanup, and finally verification.

## Tasks

- [x] 1. Remove backend prompts and feedback routes
  - [x] 1.1 Remove prompts and feedback route logic from `backend/handler.py`
    - Remove `prompts_handler` and `feedback_handler` imports
    - Remove `_PROMPTS_DETAIL_PATTERN`, `_FEEDBACK_SUBMIT_PATTERN`, `_FEEDBACK_REVIEW_PATTERN` regex patterns
    - Remove all route blocks for `/api/prompts`, `/api/prompts/{requestId}`, `/api/prompts/{requestId}/feedback`, `/api/feedback`, `/api/feedback/{feedbackId}/review`
    - The existing catch-all in `_route()` already returns 404 for unknown paths
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 3.4_

  - [x] 1.2 Delete `backend/handlers/prompts_handler.py`
    - Remove the file entirely — no longer called from any route
    - _Requirements: 5.1, 5.2, 5.4_

  - [x] 1.3 Delete `backend/handlers/feedback_handler.py`
    - Remove the file entirely — no longer called from any route
    - _Requirements: 3.4_

  - [ ]* 1.4 Update backend tests for removed endpoints
    - Update `tests/test_prompts_handler.py` — either delete or convert to 404 verification tests
    - Update `tests/test_feedback_handler.py` — either delete or convert to 404 verification tests
    - Add tests verifying `GET /api/prompts` returns 404, `GET /api/prompts/{id}` returns 404, `POST /api/prompts/{id}/feedback` returns 404, `GET /api/feedback` returns 404, `PUT /api/feedback/{id}/review` returns 404
    - Verify existing routes (usage, config, correlation) still work
    - _Requirements: 5.1, 5.2, 5.3, 3.4, 6.1_

- [x] 2. Checkpoint - Verify backend changes
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Remove frontend prompts components and state
  - [x] 3.1 Remove prompts-related code from `frontend/src/pages/UserPage.tsx`
    - Remove imports: `RecentPromptsTable`, `PromptDetailPanel`, `PromptsListResponse`
    - Remove state: `selectedPromptId`, `prompts`, `promptsLoading`, `currentPage`, `pageTokens`
    - Remove `handlePromptSelect` callback and split panel usage for prompts
    - Remove `fetchPrompts` function and its invocations in `useEffect` hooks
    - Remove `handlePageChange` callback
    - Remove `<RecentPromptsTable>` from the usage tab JSX
    - Keep `useSplitPanel` hook import only if still used elsewhere in the file; otherwise remove
    - Remove `selectedCategory` state and `onCategorySelect` prop from `DistributionCharts` (category selection was used to filter prompts table)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2_

  - [x] 3.2 Delete `frontend/src/components/RecentPromptsTable.tsx`
    - _Requirements: 2.4_

  - [x] 3.3 Delete `frontend/src/components/PromptDetailPanel.tsx`
    - _Requirements: 2.3_

  - [x] 3.4 Delete `frontend/src/components/FeedbackModal.tsx`
    - _Requirements: 3.1_

  - [x] 3.5 Remove `FeedbackAdminPage` from routing and navigation
    - Delete `frontend/src/pages/FeedbackAdminPage.tsx`
    - Remove any route for the feedback admin page from `App.tsx` (if present)
    - Remove any navigation link to the feedback admin page from `App.tsx` side navigation
    - _Requirements: 3.3, 3.5_

  - [x] 3.6 Remove `selectedCategory`/`onCategorySelect` props from `DistributionCharts`
    - Remove `selectedCategory` and `onCategorySelect` from the component's props interface
    - Remove `highlightedSegment` logic and `onHighlightChange` handler from the category pie chart
    - The category chart becomes view-only (no interactive selection)
    - _Requirements: 1.3_

- [x] 4. Reorganize distribution charts layout
  - [x] 4.1 Update `frontend/src/components/DistributionCharts.tsx` layout
    - Change from `Grid gridDefinition={[{ colspan: 4 }, { colspan: 4 }, { colspan: 4 }]}` to a 2-column + full-width layout
    - Use `SpaceBetween size="l"` wrapping a `Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}` for model + trigger, then a full-width `div` for category
    - Change all `PieChart` components from `size="medium"` to `size="large"`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 5. Clean up TypeScript types and translations
  - [x] 5.1 Remove unused types from `frontend/src/types/index.ts`
    - Remove `PromptDetail` interface
    - Remove `PromptMetadata` interface
    - Remove `PromptsListResponse` interface
    - Remove `RecentPrompt` interface (if unused after prompts removal)
    - Remove `FeedbackSubmission` interface
    - Remove `FeedbackRecord` interface
    - Remove `FeedbackListResponse` interface
    - Remove `FeedbackReviewAction` interface
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 5.2 Remove unused translation keys from locale files
    - Remove all keys prefixed with `prompts.` from `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json`
    - Remove all keys prefixed with `promptDetail.` from both locale files
    - Remove all keys prefixed with `feedback.` from both locale files
    - Ensure both files remain alphabetically sorted
    - _Requirements: 7.4_

  - [x] 5.3 Remove any remaining references to `/api/feedback` in frontend source
    - Search for and remove any API client calls or constants referencing `/api/feedback`
    - _Requirements: 3.2_

- [x] 6. Checkpoint - Build verification and final validation
  - Ensure all tests pass, ask the user if questions arise.
  - Run `cd frontend && npm run build` to verify TypeScript compilation succeeds and locale key-parity check passes
  - Verify deleted files no longer exist: `RecentPromptsTable.tsx`, `PromptDetailPanel.tsx`, `FeedbackModal.tsx`, `FeedbackAdminPage.tsx`
  - Verify no references to `/api/feedback` remain in frontend source
  - Verify no `prompts.`, `promptDetail.`, `feedback.` keys remain in locale files
  - _Requirements: 7.5, 7.6_

- [ ]* 7. Write frontend tests for removed components
  - [ ]* 7.1 Write tests verifying Usage tab renders without prompts table
    - Verify `RecentPromptsTable` is not rendered
    - Verify no HTTP request to `/api/prompts` is made on load
    - _Requirements: 1.1, 1.4_
  - [ ]* 7.2 Write tests verifying distribution charts new layout
    - Verify `DistributionCharts` renders with `size="large"` pie charts
    - Verify the 2-column + full-width layout structure
    - _Requirements: 4.1, 4.3, 4.4_
  - [ ]* 7.3 Write tests verifying navigation does not include feedback admin link
    - Verify App routes do not include feedback admin page
    - _Requirements: 3.3, 3.5_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The backend is modified first since the frontend still works without the prompts API (it just gets 404s which are non-critical)
- The correlation agent is explicitly NOT modified — it continues to access prompt data server-side for analysis
- The `useSplitPanel` hook and `SplitPanelProvider` remain in the codebase as general-purpose utilities
- `selectedCategory` state in UserPage was only used to filter the prompts table, so it is removed along with the prompts code
- The `RecentPrompt` interface in `types/index.ts` should also be checked — it may be unused after `UserDetailResponse.recentPrompts` is no longer consumed by the prompts table

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3"] },
    { "id": 5, "tasks": ["7.1", "7.2", "7.3"] }
  ]
}
```
