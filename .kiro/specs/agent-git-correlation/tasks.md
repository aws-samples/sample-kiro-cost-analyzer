# Implementation Plan: Git-Kiro Semantic Correlation — Fix Broken Agent Wiring

## Overview

The agent code exists but is broken — tools aren't wired as proper `@tool` decorated functions, the entrypoint pre-fetches empty data instead of letting the agent use tools autonomously, and the backend handler doesn't pass the GitHub token in the payload. This plan rewrites the existing files to match the Strands Agents SDK patterns defined in the design document.

## Tasks

- [x] 1. Rewrite Strands tools as proper @tool decorated functions
  - [x] 1.1 Rewrite `agent/app/GitCorrelationAgent/tools/kiro_data.py` as a @tool function
    - Replace the current Lambda-style handler with a `build_kiro_tool(table_name)` factory that returns a `@tool` decorated `get_kiro_usage` function
    - The tool function accepts `user_id: str`, `start_date: str`, `end_date: str` parameters
    - Uses `AnalyticsRepository` internally to query DynamoDB
    - Returns dict with keys: `prompts` (list), `dailyStats` (list), `categoryDistribution` (list)
    - Preserves the `_truncate` helper (max 500 chars per prompt)
    - Preserves input validation logic (returns structured error dict on missing params)
    - The factory pattern allows injecting `table_name` from the environment at agent construction time
    - _Requirements: 1.1, 1.2, 1.4_

  - [x] 1.2 Rewrite `agent/app/GitCorrelationAgent/tools/github_tool.py` as a @tool function
    - Replace the current schema-only module with a `build_github_tool(token)` factory that returns a `@tool` decorated `get_github_activity` function
    - The tool function accepts `owner: str`, `repo: str`, `author: str`, `since: str` parameters
    - Token is captured via closure from the factory (not passed as a tool parameter by the LLM)
    - Calls GitHub REST API: `GET /repos/{owner}/{repo}/commits` (filtered by author, since) and `GET /repos/{owner}/{repo}/pulls` (filtered by state=all)
    - Returns dict with keys: `commits` (list of {sha, message, date}) and `pull_requests` (list of {number, title, state, created_at})
    - Handles HTTP 429 → returns `{"error": "GITHUB_RATE_LIMIT", "retryable": true}`
    - Handles HTTP 401/403 → returns `{"error": "GITHUB_AUTH_FAILED", "retryable": false}`
    - Limits: max 100 commits, max 50 PRs per call
    - _Requirements: 1.1, 1.3, 1.5, 1.6_

  - [x] 1.3 Update `agent/app/GitCorrelationAgent/tools/__init__.py`
    - Export `build_kiro_tool` and `build_github_tool` factory functions
    - _Requirements: 1.1_

- [x] 2. Rewrite agent entrypoint (`main.py`) with autonomous tool orchestration
  - [x] 2.1 Rewrite `agent/app/GitCorrelationAgent/main.py`
    - Use `@app.entrypoint` pattern from `bedrock_agentcore.runtime.BedrockAgentCoreApp`
    - Extract from payload: userId, startDate, endDate, gitUsername, repos, token
    - Build tools using factories: `build_kiro_tool(os.environ["ANALYTICS_TABLE"])` and `build_github_tool(token)`
    - Create agent: `Agent(model=BedrockModel(...), tools=[kiro_tool, github_tool], system_prompt=SYSTEM_PROMPT)`
    - Build a user prompt describing the analysis task (user, period, repos to check) — do NOT pre-fetch data
    - Let the agent autonomously call tools and produce analysis
    - Parse agent output with `parse_agent_output` (handle JSON in code fences)
    - Return fallback response (impactScore=null, error insight) if JSON parsing fails
    - Return result as `json.dumps(analysis)`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x]* 2.2 Write property tests for `parse_agent_output`
    - **Property 4: Agent Output JSON Parsing** — valid JSON (plain and code-fenced) is extracted correctly
    - **Property 5: Fallback on Invalid JSON** — non-JSON strings cause fallback response
    - **Property 6: Handler Returns Valid JSON** — entrypoint always returns parseable JSON string
    - **Validates: Requirements 2.5, 2.6, 2.7**

