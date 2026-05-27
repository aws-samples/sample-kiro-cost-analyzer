# Requirements Document

## Introduction

Re-introduce the prompt history display feature in the Kiro Cost Analyzer (KCA) application. This feature was previously removed for privacy reasons (see `.kiro/specs/remove-prompt-content-visibility/`). Multiple clients (tenants/organizations) have now requested the functionality back, but with stricter access control: the prompt history is only accessible to administrators, and only when an admin has explicitly enabled the visibility toggle in the Settings screen. Regular (non-admin) users never see prompt history regardless of the toggle state.

## Glossary

- **KCA**: Kiro Cost Analyzer — the serverless application for analyzing Kiro usage and costs.
- **Prompt_History_Feature**: The opt-in feature that displays prompt metadata and content, restricted to administrators and controlled by an admin toggle.
- **Admin_Toggle**: A configuration setting in the Settings page that enables or disables the Prompt_History_Feature for the tenant.
- **Prompts_Table**: The table component that displays prompt metadata (content preview, date/time, category) for a selected user.
- **Prompt_Detail_Panel**: A split panel component that displays the full prompt and response content when a row is selected.
- **Settings_Page**: The admin configuration page inside AdminPage (tab "settings") with sub-tabs for ETL, Data, Identity, Engagement, and Pricing.
- **Usage_Tab**: The "Usage" tab within UserPage that shows summary cards, daily usage chart, and distribution charts.
- **Config_API**: The backend endpoints at `/api/config` (GET) and `/api/config/*` (PUT) that manage application configuration stored in SSM Parameter Store.
- **Prompts_API**: The backend endpoints at `/api/prompts` (list) and `/api/prompts/{requestId}` (detail) that return prompt data from DynamoDB.
- **Empty_Category**: Prompts classified with category "empty", which represent non-meaningful interactions.
- **System_Categories**: The set of categories considered non-meaningful: Empty, NOT_CATEGORIZED, Classification Error.

## Requirements

### Requirement 1: Admin Toggle for Prompt History Visibility

**User Story:** As an administrator, I want to enable or disable prompt history visibility, so that I can control whether prompt content is accessible in the application.

#### Acceptance Criteria

1. THE Settings_Page SHALL include an Admin_Toggle control to enable or disable the Prompt_History_Feature, displaying the current persisted state (enabled or disabled) when the page loads.
2. THE Admin_Toggle SHALL be located in a dedicated sub-tab within the Settings_Page, alongside the existing sub-tabs (ETL, Data, Identity, Engagement, Pricing).
3. WHEN an administrator changes the Admin_Toggle value, THE Settings_Page SHALL persist the setting via a PUT request to the Config_API and display a success notification upon receiving a 200 response.
4. IF the PUT request to persist the Admin_Toggle fails, THEN THE Settings_Page SHALL display an error notification indicating the setting was not saved and revert the toggle to its previous state.
5. THE Config_API SHALL store the Prompt_History_Feature enabled state as a string value ("true" or "false") in SSM Parameter Store under the `/kiro-cost-analyzer/` prefix path.
6. THE default value of the Prompt_History_Feature for new deployments SHALL be disabled (prompts not visible).
7. THE Admin_Toggle SHALL only be accessible to users in the Admins group.

### Requirement 2: Feature Flag Propagation to Frontend

**User Story:** As the frontend application, I want to know whether prompt history is enabled, so that I can conditionally render the prompts section for administrators.

#### Acceptance Criteria

1. THE Config_API GET `/api/config` response SHALL include a boolean field indicating whether the Prompt_History_Feature is enabled.
2. WHEN the Prompt_History_Feature is disabled, THE Usage_Tab SHALL NOT render the Prompts_Table component.
3. WHEN the Prompt_History_Feature is disabled, THE Usage_Tab SHALL NOT make any HTTP request to the Prompts_API.
4. WHEN the Prompt_History_Feature is enabled AND the current user is an administrator, THE Usage_Tab SHALL render the Prompts_Table component below the distribution charts.
5. IF the current user is NOT an administrator, THEN THE Usage_Tab SHALL NOT render the Prompts_Table regardless of the Admin_Toggle state.
6. IF the GET `/api/config` request fails or the feature flag field is absent from the response, THEN THE Usage_Tab SHALL treat the Prompt_History_Feature as disabled and SHALL NOT render the Prompts_Table.

### Requirement 3: Prompts List API Endpoint

**User Story:** As an administrator with prompt history enabled, I want to retrieve prompt history for any user via an API, so that the frontend can display it.

#### Acceptance Criteria

