"""GitHub Tool — Strands @tool for fetching GitHub activity.

Provides the agent with access to GitHub commits and pull requests
via the GitHub REST API.

Uses a factory pattern: `build_github_tool(token)` returns a @tool
decorated function with the GitHub token captured in closure.
"""

from __future__ import annotations

import logging

import requests
from strands import tool

logger = logging.getLogger(__name__)

MAX_COMMITS = 100
MAX_PRS = 50
GITHUB_API_BASE = "https://api.github.com"


def build_github_tool(token: str):
    """Factory that returns a @tool decorated function for GitHub API access.

    Args:
        token: GitHub personal access token for authentication.

    Returns:
        A @tool decorated function that the Strands Agent can call.
    """

    @tool
    def get_github_activity(owner: str, repo: str, author: str, since: str) -> dict:
        """Fetch GitHub commits and pull requests for a repository.

        Args:
            owner: Repository owner (user or org)
            repo: Repository name
            author: Git author username to filter by
            since: ISO 8601 date — only activity after this date

        Returns:
            Dict with commits (list) and pull_requests (list)
        """
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

        try:
            commits_response = requests.get(
                commits_url, headers=headers, params=commits_params, timeout=30
            )
        except requests.RequestException as exc:
            logger.error("GitHub API request failed: %s", exc)
            return {"error": "GITHUB_REQUEST_FAILED", "retryable": True}

        if commits_response.status_code == 429:
            return {"error": "GITHUB_RATE_LIMIT", "retryable": True}
        if commits_response.status_code in (401, 403):
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

        try:
            prs_response = requests.get(
                prs_url, headers=headers, params=prs_params, timeout=30
            )
        except requests.RequestException as exc:
            logger.error("GitHub PRs API request failed: %s", exc)
            return {
                "commits": commits,
                "pull_requests": [],
                "warning": "Failed to fetch pull requests",
            }

        if prs_response.status_code == 429:
            return {"error": "GITHUB_RATE_LIMIT", "retryable": True}
        if prs_response.status_code in (401, 403):
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