- [x] 3. Update system prompt to instruct tool usage
  - [x] 3.1 Rewrite `agent/app/GitCorrelationAgent/prompts.py`
    - Update SYSTEM_PROMPT to explicitly instruct the agent to CALL its tools:
      1. Call `get_kiro_usage` to fetch prompts and daily stats
      2. Call `get_github_activity` for each repository
      3. Compare content semantically
      4. Calculate impact score and generate insights
    - Add `impactLevel` thresholds: 0-25=low, 26-50=moderate, 51-75=high, 76-100=veryHigh
    - Instruct output as ONLY JSON (no markdown wrapping, no explanation)
    - Keep OUTPUT_SCHEMA dict for reference/validation
    - Add `build_user_prompt(user_id, start_date, end_date, git_username, repos)` function that describes the task and lists repos for the agent to query
    - _Requirements: 2.3, 2.5_

- [x] 4. Checkpoint — Agent code is internally consistent
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Update backend handler to pass token in payload
  - [x] 5.1 Update `backend/handlers/agent_correlation_handler.py`
    - In `_invoke_agent`, fetch GitHub token from SSM at path `/kiro-cost-analyzer/git-tokens/{userId}`
    - Add `token` field to the AgentCore invocation payload
    - Handle `ParameterNotFound` from SSM — return 200 with message directing user to configure token
    - Keep existing cache logic, error handling, and response formatting
    - _Requirements: 3.3, 3.4, 3.5, 3.6_

  - [x]* 5.2 Write property tests for handler error resilience and response contract
    - **Property 8: Error Resilience** — any exception during agent invocation returns 503
    - **Property 9: Response Contract Completeness** — all required keys present in response
    - **Validates: Requirements 3.6, 3.8**

- [x] 6. Update tests to match new implementation
  - [x] 6.1 Rewrite `tests/test_kiro_data_tool.py`
    - Test the `build_kiro_tool` factory returns a callable tool
    - Test the tool function with mocked AnalyticsRepository
    - Preserve existing test cases: truncation, validation, user not found, successful response
    - Add test for tool being callable by Strands (has correct signature and docstring)
    - _Requirements: 1.2, 1.4_

  - [x]* 6.2 Write property test for prompt truncation
    - **Property 1: Prompt Truncation Invariant** — output never exceeds 500 chars, strings ≤500 unchanged
    - **Validates: Requirements 1.4**

  - [x] 6.3 Create `tests/test_github_tool.py`
    - Test `build_github_tool` factory returns a callable tool
    - Test successful response parsing (commits + PRs structure)
    - Test HTTP 429 handling returns structured rate limit error
    - Test HTTP 401/403 handling returns auth failure error
    - Test max limits (100 commits, 50 PRs)
    - Mock `requests.get` for GitHub API calls
    - _Requirements: 1.3, 1.5, 1.6_

  - [x]* 6.4 Write property test for GitHub tool output structure
    - **Property 3: GitHub Tool Output Structure** — valid API responses produce correct output keys/types
    - **Validates: Requirements 1.3**

  - [x] 6.5 Update `tests/test_agent_correlation_handler.py`
    - Update mock for `_invoke_agent` to account for SSM token fetch
    - Add test for SSM `ParameterNotFound` returning message to configure token
    - Verify token is included in the payload passed to AgentCore
    - Keep existing tests: cache behavior, force refresh, timeout, no mapping
    - _Requirements: 3.3, 3.4, 3.6_

  - [x] 6.6 Update `tests/test_analysis_cache.py`
    - Verify tests still pass with current AnalyticsRepository implementation
    - No major changes expected — cache logic is unchanged
    - _Requirements: 5.1, 5.3, 5.5_

- [x] 7. Checkpoint — All tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Deploy and validate end-to-end
  - [x] 8.1 Deploy agent to AgentCore
    - Run `agentcore configure` to update local config if needed
    - Run `agentcore launch` to deploy the rewritten agent code
    - Verify deployment succeeds and agent is reachable
    - _Requirements: 1.1, 1.7_

  - [x] 8.2 Deploy backend via SAM
    - Run `sam build && sam deploy` to update the Lambda with the new handler code
    - Verify the AGENT_RUNTIME_ARN env var is correctly set in template.yaml
    - _Requirements: 3.5_

  - [x] 8.3 Validate end-to-end flow
    - Invoke the correlation endpoint for a test user with a valid Git mapping and token
    - Verify the agent calls both tools and returns structured analysis
    - Verify cache is populated after first invocation
    - Verify second invocation returns cached result
    - _Requirements: 2.3, 3.2, 5.1_

