"""GitHub Tool — Strands @tool for fetching GitHub activity.

Provides the agent with access to GitHub commits and pull requests
via the GitHub REST API.

Uses a factory pattern: `build_github_tool(ssm_client=None)` returns a
single `@tool` decorated function shared across every GitHub repository in
the analysis. `repo_id` is a per-call tool argument rather than a
factory-time closure parameter, mirroring `gitlab_tool.py`. The
repository-scoped access token is fetched lazily on the first call for a
given `repo_id` and memoized in a `dict[str, str]` cache keyed by
`repo_id`, so a GitLab-only analysis never reads a GitHub token and vice
versa, and repeated calls for the same repository skip SSM.
"""

from __future__ import annotations

import logging

import requests
from strands import tool

try:
    from tools.ssm_token import fetch_repo_token
except ImportError:
    from agent.app.GitCorrelationAgent.tools.ssm_token import fetch_repo_token

logger = logging.getLogger(__name__)

MAX_COMMITS = 100
MAX_PRS = 50
GITHUB_API_BASE = "https://api.github.com"


def build_github_tool(ssm_client=None):
    """Factory that returns a @tool decorated function for GitHub API access.

    Args:
        ssm_client: Optional boto3 SSM client, injected for testability
            and forwarded to `fetch_repo_token`.

    Returns:
        A @tool decorated function that the Strands Agent can call. The
        same function instance is reused for every GitHub repository in
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
    def get_github_activity(repo_id: str, owner: str, repo: str, author: str, since: str) -> dict:
        """Fetch GitHub commits and pull requests for a repository.

        Args:
            repo_id: Repository-scoped identifier used to resolve the
                access token from SSM Parameter Store.
            owner: Repository owner (user or org)
            repo: Repository name
            author: Git author username to filter by
            since: ISO 8601 date — only activity after this date

        Returns:
            Dict with commits (list) and pull_requests (list)
        """
        token = _get_token(repo_id)
        if not token:
            logger.error(
                "GitHub auth failed before any request: repo_id=%s owner=%s repo=%s reason=no_token_resolved",
                repo_id, owner, repo,
            )
            return {"error": "GITHUB_AUTH_FAILED", "retryable": False}

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Fetch commits
        commits_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits"
        commits_params = {
            "author": author,
            "since": since,
            "per_page": MAX_COMMITS,
        }

        logger.info(
            "GitHub commits request: repo_id=%s url=%s params=%s",
            repo_id, commits_url, commits_params,
        )

        try:
            commits_response = requests.get(
                commits_url, headers=headers, params=commits_params, timeout=30
            )
        except requests.RequestException as exc:
            logger.error(
                "GitHub commits request failed: repo_id=%s url=%s exc_type=%s",
                repo_id, commits_url, type(exc).__name__,
            )
            return {"error": "GITHUB_REQUEST_FAILED", "retryable": True}

        logger.info(
            "GitHub commits response: repo_id=%s url=%s status_code=%s",
            repo_id, commits_url, commits_response.status_code,
        )

        if commits_response.status_code == 429:
            logger.error("GitHub rate limit on commits: repo_id=%s url=%s", repo_id, commits_url)
            return {"error": "GITHUB_RATE_LIMIT", "retryable": True}
        if commits_response.status_code in (401, 403):
            logger.error(
                "GitHub auth failed on commits: repo_id=%s url=%s status_code=%s",
                repo_id, commits_url, commits_response.status_code,
            )
            return {"error": "GITHUB_AUTH_FAILED", "retryable": False}

        commits_data = commits_response.json() if commits_response.status_code == 200 else []

        commits = [
            {
                "sha": c.get("sha", ""),
                "message": c.get("commit", {}).get("message", ""),
                "date": c.get("commit", {}).get("author", {}).get("date", ""),
            }
            for c in commits_data[:MAX_COMMITS]
        ]

        # Fetch pull requests
        prs_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls"
        prs_params = {
            "state": "all",
            "per_page": MAX_PRS,
            "sort": "updated",
            "direction": "desc",
        }

        logger.info(
            "GitHub pull requests request: repo_id=%s url=%s params=%s",
            repo_id, prs_url, prs_params,
        )

        try:
            prs_response = requests.get(
                prs_url, headers=headers, params=prs_params, timeout=30
            )
        except requests.RequestException as exc:
            logger.error(
                "GitHub pull requests request failed: repo_id=%s url=%s exc_type=%s",
                repo_id, prs_url, type(exc).__name__,
            )
            return {
                "commits": commits,
                "pull_requests": [],
                "warning": "Failed to fetch pull requests",
            }

        logger.info(
            "GitHub pull requests response: repo_id=%s url=%s status_code=%s",
            repo_id, prs_url, prs_response.status_code,
        )

        if prs_response.status_code == 429:
            logger.error("GitHub rate limit on pull requests: repo_id=%s url=%s", repo_id, prs_url)
            return {"error": "GITHUB_RATE_LIMIT", "retryable": True}
        if prs_response.status_code in (401, 403):
            logger.error(
                "GitHub auth failed on pull requests: repo_id=%s url=%s status_code=%s",
                repo_id, prs_url, prs_response.status_code,
            )
            return {"error": "GITHUB_AUTH_FAILED", "retryable": False}

        prs_data = prs_response.json() if prs_response.status_code == 200 else []

        # Filter PRs by author
        pull_requests = [
            {
                "number": pr.get("number", 0),
                "title": pr.get("title", ""),
                "state": pr.get("state", ""),
                "created_at": pr.get("created_at", ""),
            }
            for pr in prs_data[:MAX_PRS]
            if pr.get("user", {}).get("login", "").lower() == author.lower()
        ]

        return {
            "commits": commits,
            "pull_requests": pull_requests,
        }

    return get_github_activity
