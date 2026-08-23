# Design — Git Token Permission Validation

## Overview

A new backend handler probes the three provider API operations the correlation agent depends on, using a token supplied either in the request body (pre-save) or resolved from SSM (post-save), and returns a per-check verdict plus the permission identifiers needed to fix any failure. The frontend adds two entry points — a button in the add/edit form and a per-row table action — and a remediation modal that renders provider-native permission names.

The work is deliberately additive. No existing route, response shape, DynamoDB item, or SSM parameter changes. The `Access Token` column keeps meaning "a token is stored", and validation results are never persisted (see requirements.md, Out of scope).

Files touched:

| File | Change |
|---|---|
| `backend/handlers/git_token_validation_handler.py` | New — the whole validation engine |
| `backend/handler.py` | New route regex + two dispatch blocks |
| `template.yaml` | Two new API Gateway Events on `BackendFunction` |
| `frontend/src/types/index.ts` | New interfaces in the Git section |
| `frontend/src/api/gitApi.ts` | Two new call wrappers |
| `frontend/src/components/GitRepoForm.tsx` | Validate button + result surface |
| `frontend/src/components/GitTokenValidationModal.tsx` | New — remediation modal |
| `frontend/src/pages/GitSettingsPage.tsx` | Row action + modal wiring |
| `frontend/src/locales/en.json`, `pt-BR.json` | Parallel keys |
| `tests/test_git_token_validation_handler.py` | New |
| `frontend/src/components/__tests__/GitTokenValidationModal.test.tsx` | New |

## Reuse, not reimplementation

Three shared pieces already exist and are used verbatim:

- `git_shared.git_url_parser.parse_repo_url(provider, url)` → `{"owner","repo"}` for GitHub, `{"baseUrl","projectPath"}` for GitLab. Total (never raises, returns `None`). This is the same function `agent_correlation_handler.build_repo_descriptors` uses, so the validator resolves a repository to exactly the coordinates the agent will later use — a passing validation cannot be passing against a different target.
- `git_shared.git_providers.SUPPORTED_PROVIDERS` (`{"github","gitlab"}`) and `SSM_TOKEN_PATH_PREFIX` (`/kiro-cost-analyzer/git-tokens`).
- `git_shared.git_repository.GitRepository` for reading the stored repository config on the `{repoId}` path.

The endpoint URLs and auth headers mirror `agent/app/GitCorrelationAgent/tools/github_tool.py` and `gitlab_tool.py`. That mirroring is the feature's whole value, and it is also its main maintenance hazard: if a future change adds an operation to a provider tool, the check table here must gain a matching row or validation will report a green token that the agent then fails on. This coupling is called out in `tasks.md` as a documentation task rather than left implicit.

## Check table

```python
CHECK_REPO_ACCESS = "repo_access"
CHECK_COMMITS = "commits"
CHECK_PULL_REQUESTS = "pull_requests"

CHECK_ORDER = (CHECK_REPO_ACCESS, CHECK_COMMITS, CHECK_PULL_REQUESTS)
```

| Check | GitHub path (host fixed to `api.github.com`) | GitLab path (under `{baseUrl}/api/v4`) | Query |
|---|---|---|---|
| `repo_access` | `/repos/{owner}/{repo}` | `/projects/{enc}` | — |
| `commits` | `/repos/{owner}/{repo}/commits` | `/projects/{enc}/repository/commits` | `per_page=1` |
| `pull_requests` | `/repos/{owner}/{repo}/pulls` | `/projects/{enc}/merge_requests` | `per_page=1`, `state=all` |

`{enc}` is `urllib.parse.quote(project_path, safe="")`, matching `gitlab_tool.py`.

Permission identifiers returned for a non-`ok` check:

```python
REQUIRED_PERMISSION = {
    "github": {
        CHECK_REPO_ACCESS: "metadata:read",
        CHECK_COMMITS: "contents:read",
        CHECK_PULL_REQUESTS: "pull_requests:read",
    },
    "gitlab": {
        CHECK_REPO_ACCESS: "read_api",
        CHECK_COMMITS: "read_api",
        CHECK_PULL_REQUESTS: "read_api",
    },
}
```

GitLab collapses to a single scope because `read_api` is what actually gates all three; reporting three copies of it would imply three separate switches in the GitLab UI that do not exist. The response de-duplicates while preserving first-seen order.

## Status mapping

```python
def _status_for(http_status: int) -> str:
    if 200 <= http_status < 300:
        return "ok"
    return {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        429: "rate_limited",
    }.get(http_status, "error")
```

`unreachable` is assigned only in the `requests.RequestException` branch, where no status exists. An empty 200 body is `ok` (Requirement 2.7) — the check reads the status line, never the payload, which also means the response body is never parsed and therefore never logged.

## Response contract