- [x] 9. Frontend adjustments (if needed)
  - [x] 9.1 Verify `ProductivityPage.tsx` works with the updated API response
    - Confirm the response contract matches what the frontend expects (CorrelationAnalysis type)
    - Verify loading state, error handling, and cached indicator display correctly
    - Fix any minor issues (e.g., field name mismatches)
    - _Requirements: 6.1, 6.2, 6.4, 6.5, 6.6_

- [x] 10. Final checkpoint — Full system validation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Bilingual Insights — generate insights in English and pt-BR (Requirement 8)
  - [x] 11.1 Update agent system prompt to emit bilingual insights
    - In `agent/app/GitCorrelationAgent/prompts.py`, replace the single pt-BR `insights` array in the SYSTEM_PROMPT and OUTPUT_SCHEMA with the bilingual map shape `{ "en": [...], "pt-BR": [...] }`
    - Update the rules block to require: both keys always present, equal-length arrays, parallel ordering (index `i` is the same insight in both languages), `"Title: description"` format in each language, second-person addressing per language, brand strings (`Kiro`, `Kiro Cost Analyzer`) NEVER translated
    - Update `correlations[].promptSummary` and `correlations[].gitActivity` instructions to require English (verbatim/summarized in English regardless of original prompt language)
    - Adjust `build_user_prompt` to make the bilingual contract explicit to the agent
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 11.2 Update agent fallback responses to bilingual shape
    - In `agent/app/GitCorrelationAgent/main.py`, replace the single-list fallback (used when JSON parsing fails) with `{ "en": ["Analysis could not be processed. Please try again."], "pt-BR": ["Não foi possível processar a análise. Tente novamente."] }`
    - Apply the same change to any other hardcoded fallback insight lists in the entrypoint
    - _Requirements: 2.6, 8.8_

  - [ ]* 11.3 Property tests for bilingual shape
    - Update P4/P5/P6 tests in `tests/test_agent_main.py` to assert the bilingual map shape (both keys, equal length)
    - Add new test for **Property 12: Bilingual Insights Parity** — Hypothesis-generated analyses, assert `len(insights["en"]) == len(insights["pt-BR"])` and brand-string invariance
    - _Validates: Requirements 2.5, 2.6, 8.2, 8.3, 8.6_

- [x] 12. Backend response contract — bilingual insights and status slugs
  - [x] 12.1 Update `_format_response` in `backend/handlers/agent_correlation_handler.py`
    - Output `insights` as the bilingual map. If the agent ever returns a legacy list, coerce it to `{ "en": [], "pt-BR": <legacy list> }` before returning (keeps `_format_response` total)
    - Replace any human-readable `message` prose with a stable English `status` slug from `CorrelationStatusSlug`
    - Drop the `message` field from the response body (keep it only in structured logs for operator context)
    - _Requirements: 3.8, 3.9, 8.2, 8.8_

  - [x] 12.2 Update non-success branches to use status slugs
    - "No Git mapping" → `status="GIT_MAPPING_MISSING"`, `insights = { en: [], "pt-BR": [] }`
    - "SSM token not found" → `status="GITHUB_TOKEN_MISSING"`
    - GitHub auth/rate-limit failures surfaced from the agent → `status="GITHUB_AUTH_FAILED"` / `GITHUB_RATE_LIMIT`
    - Insufficient data (agent returned `impactScore=null` with reason) → `status="INSUFFICIENT_DATA"`
    - AgentCore timeout → `status="AGENT_TIMEOUT"` (HTTP 503)
    - Generic agent failure → `status="AGENT_ERROR"` (HTTP 503)
    - _Requirements: 3.6, 3.9_

  - [x] 12.3 Implement legacy cache coercion in `AnalyticsRepository.get_latest_analysis`
    - Detect items where `insights` is a list (legacy shape) and coerce on read to `{ "en": [], "pt-BR": <list> }`
    - Do NOT mutate the underlying DynamoDB item — coercion is read-only and one-way
    - Add a structured-logger line at INFO level when a legacy item is coerced (to track migration progress organically via the 7-day TTL)
    - _Requirements: 8.10_

  - [ ]* 12.4 Property tests for backend response and legacy coercion
    - Update `tests/test_agent_correlation_handler.py` for **Property 9** (bilingual response contract)
    - Add **Property 13: Legacy Cache Coercion** test in `tests/test_analytics_repository.py`
    - Add **Property 14: Status Slug Vocabulary** test for non-success branches
    - _Validates: Requirements 3.8, 3.9, 8.2, 8.10_

