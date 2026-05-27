# Requirements Document

## Introduction

Remove the prompts section entirely from the Kiro Cost Analyzer (KCA) UI, including the prompts table, detail panel, and feedback functionality. Prompts may contain proprietary code, internal file names, business logic, and infrastructure details that should not be accessible through the application. The distribution charts (model, trigger, category) remain visible but should be reorganized to use the available space better — currently they are cramped in a 3-column grid. The correlation agent's `promptSummary` field (a brief AI-generated description) is unaffected since it does not expose raw content.

## Glossary

- **KCA**: Kiro Cost Analyzer — the serverless application for analyzing Kiro usage and costs.
- **Prompts_Section**: The entire prompts area in the Usage tab, including the `RecentPromptsTable` component, the `PromptDetailPanel` split panel, and associated state/fetching logic.
- **Feedback_Feature**: The category feedback workflow consisting of the `FeedbackModal` component, the "Correct Category" button in the detail panel, and the `/api/feedback` backend endpoint.
- **Distribution_Charts**: The `DistributionCharts` component that renders three pie charts (model, trigger, category) in a `Grid` layout.
- **Detail_Panel**: The `PromptDetailPanel` split panel component that displays prompt content.
- **Prompts_API**: The backend endpoints at `/api/prompts` (list) and `/api/prompts/{requestId}` (detail) that return prompt data.
- **Correlation_Agent**: The Git-Kiro Correlation Agent that produces `promptSummary` fields (brief AI-generated descriptions, not raw content).

## Requirements

### Requirement 1: Remove Prompts Table from Usage Tab

**User Story:** As a user, I want the prompts listing removed from the usage tab, so that raw prompt metadata is no longer browsable in the UI.

#### Acceptance Criteria

1. THE Usage tab SHALL NOT render the `RecentPromptsTable` component.
2. THE Usage tab SHALL NOT fetch data from the `/api/prompts` list endpoint.
3. THE Usage tab SHALL NOT contain pagination state, prompt filtering state, or category selection state related to the prompts table.
4. WHEN the Usage tab loads, THE application SHALL NOT make any HTTP request to `/api/prompts`.

### Requirement 2: Remove Prompt Detail Panel

**User Story:** As a user, I want the prompt detail panel removed, so that raw prompt and response content is never displayed in the UI.

#### Acceptance Criteria

1. THE Usage tab SHALL NOT render the `PromptDetailPanel` component.
2. THE Usage tab SHALL NOT use the `useSplitPanel` hook for prompt detail display.
3. THE `PromptDetailPanel` component file SHALL be deleted from the codebase.
4. THE `RecentPromptsTable` component file SHALL be deleted from the codebase.

### Requirement 3: Remove Feedback Feature

**User Story:** As a user, I want the category feedback feature removed, so that there is no workflow that requires viewing prompt content.

#### Acceptance Criteria

1. THE `FeedbackModal` component file SHALL be deleted from the codebase.
2. THE frontend SHALL NOT contain any reference to the `/api/feedback` endpoint.
3. THE `FeedbackAdminPage` SHALL be removed from the application routing.
4. THE backend `/api/feedback` endpoint handler SHALL be removed.
5. THE navigation SHALL NOT include a link to the feedback admin page.

### Requirement 4: Reorganize Distribution Charts Layout

**User Story:** As a user, I want the distribution charts to use the full available width, so that the pie charts and their legends are readable without being cramped.

#### Acceptance Criteria

1. THE Distribution_Charts component SHALL use a layout that gives each chart more horizontal space than the current `colspan: 4` (one-third) grid.
2. WHEN the prompts section is removed, THE Distribution_Charts SHALL expand to fill the space previously occupied by the prompts table.
3. THE Distribution_Charts SHALL display model, trigger, and category pie charts with `size="large"` instead of `size="medium"`.
4. THE Distribution_Charts layout SHALL use a 2-column grid for the first row (model + trigger) and a full-width row for the category chart, OR an alternative layout that provides more space per chart than the current equal-thirds approach.
5. THE category chart legends SHALL be fully readable without text truncation.

### Requirement 5: Remove Prompts API Endpoints

**User Story:** As a system administrator, I want the prompts API endpoints removed, so that raw prompt content is not accessible through any application interface.

#### Acceptance Criteria

1. THE backend SHALL NOT expose a GET `/api/prompts` endpoint.
2. THE backend SHALL NOT expose a GET `/api/prompts/{requestId}` endpoint.
3. THE backend route handler SHALL return 404 for any request to `/api/prompts` paths.
4. THE backend SHALL NOT fetch prompt content from S3 for any user-facing request.

### Requirement 6: Preserve Correlation Agent Output

**User Story:** As a user, I want the correlation agent's prompt summaries to remain available, so that I can still see AI-generated descriptions of my usage patterns.

#### Acceptance Criteria

1. THE Correlation_Agent output SHALL continue to include the `promptSummary` field in correlation results.
2. THE Correlation_Agent SHALL NOT be modified by this change (the agent reads prompts internally for analysis but its output contains only summaries, not raw content).
3. THE Correlation_Agent's internal tool `get_kiro_usage` SHALL continue to access prompt data for analysis purposes (this is server-side only, not exposed to users).

### Requirement 7: Clean Up TypeScript Types and Translations

**User Story:** As a developer, I want unused types and translation keys removed, so that the codebase stays clean and maintainable.

#### Acceptance Criteria

1. THE `PromptDetail` interface SHALL be removed from `types/index.ts`.
2. THE `PromptMetadata` interface SHALL be removed from `types/index.ts` IF it is no longer used by any remaining component.
3. THE `PromptsListResponse` interface SHALL be removed from `types/index.ts`.
4. Translation keys prefixed with `prompts.`, `promptDetail.`, and `feedback.` SHALL be removed from both `en.json` and `pt-BR.json` locale files.
5. THE frontend build SHALL compile without type errors after all removals.
6. THE locale key-parity check (`scripts/check-locales.ts`) SHALL pass after translation key removals.
