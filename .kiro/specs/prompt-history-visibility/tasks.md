# Implementation Plan: Prompt History Visibility

## Overview

This plan implements the admin-controlled prompt history visibility feature. The implementation follows a backend-first approach: feature flag cache and config handler changes, then the prompts handler, then frontend types and components, and finally integration wiring. Each task builds incrementally on the previous ones, with checkpoints to validate correctness.

## Tasks

- [x] 1. Backend: Feature flag cache and config handler changes
  - [x] 1.1 Implement `_FeatureFlagCache` class in `backend/handlers/prompts_handler.py`
    - Create `backend/handlers/prompts_handler.py` with the `_FeatureFlagCache` class
    - In-memory cache with 300s TTL for the SSM parameter `/kiro-cost-analyzer/prompt-history-enabled`
    - `is_enabled(cls, ssm_client=None) -> bool` class method
    - Fail-closed: return `False` on any SSM error
    - Use `os.environ.get("SSM_PROMPT_HISTORY_ENABLED", "/kiro-cost-analyzer/prompt-history-enabled")` for the parameter name
    - MUST NOT log the SSM parameter path or its value
    - _Requirements: 10.4, 10.5, 9.2_

  - [x] 1.2 Add `handle_put_config_prompt_history_enabled` to `backend/handlers/config_handler.py`
    - Accept `body: dict` with `enabled: bool` field
    - Validate that `enabled` is a boolean; return 400 if not
    - Write `"true"` or `"false"` to SSM parameter
    - Return `{ "status": "valid", "message": "Prompt history visibility updated", "enabled": <bool> }`
    - MUST NOT log the SSM parameter value
    - _Requirements: 1.5, 9.2_

  - [x] 1.3 Modify `handle_get_config` in `backend/handlers/config_handler.py` to include `promptHistoryEnabled`
    - Read the prompt-history-enabled SSM parameter
    - Return `"promptHistoryEnabled": True/False` in the response dict
    - Default to `False` if parameter doesn't exist or read fails
    - _Requirements: 2.1, 1.6_

  - [ ]* 1.4 Write property tests for feature flag cache (Property 8: SSM parameter values never logged)
    - **Property 8: SSM parameter values and error content never logged**
    - **Validates: Requirements 9.2, 9.4**
    - Use Hypothesis to generate SSM operations, capture log output, verify no SSM values appear

- [x] 2. Backend: Prompts handler endpoints
  - [x] 2.1 Implement `handle_list_prompts` in `backend/handlers/prompts_handler.py`
    - Accept `query_params: dict` with `userId` (required), `limit`, `nextToken`, `startDate`, `endDate`, `category`
    - Validate `userId` present → 400 if missing
    - Check feature enabled via `_FeatureFlagCache.is_enabled()` → 403 if disabled
    - Clamp limit to [1, 100], default 20
    - Exclude System_Categories (Empty, NOT_CATEGORIZED, Classification Error) by default
    - Generate `promptPreview`: truncate prompt to 200 chars with `"..."` suffix when exceeded
    - Use existing `analytics_repository` methods for data access
    - Return `{ "items": [...], "nextToken": ... }`
    - Log only metadata fields (requestId, userId, category, statusCode) — NEVER log content
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 9.1, 9.3, 9.6_

  - [x] 2.2 Implement `handle_get_prompt_detail` in `backend/handlers/prompts_handler.py`
    - Accept `request_id: str` and `query_params: dict` with `userId` (required)
    - Check feature enabled via `_FeatureFlagCache.is_enabled()` → 403 if disabled
    - Query DynamoDB by requestId (GSI) or PK/SK pattern
    - If `contentInS3 == True`, fetch from S3 at `prompts-content/{requestId}.json`
    - Return full prompt and response content with metadata
    - On S3 failure: return 500 with generic message, log errorType only (NO content in logs)
    - On not found: return 404
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 9.1, 9.4_

  - [x] 2.3 Add routes to `backend/handler.py` for prompts endpoints
    - Add `import prompts_handler` to the handlers imports
    - Add regex pattern `_PROMPT_DETAIL_PATTERN = re.compile(r"^/api/prompts/([^/]+)$")`
    - Route `GET /api/prompts` → admin-only → `prompts_handler.handle_list_prompts`
    - Route `GET /api/prompts/{requestId}` → admin-only → `prompts_handler.handle_get_prompt_detail`
    - Route `PUT /api/config/prompt-history-enabled` → admin-only → `config_handler.handle_put_config_prompt_history_enabled`
    - _Requirements: 3.4, 4.3, 10.1, 10.3, 1.7_

  - [ ]* 2.4 Write property tests for pagination (Property 1: Pagination returns at most `limit` items)
    - **Property 1: Pagination returns at most limit items**
    - **Validates: Requirements 3.1, 3.8**
    - Use Hypothesis to generate random prompt sets, verify response contains ≤ limit items and pages are disjoint

  - [ ]* 2.5 Write property tests for system category exclusion (Property 2: System categories excluded by default)
    - **Property 2: System categories excluded by default**
    - **Validates: Requirements 3.3, 5.5**
    - Use Hypothesis to generate prompts with mixed categories, verify System_Categories absent from default response

  - [ ]* 2.6 Write property tests for content preview truncation (Property 3: Content preview truncation — 200 chars)
    - **Property 3: Content preview truncation (API — 200 chars)**
    - **Validates: Requirements 3.6**
    - Use Hypothesis to generate random strings, verify 200-char truncation with ellipsis

  - [ ]* 2.7 Write property tests for limit clamping (Property 4: Limit clamping)
    - **Property 4: Limit clamping**
    - **Validates: Requirements 3.8**
    - Use Hypothesis to generate random integers, verify clamping to [1, 100] with default 20

  - [ ]* 2.8 Write property tests for log safety (Property 7: Log entries contain only allowed metadata fields)
    - **Property 7: Log entries contain only allowed metadata fields**
    - **Validates: Requirements 9.1, 9.3, 9.6, 9.7**
    - Use Hypothesis to generate random prompt content, serve through handler, capture logs, verify no content in logs