```json
{
  "provider": "github",
  "overall": "partial",
  "tokenMissing": false,
  "checks": [
    {"id": "repo_access",    "status": "ok",        "httpStatus": 200},
    {"id": "commits",        "status": "forbidden", "httpStatus": 403},
    {"id": "pull_requests",  "status": "forbidden", "httpStatus": 403}
  ],
  "requiredPermissions": ["contents:read", "pull_requests:read"]
}
```

`overall` is derived, never sent by a caller:

```python
statuses = [c["status"] for c in checks]
if all(s == "ok" for s in statuses):
    overall = "ok"
elif any(s == "ok" for s in statuses):
    overall = "partial"
else:
    overall = "failed"
```

The payload holds no prose. Every human-readable string the user sees — check labels, status labels, remediation sentences — resolves in the frontend from `t(key)`, satisfying the English-only-backend rule in steering §4.1 without forcing English text onto a pt-BR user.

## SSRF containment

GitHub needs no containment: `GITHUB_API_BASE = "https://api.github.com"` is a module constant and the submitted URL contributes only `owner`/`repo` path segments, which are percent-encoded into the path. A URL of `https://evil.example/a/b` validates against `https://api.github.com/repos/a/b`, not against `evil.example`.

GitLab is the exposed case, because self-hosted instances mean the host is legitimately user-supplied. The gate runs before any socket is opened:

```python
def _assert_public_https_host(base_url: str) -> None:
    """Raise _ValidationInputError unless base_url is https and resolves
    exclusively to public addresses."""
    parts = urlsplit(base_url)
    if parts.scheme != "https":
        raise _ValidationInputError("provider base URL must use https")
    host = parts.hostname
    if not host:
        raise _ValidationInputError("provider base URL has no host")
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise _ValidationInputError("provider host could not be resolved")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_loopback or ip.is_link_local or ip.is_private
                or ip.is_reserved or ip.is_unspecified or ip.is_multicast):
            raise _ValidationInputError("provider host resolves to a non-public address")
```

`is_link_local` is what blocks `169.254.169.254`, so the Lambda cannot be induced to read its own IMDS role credentials. `is_private` covers RFC 1918 and `fc00::/7`. Every outbound call passes `allow_redirects=False` and `timeout=_REQUEST_TIMEOUT_SECONDS` (10), so a 302 toward an internal address is reported as `error` rather than followed.

**Known limitation, stated rather than papered over:** the check resolves the hostname and then `requests` resolves it again when connecting, so a DNS entry that changes between the two (rebinding) is not defeated. Closing that requires pinning the vetted IP into the connection, which means a custom adapter and breaks SNI/virtual hosting for legitimate self-hosted GitLab. For an admin-only endpoint in a sample the residual risk is accepted and documented here.

## Two entry points, one engine

```
POST /api/git/repos/validate-token          POST /api/git/repos/{repoId}/validate-token
  body: {url, provider, accessToken}          body: ignored
        │                                             │
        │  parse_repo_url(provider, url)              │  GitRepository.get_repo_config(repoId)
        │                                             │    → 404 if absent
        │                                             │  parse_repo_url(provider, stored url)
        │                                             │  ssm.get_parameter(WithDecryption=True)
        │                                             │    → tokenMissing=True, all unauthorized
        └──────────────────┬──────────────────────────┘
                           ▼
              _run_checks(provider, location, token)
                 · _assert_public_https_host for gitlab
                 · three sequential requests, per_page=1
                 · map status → slug
                           ▼
              {provider, overall, tokenMissing, checks, requiredPermissions}
```

Sequential rather than concurrent: three requests at ~200-400ms each finish well inside the 90s Lambda timeout, and a thread pool would add failure modes for no user-visible gain.

The `tokenMissing` short-circuit (Requirement 3.3) returns every check as `unauthorized` with `httpStatus: null` **without** making any outbound request — there is nothing to authenticate with, and probing anonymously would report a public repository's endpoints as `ok`, which is exactly the false green this feature exists to prevent.

## Routing

`handler.py` gains one regex and two blocks. Ordering matters: the literal `/api/git/repos/validate-token` must be matched **before** `_GIT_REPO_DETAIL_PATTERN` (`^/api/git/repos/([^/]+)$`), which would otherwise swallow it and treat `validate-token` as a `repoId`. The existing `/sync` route has the same hazard and is already ordered accordingly, so the new blocks follow that precedent.

```python
_GIT_REPO_VALIDATE_TOKEN_PATTERN = re.compile(r"^/api/git/repos/([^/]+)/validate-token$")
_GIT_REPO_VALIDATE_TOKEN_PATH = "/api/git/repos/validate-token"
```

Both blocks apply the standard `_is_admin(claims)` gate and the `_status_code` pop convention already used by every git route.

## Frontend

New types, in the `// --- Git Integration Types ---` section:

