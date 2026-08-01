"""Tests for GitHub Tool (agent/app/GitCorrelationAgent/tools/github_tool.py)."""

import sys
import os
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent", "app", "GitCorrelationAgent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agent.app.GitCorrelationAgent.tools.github_tool import build_github_tool, MAX_COMMITS, MAX_PRS

FAKE_REPO_ID = "deadbeef"


class TestBuildGithubTool:
    def test_factory_returns_callable(self):
        tool_fn = build_github_tool()
        assert callable(tool_fn)

    def test_tool_has_docstring(self):
        tool_fn = build_github_tool()
        assert tool_fn.__doc__ is not None
        assert "GitHub" in tool_fn.__doc__ or "commits" in tool_fn.__doc__


class TestGithubToolFunction:
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.requests.get")
    def test_successful_response(self, mock_get, mock_fetch_token):
        """Test successful fetch of commits and PRs."""
        commits_response = MagicMock()
        commits_response.status_code = 200
        commits_response.json.return_value = [
            {
                "sha": "abc123",
                "commit": {
                    "message": "feat: add login",
                    "author": {"date": "2026-04-15T10:00:00Z"},
                },
            },
            {
                "sha": "def456",
                "commit": {
                    "message": "fix: resolve auth bug",
                    "author": {"date": "2026-04-16T11:00:00Z"},
                },
            },
        ]

        prs_response = MagicMock()
        prs_response.status_code = 200
        prs_response.json.return_value = [
            {
                "number": 42,
                "title": "Add authentication",
                "state": "closed",
                "created_at": "2026-04-14T09:00:00Z",
                "user": {"login": "octocat"},
            },
        ]

        mock_get.side_effect = [commits_response, prs_response]

        tool_fn = build_github_tool()
        result = tool_fn(repo_id=FAKE_REPO_ID, owner="org", repo="myrepo", author="octocat", since="2026-04-01")

        assert "error" not in result
        assert len(result["commits"]) == 2
        assert result["commits"][0]["sha"] == "abc123"
        assert result["commits"][0]["message"] == "feat: add login"
        assert result["commits"][0]["date"] == "2026-04-15T10:00:00Z"
        assert len(result["pull_requests"]) == 1
        assert result["pull_requests"][0]["number"] == 42

    @patch("agent.app.GitCorrelationAgent.tools.github_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.requests.get")
    def test_rate_limit_on_commits(self, mock_get, mock_fetch_token):
        """Test HTTP 429 on commits returns rate limit error."""
        response = MagicMock()
        response.status_code = 429
        mock_get.return_value = response

        tool_fn = build_github_tool()
        result = tool_fn(repo_id=FAKE_REPO_ID, owner="org", repo="myrepo", author="octocat", since="2026-04-01")

        assert result["error"] == "GITHUB_RATE_LIMIT"
        assert result["retryable"] is True

    @patch("agent.app.GitCorrelationAgent.tools.github_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.requests.get")
    def test_auth_failure_on_commits(self, mock_get, mock_fetch_token):
        """Test HTTP 401 on commits returns auth failure error."""
        response = MagicMock()
        response.status_code = 401
        mock_get.return_value = response

        tool_fn = build_github_tool()
        result = tool_fn(repo_id=FAKE_REPO_ID, owner="org", repo="myrepo", author="octocat", since="2026-04-01")

        assert result["error"] == "GITHUB_AUTH_FAILED"
        assert result["retryable"] is False

    @patch("agent.app.GitCorrelationAgent.tools.github_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.requests.get")
    def test_auth_failure_403(self, mock_get, mock_fetch_token):
        """Test HTTP 403 on commits returns auth failure error."""
        response = MagicMock()
        response.status_code = 403
        mock_get.return_value = response

        tool_fn = build_github_tool()
        result = tool_fn(repo_id=FAKE_REPO_ID, owner="org", repo="myrepo", author="octocat", since="2026-04-01")

        assert result["error"] == "GITHUB_AUTH_FAILED"
        assert result["retryable"] is False

    @patch("agent.app.GitCorrelationAgent.tools.github_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.requests.get")
    def test_rate_limit_on_prs(self, mock_get, mock_fetch_token):
        """Test HTTP 429 on PRs returns rate limit error."""
        commits_response = MagicMock()
        commits_response.status_code = 200
        commits_response.json.return_value = []

        prs_response = MagicMock()
        prs_response.status_code = 429

        mock_get.side_effect = [commits_response, prs_response]

        tool_fn = build_github_tool()
        result = tool_fn(repo_id=FAKE_REPO_ID, owner="org", repo="myrepo", author="octocat", since="2026-04-01")

        assert result["error"] == "GITHUB_RATE_LIMIT"
        assert result["retryable"] is True

    @patch("agent.app.GitCorrelationAgent.tools.github_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.requests.get")
    def test_max_commits_limit(self, mock_get, mock_fetch_token):
        """Test that commits are limited to MAX_COMMITS."""
        commits_data = [
            {
                "sha": f"sha{i}",
                "commit": {"message": f"commit {i}", "author": {"date": "2026-04-15T10:00:00Z"}},
            }
            for i in range(150)
        ]

        commits_response = MagicMock()
        commits_response.status_code = 200
        commits_response.json.return_value = commits_data

        prs_response = MagicMock()
        prs_response.status_code = 200
        prs_response.json.return_value = []

        mock_get.side_effect = [commits_response, prs_response]

        tool_fn = build_github_tool()
        result = tool_fn(repo_id=FAKE_REPO_ID, owner="org", repo="myrepo", author="octocat", since="2026-04-01")

        assert len(result["commits"]) <= MAX_COMMITS

    @patch("agent.app.GitCorrelationAgent.tools.github_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.requests.get")
    def test_max_prs_limit(self, mock_get, mock_fetch_token):
        """Test that PRs are limited to MAX_PRS."""
        commits_response = MagicMock()
        commits_response.status_code = 200
        commits_response.json.return_value = []

        prs_data = [
            {
                "number": i,
                "title": f"PR {i}",
                "state": "closed",
                "created_at": "2026-04-15T10:00:00Z",
                "user": {"login": "octocat"},
            }
            for i in range(100)
        ]

        prs_response = MagicMock()
        prs_response.status_code = 200
        prs_response.json.return_value = prs_data

        mock_get.side_effect = [commits_response, prs_response]

        tool_fn = build_github_tool()
        result = tool_fn(repo_id=FAKE_REPO_ID, owner="org", repo="myrepo", author="octocat", since="2026-04-01")

        assert len(result["pull_requests"]) <= MAX_PRS

    @patch("agent.app.GitCorrelationAgent.tools.github_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.requests.get")
    def test_filters_prs_by_author(self, mock_get, mock_fetch_token):
        """Test that PRs are filtered by author."""
        commits_response = MagicMock()
        commits_response.status_code = 200
        commits_response.json.return_value = []

        prs_data = [
            {"number": 1, "title": "My PR", "state": "open", "created_at": "2026-04-15T10:00:00Z", "user": {"login": "octocat"}},
            {"number": 2, "title": "Other PR", "state": "open", "created_at": "2026-04-15T10:00:00Z", "user": {"login": "other-user"}},
        ]

        prs_response = MagicMock()
        prs_response.status_code = 200
        prs_response.json.return_value = prs_data

        mock_get.side_effect = [commits_response, prs_response]

        tool_fn = build_github_tool()
        result = tool_fn(repo_id=FAKE_REPO_ID, owner="org", repo="myrepo", author="octocat", since="2026-04-01")

        assert len(result["pull_requests"]) == 1
        assert result["pull_requests"][0]["title"] == "My PR"


