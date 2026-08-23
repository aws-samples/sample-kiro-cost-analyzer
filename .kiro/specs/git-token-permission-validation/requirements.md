# Requirements — Git Token Permission Validation

A repository can be registered with a token that authenticates successfully but lacks the permissions the correlation agent actually needs. Today that failure is silent and only visible in AgentCore CloudWatch logs: a real incident on 2026-08-23 had `vsbatista/agentic-city` registered with a fine-grained PAT carrying only "Read access to administration and metadata". The repo showed `Token configured` (green) in Settings, the correlation ran without error, and the repository simply never appeared in any result. Diagnosing it required reading `/aws/bedrock-agentcore/runtimes/*` logs to find `GitHub auth failed on commits: repo_id=efa4ed67 status_code=403`.

This spec adds an explicit, user-triggered permission check that exercises the same provider API operations the correlation agent depends on, and reports per-operation results with actionable remediation.

## Glossary

- **Provider**: `github` or `gitlab` — the only two providers the correlation agent supports.
- **Check**: one probe of a single provider API operation the agent depends on. Three checks per provider (see Requirement 2).
- **Ad-hoc validation**: validating a token supplied in the request body, before it has been persisted. Used from the add/edit repository form.
- **Stored validation**: validating the token already persisted in SSM for a registered `repoId`. Used from the repositories table.
- **Check status slug**: a stable machine identifier for one check's outcome (`ok`, `unauthorized`, `forbidden`, `not_found`, `rate_limited`, `unreachable`, `error`). Not prose — the frontend maps it to a translated label.
- **Overall verdict**: `ok` (every check passed), `partial` (at least one passed and at least one did not), `failed` (no check passed).

## Requirement 1: Validate a token before it is saved

**User Story.** As an administrator entering a Git token, I want to confirm the token actually works before saving the repository, so I do not register a repository that will silently never correlate.

### Acceptance Criteria

1.1. THE system SHALL expose `POST /api/git/repos/validate-token` accepting a JSON body with `url`, `provider`, and `accessToken`.

1.2. WHEN the request body omits or empties any of `url`, `provider`, or `accessToken` THEN THE endpoint SHALL return HTTP 400 with `error: "ValidationError"` and SHALL NOT perform any outbound request.

1.3. WHEN `provider` is not `github` or `gitlab` THEN THE endpoint SHALL return HTTP 400 with `error: "ValidationError"`, because no other provider is supported by the correlation agent.

1.4. WHEN `url` cannot be parsed into the provider's location fields (owner/repo for GitHub; baseUrl/projectPath for GitLab) THEN THE endpoint SHALL return HTTP 400 with `error: "ValidationError"`.

1.5. THE endpoint SHALL be restricted to members of the `Admins` Cognito group, returning HTTP 403 otherwise, consistent with every other `/api/git/*` route.

1.6. THE endpoint SHALL NOT persist the supplied token anywhere — not in SSM, not in DynamoDB, not in logs.

## Requirement 2: Exercise the operations the correlation agent actually needs

**User Story.** As an administrator, I want the validation to test the same API calls the correlation agent makes, so a green result means correlation will genuinely work.

### Acceptance Criteria

2.1. THE validation SHALL perform exactly three checks per provider, in this order, each mapped to the agent operation it protects:

| Check id | GitHub operation | GitHub permission | GitLab operation | GitLab scope |
|---|---|---|---|---|
| `repo_access` | `GET /repos/{owner}/{repo}` | Metadata: Read | `GET /api/v4/projects/{encodedPath}` | `read_api` |
| `commits` | `GET /repos/{owner}/{repo}/commits` | Contents: Read | `GET /api/v4/projects/{encodedPath}/repository/commits` | `read_api` |
| `pull_requests` | `GET /repos/{owner}/{repo}/pulls` | Pull requests: Read | `GET /api/v4/projects/{encodedPath}/merge_requests` | `read_api` |

2.2. EACH check SHALL request at most one item (`per_page=1`) — the validation confirms authorization, not data volume.

2.3. EACH check SHALL be reported independently with its own status slug, so a token that reads metadata but not contents produces `repo_access: ok` alongside `commits: forbidden` — the exact signature of the incident this feature addresses.

2.4. THE response SHALL map each HTTP outcome to a status slug: 2xx → `ok`, 401 → `unauthorized`, 403 → `forbidden`, 404 → `not_found`, 429 → `rate_limited`, network failure or timeout → `unreachable`, any other status → `error`.

2.5. EACH check result SHALL carry the observed `httpStatus` when a response was received, and `null` when no response was obtained.

2.6. WHEN `repo_access` returns `unauthorized` THEN the remaining checks SHALL still run, so the user sees the complete picture in one round trip rather than fixing one permission at a time.

2.7. THE `commits` and `pull_requests` checks SHALL NOT be treated as failures merely because the repository has no commits or no pull requests — an empty 200 response is `ok`.

## Requirement 3: Validate an already-registered repository

**User Story.** As an administrator looking at the repositories table, I want to validate a repository I already saved, because the token may have been created with wrong permissions, expired, or been revoked after registration.

### Acceptance Criteria

3.1. THE system SHALL expose `POST /api/git/repos/{repoId}/validate-token`, resolving the token from SSM at `/kiro-cost-analyzer/git-tokens/{repoId}` and the location from the stored repository configuration.