```ts
export type GitTokenCheckId = 'repo_access' | 'commits' | 'pull_requests';
export type GitTokenCheckStatus =
  | 'ok' | 'unauthorized' | 'forbidden' | 'not_found'
  | 'rate_limited' | 'unreachable' | 'error';

export interface GitTokenCheck {
  id: GitTokenCheckId;
  status: GitTokenCheckStatus;
  httpStatus: number | null;
}

export interface GitTokenValidation {
  provider: 'github' | 'gitlab';
  overall: 'ok' | 'partial' | 'failed';
  tokenMissing: boolean;
  checks: GitTokenCheck[];
  requiredPermissions: string[];
}
```

`gitApi.ts`:

```ts
export function validateGitToken(body: { url: string; provider: string; accessToken: string }) {
  return post<GitTokenValidation>('/api/git/repos/validate-token', body);
}
export function validateStoredGitToken(repoId: string) {
  return post<GitTokenValidation>(`/api/git/repos/${repoId}/validate-token`, {});
}
```

`GitRepoForm.tsx` gains a `Button variant="normal"` after the token `FormField`, inside the existing `SpaceBetween size="m"`, disabled until `url`, `provider`, and `accessToken` are non-empty. On `overall === 'ok'` it renders an inline `StatusIndicator type="success"`; otherwise it raises the modal. The button is separate from submit — validating never saves, and saving never silently validates.

`GitTokenValidationModal.tsx` follows the project's established Modal shape (`visible` driven by a nullable state, `Box float="right"` footer, body in `SpaceBetween size="m"`), and renders:

- an `Alert` whose type is `error` for `failed`, `warning` for `partial`;
- a per-check list, each row a `StatusIndicator` plus the translated check label;
- the remediation block: for GitHub, both the fine-grained permission names and the classic-PAT `repo` alternative (Requirement 4.4); for GitLab, the `read_api` scope.

Permission names stay untranslated inside translated sentences — a pt-BR user looking for "Contents" in GitHub's UI will see the word "Contents" there regardless of their KCA locale, so translating it would actively mislead. This mirrors the existing `brand.*` convention for non-translatable strings.

`GitSettingsPage.tsx` adds a `Validate` link to the row actions `SpaceBetween` next to Edit/Remove/Sync, plus `validatingRepoId` and `validationResult` state, and renders the shared modal once at page level.

## Test plan

`tests/test_git_token_validation_handler.py`, with `requests` patched at the module boundary (no network in tests):

- Per-provider check-table correctness: asserts the exact URL and query params for all three checks, GitHub against `api.github.com` and GitLab against a `https://gitlab.example.com` base — the regression guard for URL drift away from the agent tools.
- The incident scenario end to end: `repo_access` 200, `commits` 403, `pull_requests` 403 → `overall: "partial"`, `requiredPermissions: ["contents:read", "pull_requests:read"]`.
- Full-success: three 200s → `overall: "ok"`, `requiredPermissions: []`.
- Status mapping table: 401/403/404/429/500 → `unauthorized`/`forbidden`/`not_found`/`rate_limited`/`error`; `RequestException` → `unreachable` with `httpStatus: None`.
- Empty 200 body on commits and pulls is `ok` (Requirement 2.7).
- GitLab de-duplicates `read_api` to one entry.
- SSRF gate: `http://` scheme, `https://127.0.0.1`, `https://169.254.169.254`, `https://10.0.0.5`, and an unresolvable host each produce HTTP 400 and zero outbound calls (asserted via the patched `requests` mock's call count).
- GitHub host pinning: a submitted URL of `https://evil.example/o/r` still calls `api.github.com`.
- `allow_redirects=False` and a timeout are passed on every call.
- Input validation: missing/blank `url`/`provider`/`accessToken`, unsupported provider, unparseable URL → 400 with `ValidationError`.
- Stored path: unknown `repoId` → 404; absent SSM parameter → `tokenMissing: true`, all `unauthorized`, and **zero** outbound calls.
- Token secrecy: the serialized response and every captured log record are asserted not to contain the token literal (Requirements 6.1, 6.2).

Frontend, Vitest + Testing Library: the modal renders the correct alert severity per verdict, lists each check with its status, shows both GitHub token-type remediations for a GitHub failure and `read_api` for GitLab, and renders the `tokenMissing` case distinctly from a rejected token.

Locale parity is enforced by the existing `scripts/check-locales.ts` gate in `npm run build` — no bespoke test needed.

## Correctness properties

1. **Check totality** — every response contains exactly three checks, one per id in `CHECK_ORDER`, in that order, for every provider and every combination of upstream statuses.
2. **Verdict determinism** — `overall` is a pure function of the multiset of check statuses: `ok` iff all are `ok`; `failed` iff none is `ok`; `partial` otherwise. No input reaches a fourth value.
3. **Permission soundness** — `requiredPermissions` contains an identifier if and only if at least one non-`ok` check maps to it, is duplicate-free, and preserves `CHECK_ORDER` first-seen order.
4. **Credential non-disclosure** — for every input, the token substring appears in neither the response body nor any emitted log record.
5. **No-probe invariants** — a rejected SSRF gate, a failed input validation, and a missing stored token each perform zero outbound requests.