- [x] 13. Frontend — render insights for the active locale
  - [x] 13.1 Update TypeScript types in `frontend/src/types/index.ts`
    - Change `CorrelationAnalysis.insights` from `string[]` to the bilingual map type with keys `en` and `'pt-BR'`
    - Replace optional `message?: string` with optional `status?: CorrelationStatusSlug` (string-literal union mirroring the backend)
    - Add the `CorrelationStatusSlug` type to the same file
    - _Requirements: 3.8, 6.3_

  - [x] 13.2 Update `frontend/src/pages/UserPage.tsx` insight rendering
    - Read `useI18n()` to obtain the active locale (already used elsewhere in the page)
    - Replace `analysis.insights` iteration with `analysis.insights[activeLocale] ?? analysis.insights.en ?? []`
    - Keep the existing emoji-strip and "Title: description" parsing — that logic is locale-agnostic
    - _Requirements: 6.3, 8.9_

  - [x] 13.3 Add the `productivity.correlation.status.*` translation keys
    - In `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json`, add keys for: `gitMappingMissing`, `githubTokenMissing`, `githubAuthFailed`, `githubRateLimit`, `insufficientData`, `agentTimeout`, `agentError`
    - Keep keys alphabetically sorted to satisfy `scripts/check-locales.ts`
    - Provide concise, actionable copy in each language (≤ 140 chars) — directing the user to the next action (e.g., "Configure your GitHub mapping in Settings.")
    - _Requirements: 3.9, 6.5_

  - [x] 13.4 Update `UserPage.tsx` to render slug-based alerts
    - Build a `slugToTranslationKey` map (`GIT_MAPPING_MISSING` → `productivity.correlation.status.gitMappingMissing`, etc.)
    - Replace any direct `analysis.message` rendering with `t(slugToTranslationKey[analysis.status])` when `status` is present
    - Display Cloudscape `Alert` of the appropriate severity (info / warning / error) per slug
    - _Requirements: 6.5_

  - [ ]* 13.5 Frontend tests
    - Add a Vitest test for `UserPage.tsx` that mocks two responses (one with `pt-BR` active, one with `en` active) and asserts the rendered insights match the active locale's list
    - Add a Vitest test that mocks each `status` slug and asserts the corresponding translated Alert renders
    - _Validates: Requirements 6.3, 6.5, 8.9_

- [x] 14. Final checkpoint — Bilingual feature end-to-end
  - Deploy agent (`agentcore launch`) and backend (`sam deploy`)
  - Trigger a fresh analysis for a test user in each locale and confirm the same `analyzedAt` timestamp serves both renderings without re-invoking the LLM
  - Trigger a `forceRefresh=true` analysis and confirm both lists in the new payload are non-empty and equal in length
  - Confirm a legacy cached analysis (pre-deploy) coerces correctly: `insights.en` is empty, `insights.pt-BR` retains the original list, and the frontend falls back to the pt-BR list when the active locale is `en` and `en` is empty (acceptable transitional state — TTL purges within 7 days)
  - Update `docs/changelog.md` with an entry under `Unreleased` describing bilingual insights and the slug-based status contract
  - _Requirements: 8.1, 8.2, 8.3, 8.8, 8.9, 8.10_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The existing code is being REWRITTEN, not created from scratch — file paths remain the same
- Legacy code removal (Requirement 7) is already done in this branch and is NOT included here
- The `template.yaml` already has `AGENT_RUNTIME_ARN` configured — no infra changes needed
- Property tests validate universal correctness properties from the design document
- The factory pattern (`build_kiro_tool`, `build_github_tool`) enables dependency injection for testing and closure over runtime values (token, table name)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["5.1"] },
    { "id": 6, "tasks": ["5.2", "6.1", "6.3", "6.6"] },
    { "id": 7, "tasks": ["6.2", "6.4", "6.5"] },
    { "id": 8, "tasks": ["8.1", "8.2"] },
    { "id": 9, "tasks": ["8.3"] },
    { "id": 10, "tasks": ["9.1"] },
    { "id": 11, "tasks": ["11.1", "11.2"] },
    { "id": 12, "tasks": ["11.3"] },
    { "id": 13, "tasks": ["12.1", "12.3"] },
    { "id": 14, "tasks": ["12.2"] },
    { "id": 15, "tasks": ["12.4"] },
    { "id": 16, "tasks": ["13.1", "13.3"] },
    { "id": 17, "tasks": ["13.2"] },
    { "id": 18, "tasks": ["13.4"] },
    { "id": 19, "tasks": ["13.5"] }
  ]
}
```
