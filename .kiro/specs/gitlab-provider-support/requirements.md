# Requirements Document

## Introduction

This feature adds GitLab as a second supported Git provider in the Kiro Cost Analyzer (KCA), alongside the existing GitHub integration. Administrators will be able to register GitLab repositories, map Kiro users to GitLab usernames, and run the on-demand Kiro-to-Git correlation analysis against GitLab activity (commits and merge requests).

The target platform is **GitLab Community Edition (CE), self-hosted**. The integration uses the GitLab REST API v4 directly, which is fully available on CE. GitLab's official MCP server (part of GitLab Duo) was evaluated and rejected because it requires Premium/Ultimate (EE) licensing and the cloud AI Gateway, neither of which is available on CE; community MCP servers were rejected because embedding a Node.js MCP subprocess in the AgentCore container adds packaging complexity and a large tool surface for only two required API calls. This evaluation is recorded here as context and will be carried into the design document as a documented design decision.

The feature preserves the existing on-demand analysis model (no sync pipeline, no webhooks) and the existing normalized activity contract consumed by the correlation agent. GitLab merge requests are normalized into the existing `pull_requests` field of that contract.

**Documented decision — status slug strategy:** provider-specific status slugs are added for GitLab (`GITLAB_TOKEN_MISSING`, `GITLAB_AUTH_FAILED`, `GITLAB_RATE_LIMIT`) rather than migrating the existing `GITHUB_*` slugs to neutral names. Rationale: the existing `GITHUB_*` slugs remain untouched (no breaking change to the frontend contract or cached analyses), and provider-specific slugs let the UI show messages that name the correct provider and settings action. This decision is open for review during the requirements phase.

**Documented decision — one Git username per provider, enforced structurally:** a Kiro user holds at most one Git username per provider, and that limit is enforced by the shape of the DynamoDB sort key rather than by application-level validation. The Mapping_Sort_Key becomes `GITMAP#{provider}`, with `gitUsername` demoted from the sort key to an ordinary item attribute.

Rationale: a structural constraint cannot be violated. Application-level enforcement would be a check-then-write, which is racy under concurrent admin requests, and it would still leave the read path needing a tie-break for data written before the check existed. Adding future providers stays purely additive under this shape — `provider` remains the first discriminator in the sort key, so registering `bitbucket` later writes `GITMAP#bitbucket` and touches no existing item; the migration cost is one-time (moving off the previous key), not per-provider.

Accepted limitation: this shape cannot express two identities for the same provider — a user with different usernames on a self-hosted GitLab CE instance and on gitlab.com, or a CodeCommit user with several IAM identities. That is acceptable because this feature is scoped to a single self-hosted GitLab CE instance, and GitLab.com SaaS-specific features, Bitbucket, and CodeCommit are out of scope (see below). A `GITMAP#{provider}#{instanceHost}` variant was considered and rejected for now: it would add an instance field to the mapping form and create a consistency question against the host already stored in the repository configuration. If multi-identity is ever needed, the migration is over mapping items only, which are few and admin-recreatable.

Consequence: the mapping delete route loses its trailing username segment, becoming `DELETE /api/git/mappings/{userId}/{provider}`. This is a breaking change to the API surface, accepted because the endpoint is admin-only and its sole consumer is this project's own SPA.

**Out of scope:** Bitbucket and CodeCommit providers, GitLab.com SaaS-specific features, GitLab EE/Duo features, webhook-based or scheduled sync pipelines, GitLab OAuth flows (personal access tokens only), and code review/approval analytics.

## Glossary