1. THE backend SHALL expose a GET `/api/prompts` endpoint that returns paginated prompt metadata.
2. THE GET `/api/prompts` endpoint SHALL accept query parameters for pagination (limit, nextToken), date filtering (startDate, endDate in YYYY-MM-DD format), category filtering (category), and user filtering (userId).
3. THE GET `/api/prompts` endpoint SHALL exclude prompts with Empty_Category by default; WHEN the category query parameter is explicitly set to "empty", THE endpoint SHALL include Empty_Category prompts in the response.
4. THE GET `/api/prompts` endpoint SHALL restrict access to administrators only; non-admin users SHALL receive a 403 response.
5. WHEN the Prompt_History_Feature is disabled, THE GET `/api/prompts` endpoint SHALL return a 403 response with a message indicating the feature is not enabled.
6. THE GET `/api/prompts` response SHALL include for each prompt: requestId, timestamp, category, and a content preview limited to 200 characters of the prompt text with trailing ellipsis when truncated.
7. IF the userId query parameter is missing or empty, THEN THE GET `/api/prompts` endpoint SHALL return a 400 response with a message indicating that userId is required.
8. THE GET `/api/prompts` endpoint SHALL apply a default limit of 20 items and a maximum limit of 100 items per request; IF the limit parameter exceeds 100, THEN THE endpoint SHALL cap it to 100.

### Requirement 4: Prompt Detail API Endpoint

**User Story:** As an administrator viewing prompt history, I want to see the full content of a specific prompt, so that I can review what was sent and received.

#### Acceptance Criteria

1. THE backend SHALL expose a GET `/api/prompts/{requestId}` endpoint that returns the full prompt and response content, accepting a userId query parameter to locate the item in DynamoDB.
2. THE GET `/api/prompts/{requestId}` endpoint SHALL retrieve content from DynamoDB (inline) or S3 (when contentInS3 is true) at key `prompts-content/{requestId}.json`.
3. THE GET `/api/prompts/{requestId}` endpoint SHALL restrict access to administrators only; non-admin users SHALL receive a 403 response.
4. WHEN the Prompt_History_Feature is disabled, THE GET `/api/prompts/{requestId}` endpoint SHALL return a 403 response with a message indicating the feature is not enabled.
5. IF the requested prompt does not exist, THEN THE endpoint SHALL return a 404 response.
6. IF the prompt content is stored in S3 and the S3 retrieval fails, THEN THE endpoint SHALL return a 500 response with a message indicating content retrieval failure.
7. THE GET `/api/prompts/{requestId}` response SHALL include fields: requestId, timestamp, category, modelId, prompt (full content), response (full content), promptLength, responseLength.

### Requirement 5: Prompts Table in Usage Tab (Admin Only)

**User Story:** As an administrator, I want to see a table of recent prompts for the user I am viewing in the Usage tab, so that I can browse prompt history with metadata.

#### Acceptance Criteria

1. WHEN the Prompt_History_Feature is enabled AND the current user is an administrator, THE Usage_Tab SHALL display a Prompts_Table below the distribution charts showing prompts belonging to the viewed user.
2. THE Prompts_Table SHALL display columns for: prompt content (truncated to a maximum of 100 characters with an ellipsis indicator), date/time, and category classification.
3. THE Prompts_Table SHALL support pagination with a default page size of 20 and selectable options of 10, 20, and 50 items per page.
4. THE Prompts_Table SHALL support filtering by category using the list of categories present in the viewed user's prompt data.
5. THE Prompts_Table SHALL NOT display prompts whose category belongs to the System_Categories set (Empty, NOT_CATEGORIZED, Classification Error) by default.
6. WHEN an administrator selects a row in the Prompts_Table, THE Usage_Tab SHALL open a Prompt_Detail_Panel showing the full prompt content and full response content.
7. THE Prompts_Table date/time column SHALL use the locale-aware `formatDateTime` formatter from `useI18n()`.
8. IF the viewed user has no prompts matching the current filter, THEN THE Prompts_Table SHALL display an empty state message indicating no prompts are available.

### Requirement 6: Prompt Detail Panel

**User Story:** As an administrator, I want to view the full content of a prompt and its response, so that I can review the complete interaction.

#### Acceptance Criteria

1. THE Prompt_Detail_Panel SHALL display the full prompt content and the full response content in visually distinct, labeled sections with independently scrollable areas when content exceeds the visible panel height.
2. THE Prompt_Detail_Panel SHALL display the prompt timestamp (formatted via the locale-aware `formatDateTime` from `useI18n()`), category, and model identifier.
3. THE Prompt_Detail_Panel SHALL be implemented as a Cloudscape SplitPanel component using the existing `useSplitPanel` hook, with a header indicating the selected prompt's category or identifier.
4. WHEN the Prompt_Detail_Panel is loading content, THE panel SHALL display a Cloudscape Spinner or StatusIndicator in the panel body while the GET `/api/prompts/{requestId}` request is in progress.
5. IF the detail request fails, THEN THE Prompt_Detail_Panel SHALL display an error message indicating the failure reason and a retry button that re-issues the GET `/api/prompts/{requestId}` request without closing the panel.
6. WHEN the administrator closes the Prompt_Detail_Panel, THE panel SHALL clear its content and deselect the active row in the Prompts_Table.