3.2. WHEN `repoId` does not correspond to a stored repository THEN THE endpoint SHALL return HTTP 404 with `error: "NotFound"`.

3.3. WHEN the SSM parameter for the repository is absent or empty THEN THE endpoint SHALL return an overall verdict of `failed` with every check reported as `unauthorized`, and SHALL include a distinct `tokenMissing: true` marker so the frontend can say "no token stored" rather than "token rejected".

3.4. THE endpoint SHALL be restricted to the `Admins` group per Requirement 1.5.

3.5. THE stored-validation path SHALL NOT accept a token in the request body — it validates exactly what is deployed, so a passing result is trustworthy.

## Requirement 4: Actionable remediation

**User Story.** As an administrator whose validation failed, I want to be told precisely which permission to grant, so I can fix it without reading provider documentation or agent logs.

### Acceptance Criteria

4.1. THE response SHALL include a `requiredPermissions` array listing a stable identifier for every check that did not return `ok`, drawn from: `metadata:read`, `contents:read`, `pull_requests:read` (GitHub) and `read_api` (GitLab).

4.2. THE response SHALL NOT contain human-readable remediation prose. Per the project's English-only-backend rule, the backend returns slugs and identifiers; the frontend owns all display text and translation.

4.3. WHEN the overall verdict is not `ok` THEN THE frontend SHALL present a modal enumerating the required permissions using each provider's own naming (GitHub: "Contents", "Pull requests", "Metadata", and the classic-PAT `repo` scope alternative; GitLab: `read_api`).

4.4. THE remediation modal SHALL state, for GitHub, both the fine-grained permission names and the classic-PAT scope equivalent, because the two token types present entirely different UIs and a user holding one cannot act on instructions written for the other.

## Requirement 5: Do not turn the validator into an SSRF vector

**User Story.** As the operator of this account, I want the validation endpoint to be unable to probe internal network addresses, because it accepts a user-supplied host and runs inside a Lambda holding SSM, DynamoDB, and Cognito permissions.

### Acceptance Criteria

5.1. FOR `github`, THE outbound host SHALL be the hardcoded constant `https://api.github.com`. The submitted URL SHALL only be parsed for `owner`/`repo`; its host SHALL NOT be used to route any request.

5.2. FOR `gitlab`, WHERE the base URL is necessarily user-supplied, THE endpoint SHALL require the `https` scheme and SHALL reject the request with HTTP 400 when the scheme is anything else.

5.3. THE endpoint SHALL resolve the GitLab hostname and SHALL reject the request with HTTP 400 when any resolved address is loopback, link-local, private, reserved, unspecified, or multicast — which blocks the instance metadata endpoint `169.254.169.254` and every RFC 1918 range.

5.4. WHEN hostname resolution fails THEN THE endpoint SHALL return HTTP 400 rather than attempting the request.

5.5. EACH outbound request SHALL carry an explicit timeout and SHALL NOT follow redirects, so a permissive redirect cannot escape the vetted host.

## Requirement 6: Never leak the token

**User Story.** As a security reviewer, I want certainty that the token cannot reach a log group, a response body, or an error message.

### Acceptance Criteria

6.1. NO log statement SHALL include the token value, in whole or in part.

6.2. THE response body SHALL NOT echo the token, nor any prefix or suffix of it.

6.3. WHEN an outbound request raises THEN THE logged detail SHALL be limited to the exception class name, the check id, the provider, and the sanitized URL — never the exception's string form, which for `requests` can embed the request headers.

6.4. THE structured log for a validation SHALL record the per-check status slugs and the overall verdict, so an operator can audit that a validation happened and what it concluded without the credential being present.

## Requirement 7: Frontend surface

**User Story.** As an administrator, I want the validation reachable from both places where a token is handled.

### Acceptance Criteria

7.1. THE add/edit repository form SHALL offer a "Validate permissions" action that is enabled only when `url`, `provider`, and `accessToken` all hold values, calling the ad-hoc endpoint.

7.2. THE repositories table SHALL offer a per-row "Validate permissions" action calling the stored endpoint for that `repoId`.

7.3. WHILE a validation is in flight THE triggering control SHALL show a loading state and SHALL be non-re-entrant.

7.4. WHEN the overall verdict is `ok` THEN THE UI SHALL show a success indication listing the three passing checks, without opening a modal.

7.5. WHEN the overall verdict is `partial` or `failed` THEN THE UI SHALL open the remediation modal of Requirement 4.3, showing each check's outcome and the permissions to grant.

7.6. EVERY string introduced SHALL resolve through `t(key)` with parallel entries in `en.json` and `pt-BR.json`, alphabetically positioned, per the i18n build gate.

## Out of scope

- Automatically re-validating on a schedule, or blocking repository creation on a failed validation. The check is user-triggered and advisory; a user may knowingly save a token whose permissions are not yet granted.
- Validating providers other than `github` and `gitlab`. The `GitRepository` type admits `bitbucket` and `codecommit`, but the correlation agent has no tool for either, so there is nothing meaningful to probe.
- Writing the validation outcome to DynamoDB or reflecting it in the table's `Access Token` column. That column reflects token *presence*; conflating it with token *validity* would make a cached verdict look live.
- Detecting token expiry dates. Neither provider exposes an expiry on the endpoints used, and GitHub's `token_expires_at` header is only present for some token types.