- **KCA**: Kiro Cost Analyzer — the serverless application this feature extends.
- **Git_Repo_Handler**: Backend Lambda handler for Git repository configuration CRUD (`backend/handlers/git_repo_handler.py`).
- **Git_Mapping_Handler**: Backend Lambda handler for user-to-Git-username mapping CRUD (`backend/handlers/git_mapping_handler.py`).
- **Git_Mapping_Repository**: The shared data-access layer that reads and writes Git integration items in DynamoDB (`layers/shared/git_shared/git_repository.py`).
- **Mapping_Sort_Key**: The DynamoDB sort key of a user-to-Git mapping item, `GITMAP#{provider}`, under partition key `USER#{userId}`. Its shape is what makes more than one mapping per pair of Kiro userId and provider unrepresentable.
- **Legacy_Mapping_Sort_Key**: The mapping sort key shape used before this feature, `GITMAP#{provider}#{gitUsername}`.
- **Mapping_Migrator**: The component that converts stored mapping items from the Legacy_Mapping_Sort_Key to the Mapping_Sort_Key.
- **Correlation_Handler**: Backend Lambda handler for `GET /api/productivity/{userId}/correlation` (`backend/handlers/agent_correlation_handler.py`).
- **Correlation_Worker**: Async Lambda that invokes the AgentCore runtime and persists results (`backend/handlers/correlation_worker.py`).
- **Correlation_Agent**: The Strands agent running on Bedrock AgentCore that orchestrates data fetching and semantic analysis (`agent/app/GitCorrelationAgent/`).
- **GitLab_Tool**: The new Strands tool that fetches commits and merge requests from a GitLab instance via the REST API v4.
- **GitHub_Tool**: The existing Strands tool that fetches commits and pull requests from GitHub (`github_tool.py`).
- **URL_Parser**: The backend logic that derives provider-specific API parameters (instance base URL, project namespace path) from a configured repository URL.
- **Token_Store**: The SSM Parameter Store SecureString parameters under `/kiro-cost-analyzer/git-tokens/` that hold Git provider access tokens.
- **Frontend**: The React + TypeScript SPA (`frontend/`).
- **GitLab_Instance**: A self-hosted GitLab Community Edition server reachable at an arbitrary hostname over http or https.
- **Namespace_Path**: The full GitLab project path including groups and subgroups (e.g., `group/subgroup/project`).
- **Personal_Access_Token**: A GitLab personal access token with API read scope, sent via the `PRIVATE-TOKEN` HTTP header.
- **Normalized_Activity_Contract**: The provider-neutral activity shape returned by Git tools to the Correlation_Agent: `{commits: [{sha, message, date}], pull_requests: [{number, title, state, created_at}]}`.
- **Status_Slug**: A stable English machine code returned by the backend on non-success branches of the correlation API, mapped by the Frontend to a translation key (e.g., `GITHUB_TOKEN_MISSING`).
- **Locale_Catalog**: The translation files `frontend/src/locales/en.json` and `frontend/src/locales/pt-BR.json`, which must keep key parity.

## Requirements

### Requirement 1: Register GitLab Repositories

**User Story:** As an administrator, I want to register self-hosted GitLab repositories with an access token, so that KCA can analyze Git activity from those repositories.

#### Acceptance Criteria

1. WHEN a repository creation request contains provider `gitlab` with a non-empty name, a valid URL, and an access token between 10 and 500 characters, THE Git_Repo_Handler SHALL persist the repository configuration and return HTTP 201.
2. THE Git_Repo_Handler SHALL accept repository URLs with any hostname and either the `http` or `https` scheme, including non-standard ports.
3. WHEN a repository creation request contains a provider outside the set {`github`, `gitlab`}, THE Git_Repo_Handler SHALL return HTTP 400 with error `ValidationError` and a message listing the supported providers.
4. WHEN a GitLab repository configuration is created, THE Git_Repo_Handler SHALL store the access token as an SSM SecureString parameter scoped to that repository configuration.
5. WHEN listing repositories, THE Git_Repo_Handler SHALL return the `provider` field for each repository and SHALL exclude token values and SSM parameter paths from the response.
6. WHEN a GitLab repository configuration is deleted, THE Git_Repo_Handler SHALL delete both the DynamoDB configuration item and the associated SSM token parameter.

### Requirement 2: Map Kiro Users to GitLab Usernames

**User Story:** As an administrator, I want to map a Kiro user to a GitLab username, so that correlation analysis attributes GitLab commits and merge requests to the correct Kiro user.

#### Acceptance Criteria