- [x] 3. Checkpoint — Backend validation
  - Ensure all backend tests pass, ask the user if questions arise.

- [x] 4. Frontend: TypeScript types and AppConfig update
  - [x] 4.1 Add `PromptMetadata`, `PromptsListResponse`, and `PromptDetail` interfaces to `frontend/src/types/index.ts`
    - Add `PromptMetadata` with fields: requestId, timestamp, category, promptPreview, modelId, triggerType, promptLength, responseLength
    - Add `PromptsListResponse` with fields: items (PromptMetadata[]), nextToken (string | null)
    - Add `PromptDetail` with fields: requestId, timestamp, category, modelId, prompt, response, promptLength, responseLength, contentInS3
    - _Requirements: 8.1, 8.2, 8.3, 8.5_

  - [x] 4.2 Add `promptHistoryEnabled: boolean` to the `AppConfig` interface in `frontend/src/types/index.ts`
    - Modify existing `AppConfig` interface to include the new field
    - _Requirements: 2.1, 8.4_

- [ ] 5. Frontend: i18n keys for prompt history
  - [x] 5.1 Add translation keys to `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json`
    - Add keys with prefix `prompts.*` for table-level strings (title, columns, empty state, pagination, filters, errors)
    - Add keys with prefix `promptDetail.*` for detail panel strings (header, sections, loading, error, retry, close)
    - Add keys for the Settings toggle tab (e.g., `settings.tabs.prompts`, `settings.promptHistory.*`)
    - Ensure keys are sorted alphabetically within each file
    - Ensure identical key sets and placeholder names in both locale files
    - _Requirements: 7.1, 7.2, 7.3, 7.5_

  - [ ]* 5.2 Write property test for locale catalog integrity (Property 9: Locale catalog integrity)
    - **Property 9: Locale catalog integrity for prompt history keys**
    - **Validates: Requirements 7.2, 7.3, 7.5**
    - Use fast-check to load both locale files, verify key parity and placeholder consistency for `prompts.*`/`promptDetail.*` keys

- [x] 6. Frontend: PromptHistoryToggle component and Settings page integration
  - [x] 6.1 Create `frontend/src/components/PromptHistoryToggle.tsx`
    - Cloudscape Toggle component showing current enabled/disabled state
    - PUT `/api/config/prompt-history-enabled` on change
    - Success notification on save
    - Error notification + revert toggle on failure
    - Use `useI18n()` for all user-facing strings
    - _Requirements: 1.1, 1.3, 1.4, 7.1_

  - [x] 6.2 Add "Prompts" tab to `frontend/src/pages/SettingsPage.tsx`
    - Add new tab entry to `configTabs` array, admin-only (same pattern as Pricing tab)
    - Tab content renders `<PromptHistoryToggle />`
    - _Requirements: 1.2, 1.7_

