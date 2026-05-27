# Requirements Document — Git-Kiro Semantic Correlation via AI Agent (AgentCore)

## Introduction

This feature replaces the legacy Git sync pipeline (Step Functions + periodic sync + Pearson correlation from PR #15) with an on-demand AI Agent deployed on Amazon Bedrock AgentCore (sa-east-1). The agent uses the Strands Agents SDK with Claude Sonnet to perform SEMANTIC correlation between Kiro prompts and GitHub activity (commits and PRs).

The agent is deployed on AgentCore and invoked by the backend Lambda when a user requests a productivity analysis. The agent autonomously fetches data using `@tool` decorated functions (Strands SDK pattern), performs semantic analysis, and returns structured insights. Results are cached in DynamoDB to avoid redundant LLM invocations.

**Critical architectural constraint**: Strands Agents require tools to be Python functions decorated with `@tool` from `strands.tool`. The agent is created with `Agent(model=..., tools=[tool_fn_1, tool_fn_2], system_prompt=...)`. The agent autonomously decides when and how to call tools — the entrypoint does NOT pre-fetch data.

## Glossary

- **AgentCore**: Amazon Bedrock AgentCore — managed serverless runtime for AI agents (sa-east-1).
- **AgentCore_Runtime**: The deployed agent instance on AgentCore, invocable via `bedrock-agentcore` boto3 client.
- **Strands_Agent**: An `Agent` instance from the `strands` SDK, configured with a model, tools, and system prompt.
- **Strands_Tool**: A Python function decorated with `@tool` from `strands.tool` that the Strands Agent can invoke autonomously during reasoning.
- **Correlation_Analysis**: Structured JSON output from the agent containing semantic correlations between Kiro prompts and Git activity, an impact score, and insights.
- **Cache_Analysis**: A DynamoDB record that persists a Correlation_Analysis result to avoid re-invocation.
- **GitHub_Tool**: A `@tool` decorated function that calls the GitHub REST API to fetch commits and pull requests for a repository.
- **Kiro_Data_Tool**: A `@tool` decorated function that queries the Analytics_Table in DynamoDB to fetch Kiro usage data (prompts, daily stats, categories).
- **Analytics_Table**: The existing DynamoDB single-table design table used by the project.
- **User_Git_Mapping**: Association between a Kiro userId and a GitHub username, stored as PK `USER#{userId}`, SK `GITMAP#github#{gitUsername}`.
- **Backend_Handler**: The Lambda function that serves as proxy between the frontend and AgentCore — checks cache, invokes agent, persists results.
- **SSM_Token**: The GitHub personal access token stored in SSM Parameter Store (SecureString) at path `/kiro-cost-analyzer/git-tokens/{userId}`.
- **Bilingual_Insights**: A map keyed by locale tag (`en`, `pt-BR`) whose values are parallel lists of insight strings — same insight content, expressed in each locale, in the same order.
- **Status_Slug**: A stable, English, machine-readable identifier (e.g., `GIT_MAPPING_MISSING`, `GITHUB_AUTH_FAILED`, `INSUFFICIENT_DATA`) returned by the backend in place of human-readable prose. The frontend maps each slug to a translation key under `productivity.correlation.status.*`.

## Requirements

### Requirement 1: Strands Agent with Wired Tools

**User Story:** As a system developer, I want the AI agent to be properly constructed with callable tools, so that it can autonomously fetch data and perform semantic correlation analysis.

#### Acceptance Criteria

1. THE Strands_Agent SHALL be instantiated with `Agent(model=model, tools=[get_kiro_usage, get_github_activity], system_prompt=SYSTEM_PROMPT)` where both tools are `@tool` decorated Python functions.
2. THE `get_kiro_usage` Strands_Tool SHALL accept parameters `user_id` (str), `start_date` (str), and `end_date` (str), and SHALL return a dict containing prompts (list), daily_stats (list), and category_distribution (list) fetched from the Analytics_Table.
3. THE `get_github_activity` Strands_Tool SHALL accept parameters `owner` (str), `repo` (str), `author` (str), `since` (str), and `token` (str), and SHALL return a dict containing commits (list) and pull_requests (list) fetched from the GitHub REST API.
4. THE `get_kiro_usage` Strands_Tool SHALL truncate each prompt content to a maximum of 500 characters to control token costs.
5. THE `get_github_activity` Strands_Tool SHALL handle GitHub API rate limiting by returning a structured error message when HTTP 429 is received.
6. WHEN the GitHub token is invalid or expired, THE `get_github_activity` Strands_Tool SHALL return a structured error indicating authentication failure.
7. THE Strands_Agent SHALL use the model `global.anthropic.claude-sonnet-4-6-v1` via BedrockModel configured for region sa-east-1.

### Requirement 2: Agent Entrypoint and Autonomous Orchestration

**User Story:** As a system developer, I want the agent entrypoint to receive the invocation payload and let the agent autonomously orchestrate data fetching and analysis, so that the LLM decides when and how to call each tool.

#### Acceptance Criteria

1. THE `@app.entrypoint` handler SHALL receive a payload containing: userId, startDate, endDate, gitUsername, repos (list of {owner, repo}), and token (GitHub access token).
2. THE `@app.entrypoint` handler SHALL create the Strands_Agent with tools that have access to the token and DynamoDB table name from the payload/environment.
3. THE `@app.entrypoint` handler SHALL pass a user prompt to the agent describing the analysis task (user, period, repos to check), and SHALL let the agent autonomously decide which tools to call and in what order.
4. THE `@app.entrypoint` handler SHALL NOT pre-fetch data or pass empty data structures to the LLM — the agent uses its tools to gather data.
5. THE Strands_Agent SHALL respond with structured JSON output containing: impactScore (0-100 or null), impactLevel (low/moderate/high/veryHigh), correlations (list with promptSummary, gitActivity, confidence, type — all strings in English), and insights (a Bilingual_Insights map with keys `en` and `pt-BR`, each value being a list of strings of equal length and parallel ordering).
6. WHEN the agent output cannot be parsed as valid JSON, THE entrypoint SHALL return a fallback response with impactScore null and an error insight present in BOTH `insights.en` and `insights.pt-BR` (each list of equal length, same order, content translated).
7. THE `@app.entrypoint` handler SHALL return the analysis result as a JSON string.

### Requirement 3: Backend Handler — Token Retrieval and Agent Invocation

**User Story:** As a frontend consumer, I want to call a single REST endpoint that handles cache checking, token retrieval, and agent invocation transparently, so that the agent infrastructure is an implementation detail.

#### Acceptance Criteria

1. THE Backend_Handler SHALL expose GET `/api/productivity/{userId}/correlation` with optional query parameters: startDate, endDate, forceRefresh.
2. WHEN the endpoint is invoked and a valid Cache_Analysis exists (less than 24 hours old for the same period), THE Backend_Handler SHALL return the cached result directly without invoking the agent.
3. WHEN no valid cache exists, THE Backend_Handler SHALL fetch the GitHub token from SSM Parameter Store at path `/kiro-cost-analyzer/git-tokens/{userId}` before invoking AgentCore.
4. THE Backend_Handler SHALL pass the GitHub token in the AgentCore invocation payload so the agent's `get_github_activity` tool can authenticate with the GitHub API.
5. THE Backend_Handler SHALL invoke the AgentCore_Runtime via boto3 `bedrock-agentcore` client with a timeout of 60 seconds.
6. WHEN the agent invocation exceeds 60 seconds or fails, THE Backend_Handler SHALL return HTTP 503 with a structured error message.
7. THE Backend_Handler SHALL persist successful analysis results in DynamoDB before returning the response.
8. THE response contract SHALL be: `{ userId, impactScore, impactLevel, correlations[], insights: { en: string[], "pt-BR": string[] }, period, analyzedAt, cached, status?, message? }` where `status` is a Status_Slug and `message` is reserved for log-only context (never user-facing prose).
9. WHEN the user has no Git mapping configured, THE Backend_Handler SHALL return a response with impactScore null and `status="GIT_MAPPING_MISSING"`. THE Backend_Handler SHALL NOT include any human-readable Portuguese prose in the response body — the frontend resolves the slug via the i18n catalog.

### Requirement 4: User-Git Mapping and Token Storage

**User Story:** As a manager, I want to map Kiro users to their GitHub profiles and store access tokens securely, so that the agent can fetch the correct Git data for each user.

#### Acceptance Criteria

1. THE System SHALL reuse the existing DynamoDB mapping model (PK `USER#{userId}`, SK `GITMAP#github#{gitUsername}`) with fields: gitUsername, provider, repos (list of repository URLs), createdAt.
2. THE System SHALL store GitHub access tokens in SSM Parameter Store (SecureString) at path `/kiro-cost-analyzer/git-tokens/{userId}`.
3. THE System SHALL expose REST endpoints for CRUD of mappings: POST /api/git/mappings, GET /api/git/mappings/{userId}, DELETE /api/git/mappings/{userId}/{provider}/{gitUsername}.
4. WHEN a mapping is created or updated with a new token, THE System SHALL write the token to SSM Parameter Store at the path corresponding to the userId.
5. THE System SHALL support multiple repository URLs per mapping, allowing the agent to analyze activity across multiple repos.

### Requirement 5: Analysis Cache in DynamoDB

**User Story:** As a system operator, I want analysis results cached in DynamoDB, so that repeated requests do not re-invoke the LLM unnecessarily.

#### Acceptance Criteria

1. WHEN the agent completes an analysis successfully, THE System SHALL persist the result in DynamoDB with PK `USER#{userId}` and SK `ANALYSIS#{date}#{analysisId}`.
2. THE Cache_Analysis record SHALL contain: impactScore, impactLevel, correlations (list), insights (Bilingual_Insights map with keys `en` and `pt-BR`, parallel lists of equal length), period (map with startDate/endDate), analyzedAt (ISO timestamp), model (string), tokensUsed (int), and TTL (epoch seconds).
3. WHEN the Backend_Handler checks for cache, THE System SHALL query for the most recent ANALYSIS record for the user where the period matches and the analyzedAt is less than 24 hours old.
4. THE `forceRefresh=true` parameter SHALL bypass cache and force a new agent invocation.
5. THE Cache_Analysis records SHALL expire automatically after 7 days via DynamoDB TTL.
6. THE System SHALL support listing historical analyses for a user to show impact score evolution over time.

### Requirement 6: Frontend — Correlation Analysis Display

**User Story:** As a manager, I want to view the semantic correlation analysis results on the productivity page, so that I can understand the impact of Kiro on code deliveries.

#### Acceptance Criteria

1. THE Productivity_Dashboard SHALL display the impactScore with a visual indicator (progress bar + impactLevel label) and the date of the last analysis.
2. THE Productivity_Dashboard SHALL display the list of correlations found by the agent, showing: prompt summary, associated commit/PR, and confidence score.
3. THE Productivity_Dashboard SHALL display the agent's insights for the user's active locale, resolved via `useI18n()`, by selecting `insights[activeLocale]` from the response. THE Productivity_Dashboard SHALL fall back to `insights.en` when the active locale is not present in the map.
4. THE Productivity_Dashboard SHALL provide a "Refresh Analysis" button that invokes the endpoint with forceRefresh=true and shows a loading state during processing.
5. WHEN the user has no Git mapping configured, THE Productivity_Dashboard SHALL display a message directing them to the settings page, resolved by mapping the response `status` slug to a translation key under `productivity.correlation.status.*`.
6. WHEN analysis is in progress, THE Productivity_Dashboard SHALL display a loading state with an informative message.
7. THE Productivity_Dashboard SHALL use exclusively Cloudscape Design System components.

### Requirement 7: Legacy Code Removal

**User Story:** As a system developer, I want to remove the legacy sync/correlation code from PR #15 that is replaced by the agent approach.

#### Acceptance Criteria

1. THE System SHALL remove: git_sync_handler.py (ETL), correlation_engine.py, GitSyncStateMachine (Step Functions), sync-related endpoints, and non-GitHub connectors (GitLab, Bitbucket, CodeCommit base/factory).
2. THE System SHALL maintain: the user mapping model (Req 4), the Git Settings page for CRUD of mappings, and the git repo handler (simplified for GitHub-only).
3. THE System SHALL remove Step Functions and sync Lambda resources from template.yaml.
4. THE System SHALL ensure all remaining tests pass after removal, with no broken imports referencing removed code.

### Requirement 8: Bilingual Insights (English + pt-BR)

**User Story:** As a user of the productivity dashboard in either English or Brazilian Portuguese, I want the AI-generated insights to render in my active UI locale, so that I can read recommendations without context switching.

#### Acceptance Criteria

1. THE Strands_Agent SHALL produce insights in BOTH English (`en`) and Brazilian Portuguese (`pt-BR`) in a single LLM invocation, returning them as a Bilingual_Insights map.
2. THE Bilingual_Insights map SHALL be a JSON object of the shape `{ "en": string[], "pt-BR": string[] }`. Both keys SHALL be present in every successful and every fallback response.
3. THE two lists SHALL have IDENTICAL length AND parallel ordering: index `i` in `insights.en` SHALL convey the same insight as index `i` in `insights["pt-BR"]`.
4. EACH insight SHALL follow the format `"Title: description text"` in its respective locale, where Title is a short label (2-4 words) and the description is the detailed explanation. The Title may differ literally between locales (e.g., `"High Productivity"` vs `"Altíssima Produtividade"`) but SHALL refer to the same concept.
5. EACH insight SHALL address the developer in the second person — `"you"` / `"your"` in `en`, `"você"` / `"seu"` / `"sua"` in `pt-BR`. Third-person framings (`"the user"`, `"the developer"`, `"o usuário"`) SHALL NOT appear.
6. THE brand strings `"Kiro"` and `"Kiro Cost Analyzer"` SHALL NOT be translated and SHALL appear identically in both locale lists.
7. THE `correlations[].promptSummary` and `correlations[].gitActivity` fields SHALL remain a single English string each, regardless of the user's active locale. They are technical citations and not subject to translation.
8. THE Backend_Handler SHALL return both locale lists in every response — including cached responses, fallback responses (invalid JSON from agent), error responses, and the no-mapping response. THE Backend_Handler SHALL NOT branch on `Accept-Language` and SHALL NOT cache by locale.
9. THE Frontend SHALL select the list to render via `insights[activeLocale]` where `activeLocale` is the value returned by `useI18n()`. WHEN `insights[activeLocale]` is missing or empty, THE Frontend SHALL fall back to `insights.en`.
10. WHEN a Cache_Analysis record persisted before this requirement was implemented (legacy shape: `insights: string[]`) is read, THE Backend_Handler SHALL coerce it on read to `{ "en": [], "pt-BR": <legacy list> }` so the response contract holds without requiring a backfill. The legacy entry expires naturally via the existing 7-day TTL.