1. WHEN a mapping creation request contains provider `gitlab`, an existing Kiro userId, and a non-empty gitUsername, THE Git_Mapping_Handler SHALL persist the mapping and return HTTP 201.
2. WHEN a mapping creation request contains a provider outside the set {`github`, `gitlab`}, THE Git_Mapping_Handler SHALL return HTTP 400 with error `ValidationError` and a message listing the supported providers.
3. THE Git_Mapping_Handler SHALL allow a single Kiro user to hold one `github` mapping and one `gitlab` mapping simultaneously, and THE Mapping_Sort_Key SHALL keep the two mappings on distinct items so that neither can overwrite the other.
4. WHEN listing mappings for a user, THE Git_Mapping_Handler SHALL return the `provider` field for each mapping.
5. THE Git_Mapping_Repository SHALL store each user-to-Git mapping under THE Mapping_Sort_Key `GITMAP#{provider}`, carrying `gitUsername` as an item attribute rather than as part of the sort key.
6. FOR ALL pairs of Kiro userId and provider, THE Git_Mapping_Repository SHALL hold at most one mapping item for that pair.
7. WHEN a mapping creation request names a provider for which the Kiro user already holds a mapping, THE Git_Mapping_Handler SHALL replace the stored mapping with the submitted gitUsername and SHALL return HTTP 201 with a body carrying the userId, the provider, the newly stored gitUsername, and an indication that a previously stored mapping for that provider was replaced.
8. WHEN a mapping deletion request is received at `DELETE /api/git/mappings/{userId}/{provider}`, THE Git_Mapping_Handler SHALL delete the mapping held by that Kiro user for that provider and SHALL return a success response naming the userId and provider.
9. WHERE no mapping exists for the requested pair of Kiro userId and provider, THE Git_Mapping_Handler SHALL return the same success response as a deletion that removed an item, so that repeated deletion requests are idempotent.
10. WHEN all mappings for a given provider are requested, THE Git_Mapping_Repository SHALL return every stored mapping whose `provider` value equals the requested provider and SHALL return no mapping belonging to another provider.
11. THE KCA SHALL expose mapping deletion at the path `/api/git/mappings/{userId}/{provider}`, taking the Kiro userId and the provider as its only path parameters.

### Requirement 3: Provider-Aware Token Resolution

**User Story:** As an administrator, I want each analysis to use the token that belongs to the repository being analyzed, so that adding a GitLab token does not break existing GitHub analyses (and vice versa).

#### Acceptance Criteria

1. WHEN the correlation flow requires an access token for a repository, THE KCA SHALL resolve the SSM token parameter associated with that specific repository configuration.
2. WHEN tokens for both `github` and `gitlab` repositories exist in the Token_Store, THE KCA SHALL select, for each repository under analysis, the token stored for that repository configuration.
3. IF the token parameter for a repository included in the analysis is absent from the Token_Store, THEN THE Correlation_Handler SHALL return the token-missing Status_Slug for that repository's provider (`GITHUB_TOKEN_MISSING` or `GITLAB_TOKEN_MISSING`).
4. WHEN the Correlation_Agent fetches a token at runtime, THE Correlation_Agent SHALL read the SSM parameter identified for the specific repository, using a repository-scoped identifier received in the invocation payload rather than the token value itself.

### Requirement 4: GitLab Repository URL Parsing

**User Story:** As an administrator, I want to register GitLab repositories using their web URLs (including subgroup paths on self-hosted instances), so that KCA derives the correct API parameters without manual configuration.

#### Acceptance Criteria

1. WHEN a GitLab repository URL is parsed, THE URL_Parser SHALL extract the instance base URL (scheme, hostname, and port) and the full Namespace_Path.
2. WHEN a GitLab repository URL contains one or more subgroups (e.g., `https://gitlab.example.com/group/subgroup/project`), THE URL_Parser SHALL preserve the complete Namespace_Path including all subgroup segments.
3. WHEN a GitLab repository URL ends with a `.git` suffix or trailing slash, THE URL_Parser SHALL strip the suffix before deriving the Namespace_Path.
4. WHEN the correlation flow builds GitLab API requests, THE KCA SHALL identify the project using the URL-encoded Namespace_Path.
5. IF a configured GitLab repository URL cannot be parsed into a base URL and Namespace_Path, THEN THE Correlation_Handler SHALL exclude that repository from the analysis and log a structured warning identifying the repository.
6. FOR ALL valid GitLab repository URLs, parsing the URL and reconstructing it from the extracted base URL and Namespace_Path SHALL produce a URL equivalent to the normalized input (round-trip property).

### Requirement 5: GitLab Activity Retrieval

**User Story:** As a Kiro user, I want the correlation agent to fetch my commits and merge requests from GitLab, so that my GitLab activity is included in the productivity analysis.

#### Acceptance Criteria

1. WHEN the Correlation_Agent needs activity for a GitLab repository, THE GitLab_Tool SHALL fetch commits from the GitLab REST API v4 repository commits endpoint of the configured GitLab_Instance.
2. WHEN the Correlation_Agent needs merge requests for a GitLab repository, THE GitLab_Tool SHALL fetch merge requests from the GitLab REST API v4 merge requests endpoint of the configured GitLab_Instance.
3. THE GitLab_Tool SHALL authenticate every GitLab API request using the `PRIVATE-TOKEN` header carrying the Personal_Access_Token.
4. WHEN fetching commits, THE GitLab_Tool SHALL return only commits authored by the mapped GitLab user, applying client-side filtering on commit author fields when the server-side author filter does not restrict the result set.
5. WHEN fetching merge requests, THE GitLab_Tool SHALL filter merge requests by the mapped GitLab username using the author username query parameter.
6. WHEN fetching activity, THE GitLab_Tool SHALL restrict results to activity on or after the analysis start date.
7. THE GitLab_Tool SHALL return at most 100 commits and at most 50 merge requests per repository.
8. THE GitLab_Tool SHALL apply a request timeout of 30 seconds to each GitLab API call.