# Feature: agent-git-correlation, Property 3: GitHub Tool Output Structure
class TestGithubToolOutputStructureProperty:
    """Property 3: GitHub Tool Output Structure.

    For any valid GitHub API response (mocked), get_github_activity SHALL return
    a dict containing exactly the keys `commits` (list) and `pull_requests` (list),
    where each commit has `sha`, `message`, and `date` fields, and each PR has
    `number`, `title`, `state`, and `created_at` fields.

    **Validates: Requirements 1.3**
    """

    @given(
        num_commits=st.integers(min_value=0, max_value=10),
        num_prs=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=20)
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.github_tool.requests.get")
    def test_output_structure_always_valid(self, mock_get, mock_fetch_token, num_commits, num_prs):
        """Valid API responses produce correct output keys/types."""
        commits_data = [
            {
                "sha": f"sha{i}",
                "commit": {"message": f"commit {i}", "author": {"date": f"2026-04-{15+i%10:02d}T10:00:00Z"}},
            }
            for i in range(num_commits)
        ]

        prs_data = [
            {
                "number": i + 1,
                "title": f"PR {i}",
                "state": "open" if i % 2 == 0 else "closed",
                "created_at": f"2026-04-{15+i%10:02d}T10:00:00Z",
                "user": {"login": "testuser"},
            }
            for i in range(num_prs)
        ]

        commits_response = MagicMock()
        commits_response.status_code = 200
        commits_response.json.return_value = commits_data

        prs_response = MagicMock()
        prs_response.status_code = 200
        prs_response.json.return_value = prs_data

        mock_get.side_effect = [commits_response, prs_response]

        tool_fn = build_github_tool()
        result = tool_fn(repo_id=FAKE_REPO_ID, owner="org", repo="myrepo", author="testuser", since="2026-04-01")

        # Must have commits and pull_requests keys
        assert "commits" in result
        assert "pull_requests" in result
        assert isinstance(result["commits"], list)
        assert isinstance(result["pull_requests"], list)

        # Each commit must have sha, message, date
        for commit in result["commits"]:
            assert "sha" in commit
            assert "message" in commit
            assert "date" in commit

        # Each PR must have number, title, state, created_at
        for pr in result["pull_requests"]:
            assert "number" in pr
            assert "title" in pr
            assert "state" in pr
            assert "created_at" in pr