- [x] 7. Frontend: PromptsTable and PromptDetailPanel components
  - [x] 7.1 Create `frontend/src/components/PromptsTable.tsx`
    - Cloudscape Table with columns: prompt content (truncated to 100 chars with ellipsis), date/time (via `formatDateTime`), category
    - Pagination with page sizes 10, 20, 50 (default 20)
    - Category filter (PropertyFilter or Select) excluding System_Categories by default
    - Empty state message when no prompts match
    - On row select → trigger detail panel open (via callback prop or useSplitPanel)
    - Fetch `GET /api/prompts?userId=...&limit=...&startDate=...&endDate=...`
    - MUST NOT log prompt content to console in production (guard with `import.meta.env.DEV`)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 5.8, 9.5_

  - [x] 7.2 Create `frontend/src/components/PromptDetailPanel.tsx`
    - Cloudscape SplitPanel content with header showing category/requestId
    - Display timestamp (formatDateTime), category, modelId as metadata
    - Two labeled, independently scrollable sections: Prompt content, Response content
    - Loading state: Spinner/StatusIndicator while fetching
    - Error state: Alert with error message + Retry button
    - On close: clear content and deselect row (via onClose callback)
    - Fetch `GET /api/prompts/{requestId}?userId=...`
    - MUST NOT log prompt content to console in production
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 9.5_

  - [ ]* 7.3 Write property test for UI content truncation (Property 5: UI content truncation — 100 chars)
    - **Property 5: UI content truncation (Table — 100 chars)**
    - **Validates: Requirements 5.2**
    - Use fast-check to generate random strings, verify 100-char truncation with ellipsis in rendered cell

  - [ ]* 7.4 Write property test for DateTime formatting (Property 6: DateTime formatting uses locale-aware formatter)
    - **Property 6: DateTime formatting uses locale-aware formatter**
    - **Validates: Requirements 5.7**
    - Use fast-check to generate random ISO timestamps, verify formatDateTime consistency

- [x] 8. Frontend: Wire PromptsTable into UserPage
  - [x] 8.1 Modify `frontend/src/pages/UserPage.tsx` to conditionally render PromptsTable
    - Fetch `promptHistoryEnabled` from config API (already fetched or add fetch)
    - Check `isAdmin` from auth context
    - When both conditions true: render `<PromptsTable>` below `<DistributionCharts>` in the Usage tab
    - When feature disabled or user not admin: do NOT render PromptsTable and do NOT call Prompts_API
    - If config API fails or field absent: treat as disabled
    - Wire SplitPanel for PromptDetailPanel using existing `useSplitPanel` hook
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6_

- [x] 9. Checkpoint — Frontend validation
  - Ensure all frontend tests pass and `npm run build` compiles without errors, ask the user if questions arise.

- [x] 10. Verification: Sensitive data protection
  - [x] 10.1 Verify no prompt content or SSM values in logs
    - Review `prompts_handler.py` to confirm no logger call references content variables
    - Review `config_handler.py` toggle handler to confirm no SSM value logging
    - Add explicit unit test: serve a prompt request, capture all log output, assert no content substring appears
    - Add explicit unit test: perform SSM read/write for toggle, capture logs, assert no parameter value appears
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6, 9.7_

- [x] 11. Final checkpoint — Full validation
  - Ensure all Python tests pass (`pytest`), all TypeScript tests pass (`npm run test`), frontend builds without errors (`npm run build`), and `check-locales.ts` passes. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties defined in the design
- Unit tests validate specific examples and edge cases
- Requirement 9 (sensitive data protection) is addressed both in implementation tasks (1.1, 2.1, 2.2) and in a dedicated verification task (10.1)
- The existing `analytics_repository` methods (`get_user_prompts`, `get_prompt_by_request_id`) are reused — no new repository code needed
- The `_FeatureFlagCache` is co-located in `prompts_handler.py` for simplicity; it could be extracted to `utils/` if reused elsewhere

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "4.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "4.2"] },
    { "id": 2, "tasks": ["1.4", "2.1", "5.1"] },
    { "id": 3, "tasks": ["2.2", "2.4", "2.5", "2.6", "2.7", "5.2", "6.1"] },
    { "id": 4, "tasks": ["2.3", "2.8", "6.2", "7.1"] },
    { "id": 5, "tasks": ["7.2", "7.3", "7.4"] },
    { "id": 6, "tasks": ["8.1"] },
    { "id": 7, "tasks": ["10.1"] }
  ]
}
```