### Requirement 6: Normalized Activity Contract Stability

**User Story:** As a maintainer, I want both Git tools to return the same normalized activity shape, so that the agent's analysis prompt and output contract remain stable regardless of provider.

#### Acceptance Criteria

1. FOR ALL supported providers, THE Correlation_Agent's Git tools SHALL return activity matching the Normalized_Activity_Contract.
2. WHEN the GitLab_Tool normalizes a commit, THE GitLab_Tool SHALL map the commit identifier to `sha`, the commit message to `message`, and the authored date to `date`.
3. WHEN the GitLab_Tool normalizes a merge request, THE GitLab_Tool SHALL place it in the `pull_requests` field, mapping the merge request iid to `number`, the title to `title`, the GitLab state value to `state`, and the creation timestamp to `created_at`.
4. THE GitHub_Tool SHALL retain its existing output shape unchanged.

### Requirement 7: Provider-Aware Correlation Flow

**User Story:** As a Kiro user, I want the correlation analysis to work across my GitHub and GitLab repositories in a single run, so that my full Git activity is analyzed regardless of where each repository is hosted.

#### Acceptance Criteria

1. WHEN the Correlation_Handler prepares an analysis, THE Correlation_Handler SHALL build, for each configured repository, a repository descriptor containing the provider, the provider-specific location parameters, and a repository-scoped token identifier.
2. WHEN resolving the Git username for a repository, THE Correlation_Handler SHALL use the user mapping whose provider matches that repository's provider.
3. IF a repository's provider has no corresponding user mapping, THEN THE Correlation_Handler SHALL exclude that repository from the analysis and log a structured warning identifying the repository and provider.
4. IF the user has no Git mappings for any provider, THEN THE Correlation_Handler SHALL return the `GIT_MAPPING_MISSING` Status_Slug.
5. WHEN dispatching the analysis, THE Correlation_Worker SHALL forward the per-repository descriptors, including provider and location parameters, to the Correlation_Agent invocation payload.
6. WHEN the Correlation_Agent processes a repository descriptor, THE Correlation_Agent SHALL invoke the Git tool matching that repository's provider.
7. WHEN building agent prompts, THE Correlation_Agent SHALL describe each repository with provider-appropriate terminology, referring to GitLab items as merge requests and GitHub items as pull requests.
8. FOR ALL Kiro users and providers, THE Correlation_Handler SHALL resolve at most one gitUsername for a repository's provider, relying on the at-most-one-mapping-per-pair invariant of Requirement 2.6 rather than on a tie-break among mappings of the same provider.
9. IF more than one mapping is present for the same pair of Kiro userId and provider, THEN THE Correlation_Handler SHALL select the mapping with the most recent `createdAt` value, so that username resolution stays deterministic and independent of the order in which mappings are read.

### Requirement 8: GitLab Error Handling and Status Slugs

**User Story:** As a Kiro user, I want clear, actionable feedback when the GitLab integration fails, so that I know whether to fix my token, wait for a rate limit, or retry.

#### Acceptance Criteria

1. WHEN a GitLab API request returns HTTP 401 or 403, THE GitLab_Tool SHALL return the error code `GITLAB_AUTH_FAILED` marked as non-retryable.
2. WHEN a GitLab API request returns HTTP 429, THE GitLab_Tool SHALL return the error code `GITLAB_RATE_LIMIT` marked as retryable.
3. IF a GitLab API request fails at the network level, THEN THE GitLab_Tool SHALL return the error code `GITLAB_REQUEST_FAILED` marked as retryable.
4. WHEN the correlation API surfaces a GitLab-related non-success condition, THE Correlation_Handler SHALL emit one of the Status_Slugs `GITLAB_TOKEN_MISSING`, `GITLAB_AUTH_FAILED`, or `GITLAB_RATE_LIMIT`.
5. THE KCA backend SHALL retain the existing `GITHUB_*` Status_Slugs unchanged.
6. THE KCA backend SHALL emit English-only human-readable text in structured logs and SHALL surface only stable Status_Slugs to API clients on non-success branches.

### Requirement 9: Frontend Provider Support