### Requirement 7: Internationalization Support

**User Story:** As an administrator in any supported locale, I want the prompt history UI to be fully translated, so that I can use the feature in my preferred language.

#### Acceptance Criteria

1. THE Prompts_Table and Prompt_Detail_Panel SHALL use translation keys via `useI18n()` for all user-facing strings, with no hardcoded text literals except brand strings defined under `brand.*` keys.
2. Translation keys for the prompt history feature SHALL be added to both `en.json` and `pt-BR.json` locale files with identical key sets, non-empty string values, and keys sorted alphabetically within each file.
3. THE translation keys SHALL follow the existing dot-notation convention with prefixes `prompts.*` for table-level strings and `promptDetail.*` for detail panel strings.
4. THE `scripts/check-locales.ts` build-time check SHALL pass after adding the new translation keys, confirming key parity, alphabetical sort order, non-empty values, and successful generation of `keys.d.ts` with updated `TranslationKey` type.
5. WHEN a translation key uses interpolation placeholders (e.g., `{{count}}`, `{{date}}`), THE locale files SHALL contain identical placeholder names in both `en.json` and `pt-BR.json` values for that key.

### Requirement 8: TypeScript Types for Prompt Data

**User Story:** As a developer, I want typed interfaces for prompt API responses, so that the frontend code is type-safe and maintainable.

#### Acceptance Criteria

1. THE frontend SHALL define a `PromptMetadata` interface in `types/index.ts` with fields: requestId (string), timestamp (string), category (string), promptPreview (string), modelId (string), triggerType (string), promptLength (number), responseLength (number).
2. THE frontend SHALL define a `PromptsListResponse` interface in `types/index.ts` with fields: items (array of PromptMetadata), nextToken (string or null).
3. THE frontend SHALL define a `PromptDetail` interface in `types/index.ts` with fields: requestId (string), timestamp (string), category (string), modelId (string), prompt (string), response (string), promptLength (number), responseLength (number), contentInS3 (boolean).
4. THE frontend build SHALL compile without type errors when running `npm run build` after adding the new interfaces.
5. WHEN the `PromptsListResponse` contains zero items, THE frontend types SHALL permit an empty array for the `items` field and null for the `nextToken` field.

### Requirement 9: Sensitive Data Protection (No Logging of Content)

**User Story:** As a system administrator, I want to ensure that prompt content, SSM parameter values, and security-sensitive data are never written to application logs, so that sensitive information cannot be leaked through observability channels.

#### Acceptance Criteria

1. THE backend SHALL NOT log prompt content (the `prompt` or `response` fields) at any log level (DEBUG, INFO, WARNING, ERROR) in any handler, repository method, or utility function involved in serving the Prompts_API.
2. THE backend SHALL NOT log SSM Parameter Store key names or values related to the Prompt_History_Feature toggle when reading or writing the configuration.
3. THE backend SHALL NOT log the full request body or response body of the Prompts_API endpoints; only structured metadata (requestId, userId, timestamp, category, HTTP status code) MAY be logged.
4. IF an error occurs during prompt content retrieval (DynamoDB or S3), THEN THE backend SHALL log the error type and a generic message (e.g., "Content retrieval failed for requestId={id}") without including the content itself in the log entry.
5. THE frontend SHALL NOT log prompt content to the browser console in production builds; console output of prompt/response text SHALL be restricted to development builds only (guarded by `import.meta.env.DEV`).
6. THE backend structured logger fields for Prompts_API requests SHALL be limited to: `requestId`, `userId`, `category`, `httpMethod`, `path`, `statusCode`, `latencyMs`, and `errorType` (when applicable); no field SHALL contain prompt text, response text, or SSM parameter values.
7. WHEN the StructuredLogger is used in the prompts handler, THE log entries SHALL NOT include any field whose value is derived from user-generated prompt or response content.

### Requirement 10: Access Control and Security

**User Story:** As a system administrator, I want prompt history access to be restricted to administrators only, so that regular users cannot view prompt content and the feature cannot be accessed when disabled.

#### Acceptance Criteria

1. WHEN a non-admin user makes any request to the Prompts_API, THE backend SHALL return a 403 response with body `{"error": "Forbidden", "message": "Access restricted to administrators"}`.
2. IF the Prompt_History_Feature is disabled globally (the SSM parameter value is not "true"), THEN THE Prompts_API SHALL reject all requests with a 403 response regardless of the caller's role.
3. THE Admin_Toggle PUT endpoint SHALL only be accessible to users in the Admins group and SHALL return a 403 response with body `{"error": "Forbidden", "message": "Access restricted to administrators"}` to non-admin callers.
4. THE Prompts_API SHALL validate the feature-enabled state on every request by reading the configuration from SSM Parameter Store, using a cached value with a maximum staleness of 300 seconds.
5. IF the SSM Parameter Store is unreachable when validating the feature-enabled state, THEN THE Prompts_API SHALL treat the feature as disabled and return a 403 response.
