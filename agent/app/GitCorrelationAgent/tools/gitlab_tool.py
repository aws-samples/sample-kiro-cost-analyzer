"""GitLab Tool — Strands @tool for fetching GitLab activity.

Provides the agent with access to GitLab commits and merge requests via the
GitLab REST API (v4). Mirrors `github_tool.py` structurally: a closure
factory returns a single `@tool` decorated function shared across every
GitLab repository in the analysis. `repo_id` is a per-call tool argument
rather than a factory-time closure parameter, since the same tool instance
may be invoked for several different repositories in one agent run. The
repository-scoped access token is fetched lazily on the first call for a
given `repo_id` and memoized in a `dict[str, str]` cache keyed by
`repo_id`, so a GitLab-only analysis never touches a GitHub token and vice
versa, and repeated calls for the same repository skip SSM.

Authentication uses the `PRIVATE-TOKEN` header, never `Authorization`.

The set of operations called here is MIRRORED by the check table in
`backend/handlers/git_token_validation_handler.py`, which is what the
Settings page's "Validate permissions" action probes. If you add an
operation to this tool, add a matching check there too — otherwise
validation reports a green token that this tool then fails on.

Author filtering is deliberately belt-and-braces:

- Commits: GitLab's `author` query parameter arrived in GitLab 15.10 and
  matches the commit author *name*, not the account username, so it is not
  relied on alone. The tool always re-filters commits client-side on
  `author_name` and `author_email`, case-insensitively.
- Merge requests: `author_username` is sent as a query parameter, and the
  tool also re-checks `author.username` client-side, mirroring the
  defensive pattern `github_tool.py` uses with `pr["user"]["login"]`.

Certificate verification is always enabled and cannot be disabled. A
GitLab instance served over a self-signed certificate must be given a
certificate issued by a trusted CA (public or internal) — see "TLS
certificate trust" in `docs/deploy.md`.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import requests
from strands import tool

try:
    from tools.ssm_token import fetch_repo_token
except ImportError:
    from agent.app.GitCorrelationAgent.tools.ssm_token import fetch_repo_token

logger = logging.getLogger(__name__)

MAX_COMMITS = 100
MAX_MRS = 50
REQUEST_TIMEOUT_SECONDS = 30
API_PATH = "/api/v4"


def build_gitlab_tool(ssm_client=None):
    """Factory that returns a @tool decorated function for GitLab API access.

    Args:
        ssm_client: Optional boto3 SSM client, injected for testability
            and forwarded to `fetch_repo_token`.

    Returns:
        A @tool decorated function that the Strands Agent can call. The
        same function instance is reused for every GitLab repository in
        an analysis; the token is resolved per call from the `repo_id`
        argument the model passes in and memoized in a cache keyed by
        `repo_id`, so repeated calls for the same repository skip SSM.
    """
    token_cache: dict[str, str] = {}

    def _get_token(repo_id: str) -> str:
        if repo_id not in token_cache:
            token_cache[repo_id] = fetch_repo_token(repo_id, ssm_client=ssm_client)
        return token_cache[repo_id]

    @tool
    def get_gitlab_activity(
        repo_id: str, base_url: str, project_path: str, author: str, since: str
    ) -> dict:
        """Fetch GitLab commits and merge requests for a project.

        Args:
            repo_id: Repository-scoped identifier used to resolve the
                access token from SSM Parameter Store.
            base_url: GitLab instance base URL (scheme://host[:port])
            project_path: Full namespace path, e.g. group/subgroup/project
            author: GitLab username to filter by
            since: ISO 8601 date — only activity on or after this date

        Returns:
            Dict with commits (list) and pull_requests (list), matching the
            Normalized_Activity_Contract. On failure, a dict with `error`
            and `retryable`.
        """
        token = _get_token(repo_id)
        if not token:
            logger.error(
                "GitLab auth failed before any request: repo_id=%s base_url=%s project_path=%s reason=no_token_resolved",
                repo_id, base_url, project_path,
            )
            return {"error": "GITLAB_AUTH_FAILED", "retryable": False}

        headers = {"PRIVATE-TOKEN": token}
        encoded_project_path = quote(project_path, safe="")

        # Fetch commits
        commits_url = f"{base_url}{API_PATH}/projects/{encoded_project_path}/repository/commits"
        commits_params = {
            "since": since,
            "per_page": MAX_COMMITS,
        }

        logger.info(
            "GitLab commits request: repo_id=%s url=%s params=%s",
            repo_id, commits_url, commits_params,
        )

        try:
            commits_response = requests.get(
                commits_url,
                headers=headers,
                params=commits_params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.error(
                "GitLab commits request failed: repo_id=%s url=%s exc_type=%s",
                repo_id, commits_url, type(exc).__name__,
            )
            return {"error": "GITLAB_REQUEST_FAILED", "retryable": True}

        logger.info(
            "GitLab commits response: repo_id=%s url=%s status_code=%s",
            repo_id, commits_url, commits_response.status_code,
        )

        if commits_response.status_code == 429:
            logger.error("GitLab rate limit on commits: repo_id=%s url=%s", repo_id, commits_url)
            return {"error": "GITLAB_RATE_LIMIT", "retryable": True}
        if commits_response.status_code in (401, 403):
            logger.error(
                "GitLab auth failed on commits: repo_id=%s url=%s status_code=%s",
                repo_id, commits_url, commits_response.status_code,
            )
            return {"error": "GITLAB_AUTH_FAILED", "retryable": False}
        if commits_response.status_code == 404:
            logger.error(
                "GitLab commits endpoint not found: repo_id=%s url=%s status_code=%s",
                repo_id, commits_url, commits_response.status_code,
            )
            return {"error": "GITLAB_REQUEST_FAILED", "retryable": True}

        commits_data = commits_response.json() if commits_response.status_code == 200 else []
        if not isinstance(commits_data, list):
            commits_data = []

        author_lower = author.lower()

        commits = [
            {
                "sha": c.get("id", ""),
                "message": c.get("message", ""),
                "date": c.get("authored_date") or c.get("committed_date") or c.get("created_at", ""),
            }
            for c in commits_data
            if _safe_lower(c.get("author_name")) == author_lower
            or _safe_lower(c.get("author_email")) == author_lower
        ]
        commits = [c for c in commits if not _before_start_date(c["date"], since)][:MAX_COMMITS]

        # Fetch merge requests
        mrs_url = f"{base_url}{API_PATH}/projects/{encoded_project_path}/merge_requests"
        mrs_params = {
            "author_username": author,
            "created_after": since,
            "state": "all",
            "per_page": MAX_MRS,
            "order_by": "updated_at",
            "sort": "desc",
        }

        logger.info(
            "GitLab merge requests request: repo_id=%s url=%s params=%s",
            repo_id, mrs_url, mrs_params,
        )

        try:
            mrs_response = requests.get(
                mrs_url,
                headers=headers,
                params=mrs_params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.error(
                "GitLab merge requests request failed: repo_id=%s url=%s exc_type=%s",
                repo_id, mrs_url, type(exc).__name__,
            )
            return {
                "commits": commits,
                "pull_requests": [],
                "warning": "Failed to fetch merge requests",
            }

        logger.info(
            "GitLab merge requests response: repo_id=%s url=%s status_code=%s",
            repo_id, mrs_url, mrs_response.status_code,
        )

        if mrs_response.status_code == 429:
            logger.error("GitLab rate limit on merge requests: repo_id=%s url=%s", repo_id, mrs_url)
            return {"error": "GITLAB_RATE_LIMIT", "retryable": True}
        if mrs_response.status_code in (401, 403):
            logger.error(
                "GitLab auth failed on merge requests: repo_id=%s url=%s status_code=%s",
                repo_id, mrs_url, mrs_response.status_code,
            )
            return {"error": "GITLAB_AUTH_FAILED", "retryable": False}

        mrs_data = mrs_response.json() if mrs_response.status_code == 200 else []
        if not isinstance(mrs_data, list):
            mrs_data = []

        pull_requests = [
            {
                "number": mr.get("iid", 0),
                "title": mr.get("title", ""),
                "state": mr.get("state", ""),
                "created_at": mr.get("created_at", ""),
            }
            for mr in mrs_data
            if _safe_lower(_safe_get_username(mr.get("author"))) == author_lower
            and not _before_start_date(mr.get("created_at", ""), since)
        ][:MAX_MRS]

        return {
            "commits": commits,
            "pull_requests": pull_requests,
        }

    return get_gitlab_activity


def _safe_lower(value) -> str:
    """Lowercase `value` if it is a string, otherwise return "".

    Defends against malformed API responses where a field expected to be
    a string author name/email/username is `None` or holds an unrelated
    type (int, list, dict, ...). `.get(key, default)` only substitutes the
    default when the key is absent, not when its value is present but
    falsy or wrongly typed, so this check is needed on top of `.get()`.
    """
    return value.lower() if isinstance(value, str) else ""


def _safe_get_username(author) -> str:
    """Extract `username` from a merge request's `author` field, safely.

    `author` is expected to be a dict like `{"username": "..."}`, but a
    malformed response may send `None`, a non-dict, or a dict whose
    `username` value is itself the wrong type. Returns "" for any shape
    that does not yield a string username.
    """
    if not isinstance(author, dict):
        return ""
    username = author.get("username")
    return username if isinstance(username, str) else ""


def _before_start_date(date_value, since: str) -> bool:
    """Return True if `date_value` sorts before `since`.

    Both are expected to be ISO 8601 strings, which sort lexicographically
    in chronological order. A missing, non-string, or otherwise malformed
    `date_value` (including non-string types from an unexpected API
    response body) is treated as not before the start date, so it is not
    silently dropped rather than raising.
    """
    if not isinstance(date_value, str) or not date_value or not since:
        return False
    return date_value < since