**User Story:** As an administrator, I want to select GitLab in the repository and mapping forms and see translated GitLab status messages, so that I can manage the GitLab integration entirely from the UI in my language.

#### Acceptance Criteria

1. WHEN the repository creation form is displayed, THE Frontend SHALL offer both `github` and `gitlab` as provider options using the existing `git.provider.*` labels.
2. WHEN the user mapping form is displayed, THE Frontend SHALL offer both `github` and `gitlab` as provider options using the existing `git.provider.*` labels.
3. WHEN the correlation API returns one of the Status_Slugs `GITLAB_TOKEN_MISSING`, `GITLAB_AUTH_FAILED`, or `GITLAB_RATE_LIMIT`, THE Frontend SHALL render the corresponding translated message in the active locale.
4. THE Frontend SHALL classify `GITLAB_TOKEN_MISSING` and `GITLAB_AUTH_FAILED` as non-retryable statuses that direct the user to the settings page, and `GITLAB_RATE_LIMIT` as a retryable status offering a refresh action.
5. WHEN new translation keys are added for GitLab statuses, THE Locale_Catalog SHALL contain each new key in both `en.json` and `pt-BR.json` with non-empty string values, preserving key parity.
6. WHEN the administrator triggers the delete action for a row of the mappings table, THE Frontend SHALL issue the deletion request using the Kiro userId and the provider of that row as the only path parameters.
7. WHEN the administrator submits the mapping form for a Kiro user and provider that already hold a mapping, THE Frontend SHALL display a message stating that the previously stored Git username for that provider was replaced by the submitted one.
8. WHEN new translation keys are added for mapping replacement or mapping deletion messages, THE Locale_Catalog SHALL contain each new key in both `en.json` and `pt-BR.json` with non-empty string values, preserving key parity.

### Requirement 10: GitLab CE Compatibility

**User Story:** As an administrator of a self-hosted GitLab CE instance, I want the integration to work without any Enterprise Edition or GitLab Duo features, so that KCA is usable in my environment.

#### Acceptance Criteria

1. THE GitLab_Tool SHALL use only GitLab REST API v4 endpoints that are available on GitLab Community Edition.
2. THE KCA SHALL operate against self-hosted GitLab_Instances without requiring GitLab Duo, the GitLab AI Gateway, or any Premium/Ultimate license feature.
3. WHERE a GitLab_Instance is served over plain `http`, THE GitLab_Tool SHALL complete API requests using the configured scheme.
4. THE GitLab_Tool SHALL read the GitLab instance base URL from the repository descriptor rather than a hardcoded hostname.

### Requirement 11: Migration of Existing User-to-Git Mappings

**User Story:** As an administrator, I want the mappings I have already registered to keep working after the mapping key change is deployed, so that correlation analysis continues without me re-entering every mapping by hand.

#### Acceptance Criteria

1. WHEN this feature is deployed to an environment holding mapping items stored under THE Legacy_Mapping_Sort_Key, THE KCA SHALL make each of those mappings retrievable under THE Mapping_Sort_Key without an administrator re-entering it.
2. WHERE the stored data holds more than one legacy mapping for the same pair of Kiro userId and provider, THE Mapping_Migrator SHALL retain the mapping whose `createdAt` value is the most recent and SHALL remove the others.
3. IF two legacy mappings for the same pair of Kiro userId and provider carry equal `createdAt` values, THEN THE Mapping_Migrator SHALL order the candidates by `gitUsername` in ascending lexicographic order and retain the first, so that the surviving mapping is determined by the stored data alone.
4. WHEN THE Mapping_Migrator retains a mapping, THE Mapping_Migrator SHALL preserve that mapping's `provider`, `gitUsername`, `createdAt`, and `createdBy` attribute values.
5. WHEN migration of a pair of Kiro userId and provider completes, THE Git_Mapping_Repository SHALL hold that pair's mapping only under THE Mapping_Sort_Key and SHALL hold no item for that pair under THE Legacy_Mapping_Sort_Key.
6. FOR ALL sets of stored mapping items, running THE Mapping_Migrator twice SHALL leave the stored mappings identical to the result of running it once (idempotence).
7. WHEN THE Mapping_Migrator processes the mappings of a Kiro user, THE Mapping_Migrator SHALL emit a structured log entry naming the userId, the provider, the retained gitUsername, and the number of discarded mappings.
8. IF THE Mapping_Migrator fails to migrate a mapping item, THEN THE Mapping_Migrator SHALL emit a structured log entry identifying the userId and provider and SHALL continue processing the remaining mapping items.
