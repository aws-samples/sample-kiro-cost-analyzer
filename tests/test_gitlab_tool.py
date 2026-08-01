"""Tests for GitLab Tool (agent/app/GitCorrelationAgent/tools/gitlab_tool.py).

Complements the property tests in `tests/test_gitlab_provider_properties.py`
(Properties 3, 15, 16, 17, 18, which cover request-shape totality, contract
totality, field fidelity, filtering/bounds, and error classification as
universal properties). This file pins down focused, concrete example values
for the same tool — mirroring how `tests/test_github_tool.py` complements
the GitHub tool's property tests.
"""

import sys
import os
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent", "app", "GitCorrelationAgent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agent.app.GitCorrelationAgent.tools.gitlab_tool import (
    API_PATH,
    MAX_COMMITS,
    MAX_MRS,
    REQUEST_TIMEOUT_SECONDS,
    build_gitlab_tool,
)

FAKE_REPO_ID = "deadbeef"
FAKE_BASE_URL = "https://gitlab.example.com"
FAKE_PROJECT_PATH = "group/project"
FAKE_AUTHOR = "jane doe"
FAKE_SINCE = "2024-01-01"


def _make_response(status_code, json_value=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_value
    return response


class TestBuildGitlabTool:
    def test_factory_returns_callable(self):
        tool_fn = build_gitlab_tool()
        assert callable(tool_fn)

    def test_tool_has_docstring(self):
        tool_fn = build_gitlab_tool()
        assert tool_fn.__doc__ is not None
        assert "GitLab" in tool_fn.__doc__
        assert "commits" in tool_fn.__doc__
        assert "merge requests" in tool_fn.__doc__


class TestGitlabToolFunction:
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_successful_response(self, mock_get, mock_fetch_token):
        """Test successful fetch of commits and merge requests, normalized shape."""
        commits_response = _make_response(
            200,
            [
                {
                    "id": "abc123",
                    "message": "feat: add login",
                    "author_name": "Jane Doe",
                    "author_email": "jane@example.com",
                    "authored_date": "2024-06-15T10:00:00Z",
                },
                {
                    "id": "def456",
                    "message": "fix: resolve auth bug",
                    "author_name": "jane doe",
                    "author_email": "other@example.com",
                    "authored_date": "2024-06-16T11:00:00Z",
                },
            ],
        )
        mrs_response = _make_response(
            200,
            [
                {
                    "iid": 42,
                    "title": "Add authentication",
                    "state": "merged",
                    "created_at": "2024-06-14T09:00:00Z",
                    "author": {"username": "jane doe"},
                },
            ],
        )
        mock_get.side_effect = [commits_response, mrs_response]

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert "error" not in result
        assert result == {
            "commits": [
                {"sha": "abc123", "message": "feat: add login", "date": "2024-06-15T10:00:00Z"},
                {"sha": "def456", "message": "fix: resolve auth bug", "date": "2024-06-16T11:00:00Z"},
            ],
            "pull_requests": [
                {"number": 42, "title": "Add authentication", "state": "merged", "created_at": "2024-06-14T09:00:00Z"},
            ],
        }

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_commits_endpoint_construction(self, mock_get, mock_fetch_token):
        """Test the commits URL is built from base_url + API_PATH + the
        URL-encoded project path + the fixed endpoint suffix, exercising a
        project_path with subgroup slashes to confirm they get percent-encoded."""
        project_path = "group/subgroup/project"
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        tool_fn = build_gitlab_tool()
        tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=project_path,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        encoded_project_path = quote(project_path, safe="")
        assert "/" not in encoded_project_path.replace("%2F", "")  # sanity: slashes were encoded away
        expected_commits_url = (
            f"{FAKE_BASE_URL}{API_PATH}/projects/{encoded_project_path}/repository/commits"
        )
        commits_call_args, _ = mock_get.call_args_list[0]
        assert commits_call_args[0] == expected_commits_url

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_commits_request_params(self, mock_get, mock_fetch_token):
        """Test the commits call's params carry since and per_page=100."""
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        tool_fn = build_gitlab_tool()
        tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        _, commits_call_kwargs = mock_get.call_args_list[0]
        params = commits_call_kwargs["params"]
        assert params["since"] == FAKE_SINCE
        assert params["per_page"] == 100
        assert MAX_COMMITS == 100

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_commits_request_headers(self, mock_get, mock_fetch_token):
        """Test the commits call's headers are exactly PRIVATE-TOKEN — never Authorization."""
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        tool_fn = build_gitlab_tool()
        tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        _, commits_call_kwargs = mock_get.call_args_list[0]
        headers = commits_call_kwargs["headers"]
        assert headers == {"PRIVATE-TOKEN": "fake-token"}
        assert "Authorization" not in headers

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_request_timeout(self, mock_get, mock_fetch_token):
        """Test both the commits and merge-requests calls pass timeout=30."""
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        tool_fn = build_gitlab_tool()
        tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        _, commits_call_kwargs = mock_get.call_args_list[0]
        _, mrs_call_kwargs = mock_get.call_args_list[1]
        assert commits_call_kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS
        assert mrs_call_kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS
        assert REQUEST_TIMEOUT_SECONDS == 30

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_merge_requests_endpoint_construction(self, mock_get, mock_fetch_token):
        """Test the merge-requests URL is base_url + API_PATH + encoded project path + /merge_requests."""
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        tool_fn = build_gitlab_tool()
        tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        encoded_project_path = quote(FAKE_PROJECT_PATH, safe="")
        expected_mrs_url = f"{FAKE_BASE_URL}{API_PATH}/projects/{encoded_project_path}/merge_requests"
        mrs_call_args, _ = mock_get.call_args_list[1]
        assert mrs_call_args[0] == expected_mrs_url

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_merge_requests_request_params(self, mock_get, mock_fetch_token):
        """Test the merge-requests call's params carry the documented query shape."""
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        tool_fn = build_gitlab_tool()
        tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        _, mrs_call_kwargs = mock_get.call_args_list[1]
        params = mrs_call_kwargs["params"]
        assert params["author_username"] == FAKE_AUTHOR
        assert params["created_after"] == FAKE_SINCE
        assert params["state"] == "all"
        assert params["per_page"] == 50
        assert params["order_by"] == "updated_at"
        assert params["sort"] == "desc"
        assert MAX_MRS == 50

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_no_token_returns_auth_failed_without_any_request(self, mock_get, mock_fetch_token):
        """Test the auth-failure short-circuit happens before any HTTP call."""
        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert result == {"error": "GITLAB_AUTH_FAILED", "retryable": False}
        mock_get.assert_not_called()

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_rate_limit_on_commits(self, mock_get, mock_fetch_token):
        """Test HTTP 429 on the commits call returns rate limit error."""
        mock_get.return_value = _make_response(429)

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert result == {"error": "GITLAB_RATE_LIMIT", "retryable": True}

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_auth_failure_401_on_commits(self, mock_get, mock_fetch_token):
        """Test HTTP 401 on the commits call returns auth failure, non-retryable."""
        mock_get.return_value = _make_response(401)

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert result == {"error": "GITLAB_AUTH_FAILED", "retryable": False}

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_auth_failure_403_on_commits(self, mock_get, mock_fetch_token):
        """Test HTTP 403 on the commits call returns auth failure, non-retryable."""
        mock_get.return_value = _make_response(403)

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert result == {"error": "GITLAB_AUTH_FAILED", "retryable": False}

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_not_found_404_on_commits(self, mock_get, mock_fetch_token):
        """Test HTTP 404 on the commits call returns request-failed, retryable."""
        mock_get.return_value = _make_response(404)

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert result == {"error": "GITLAB_REQUEST_FAILED", "retryable": True}

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_network_failure_on_commits(self, mock_get, mock_fetch_token):
        """Test a network-level failure on the commits call returns request-failed, retryable."""
        mock_get.side_effect = requests.RequestException("connection reset")

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert result == {"error": "GITLAB_REQUEST_FAILED", "retryable": True}

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_rate_limit_on_merge_requests(self, mock_get, mock_fetch_token):
        """Test HTTP 429 on the merge-requests call returns rate limit error."""
        mock_get.side_effect = [_make_response(200, []), _make_response(429)]

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert result == {"error": "GITLAB_RATE_LIMIT", "retryable": True}

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_auth_failure_401_on_merge_requests(self, mock_get, mock_fetch_token):
        """Test HTTP 401 on the merge-requests call returns auth failure, non-retryable."""
        mock_get.side_effect = [_make_response(200, []), _make_response(401)]

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert result == {"error": "GITLAB_AUTH_FAILED", "retryable": False}

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_auth_failure_403_on_merge_requests(self, mock_get, mock_fetch_token):
        """Test HTTP 403 on the merge-requests call returns auth failure, non-retryable."""
        mock_get.side_effect = [_make_response(200, []), _make_response(403)]

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert result == {"error": "GITLAB_AUTH_FAILED", "retryable": False}

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_partial_failure_when_merge_requests_call_fails(self, mock_get, mock_fetch_token):
        """Test that a network failure fetching merge requests, after commits already
        succeeded, yields the partial-success shape rather than an error dict."""
        commits_response = _make_response(
            200,
            [
                {
                    "id": "abc123",
                    "message": "feat: add login",
                    "author_name": "Jane Doe",
                    "author_email": "jane@example.com",
                    "authored_date": "2024-06-15T10:00:00Z",
                },
            ],
        )
        mock_get.side_effect = [commits_response, requests.RequestException("mrs down")]

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert result == {
            "commits": [
                {"sha": "abc123", "message": "feat: add login", "date": "2024-06-15T10:00:00Z"},
            ],
            "pull_requests": [],
            "warning": "Failed to fetch merge requests",
        }

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_max_commits_limit(self, mock_get, mock_fetch_token):
        """Test that commits are capped at MAX_COMMITS."""
        commits_data = [
            {
                "id": f"sha{i}",
                "message": f"commit {i}",
                "author_name": FAKE_AUTHOR,
                "author_email": "jane@example.com",
                "authored_date": f"2024-06-{15 + i % 10:02d}T10:00:00Z",
            }
            for i in range(150)
        ]
        mock_get.side_effect = [_make_response(200, commits_data), _make_response(200, [])]

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert len(result["commits"]) == MAX_COMMITS

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_max_merge_requests_limit(self, mock_get, mock_fetch_token):
        """Test that merge requests are capped at MAX_MRS."""
        mrs_data = [
            {
                "iid": i,
                "title": f"MR {i}",
                "state": "opened",
                "created_at": f"2024-06-{15 + i % 10:02d}T10:00:00Z",
                "author": {"username": FAKE_AUTHOR},
            }
            for i in range(100)
        ]
        mock_get.side_effect = [_make_response(200, []), _make_response(200, mrs_data)]

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert len(result["pull_requests"]) == MAX_MRS

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_filters_commits_by_author_name_or_email(self, mock_get, mock_fetch_token):
        """Test commits are filtered client-side by author_name or author_email,
        with a mix of matches by name, by email, and non-matches."""
        commits_data = [
            {
                "id": "match-by-name",
                "message": "matches by name",
                "author_name": "Jane Doe",
                "author_email": "unrelated@example.com",
                "authored_date": "2024-06-15T10:00:00Z",
            },
            {
                "id": "match-by-email",
                "message": "matches by email",
                "author_name": "Someone Else",
                "author_email": "jane doe",
                "authored_date": "2024-06-16T10:00:00Z",
            },
            {
                "id": "no-match",
                "message": "does not match",
                "author_name": "Other Person",
                "author_email": "other@example.com",
                "authored_date": "2024-06-17T10:00:00Z",
            },
        ]
        mock_get.side_effect = [_make_response(200, commits_data), _make_response(200, [])]

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        shas = {commit["sha"] for commit in result["commits"]}
        assert shas == {"match-by-name", "match-by-email"}

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_filters_merge_requests_by_author_username(self, mock_get, mock_fetch_token):
        """Test merge requests are filtered client-side by author.username,
        with a mix of matching and non-matching usernames."""
        mrs_data = [
            {
                "iid": 1,
                "title": "My MR",
                "state": "opened",
                "created_at": "2024-06-15T10:00:00Z",
                "author": {"username": FAKE_AUTHOR},
            },
            {
                "iid": 2,
                "title": "Other MR",
                "state": "opened",
                "created_at": "2024-06-15T10:00:00Z",
                "author": {"username": "someone-else"},
            },
        ]
        mock_get.side_effect = [_make_response(200, []), _make_response(200, mrs_data)]

        tool_fn = build_gitlab_tool()
        result = tool_fn(
            repo_id=FAKE_REPO_ID,
            base_url=FAKE_BASE_URL,
            project_path=FAKE_PROJECT_PATH,
            author=FAKE_AUTHOR,
            since=FAKE_SINCE,
        )

        assert len(result["pull_requests"]) == 1
        assert result["pull_requests"][0]["title"] == "My MR"

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_certificate_verification_enabled_by_default(self, mock_get, mock_fetch_token):
        """Test that with GITLAB_SSL_VERIFY unset, both requests.get calls verify=True."""
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITLAB_SSL_VERIFY", None)
            tool_fn = build_gitlab_tool()
            tool_fn(
                repo_id=FAKE_REPO_ID,
                base_url=FAKE_BASE_URL,
                project_path=FAKE_PROJECT_PATH,
                author=FAKE_AUTHOR,
                since=FAKE_SINCE,
            )

        for _, kwargs in mock_get.call_args_list:
            assert kwargs.get("verify") is True


class TestGitlabSslVerifyEnvVar:
    """Unit tests for the `GITLAB_SSL_VERIFY` opt-out (self-signed instances).

    Requirement 10.3 of `.kiro/specs/gitlab-provider-support/` documents
    that some self-hosted GitLab instances present a self-signed
    certificate the user has explicitly chosen not to replace. Setting
    `GITLAB_SSL_VERIFY=false` disables verification for GitLab API calls
    only — the default (unset, or any value other than the literal
    "false") keeps verification enabled.
    """

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_ssl_verify_false_disables_verification_on_both_calls(self, mock_get, mock_fetch_token):
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        with patch.dict(os.environ, {"GITLAB_SSL_VERIFY": "false"}):
            tool_fn = build_gitlab_tool()
            tool_fn(
                repo_id=FAKE_REPO_ID,
                base_url=FAKE_BASE_URL,
                project_path=FAKE_PROJECT_PATH,
                author=FAKE_AUTHOR,
                since=FAKE_SINCE,
            )

        for _, kwargs in mock_get.call_args_list:
            assert kwargs.get("verify") is False

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_ssl_verify_false_is_case_insensitive(self, mock_get, mock_fetch_token):
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        with patch.dict(os.environ, {"GITLAB_SSL_VERIFY": "FALSE"}):
            tool_fn = build_gitlab_tool()
            tool_fn(
                repo_id=FAKE_REPO_ID,
                base_url=FAKE_BASE_URL,
                project_path=FAKE_PROJECT_PATH,
                author=FAKE_AUTHOR,
                since=FAKE_SINCE,
            )

        for _, kwargs in mock_get.call_args_list:
            assert kwargs.get("verify") is False

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_unrecognized_value_keeps_verification_enabled(self, mock_get, mock_fetch_token):
        """A typo or unexpected value (not the literal "false") must fail safe to verify=True."""
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        with patch.dict(os.environ, {"GITLAB_SSL_VERIFY": "no"}):
            tool_fn = build_gitlab_tool()
            tool_fn(
                repo_id=FAKE_REPO_ID,
                base_url=FAKE_BASE_URL,
                project_path=FAKE_PROJECT_PATH,
                author=FAKE_AUTHOR,
                since=FAKE_SINCE,
            )

        for _, kwargs in mock_get.call_args_list:
            assert kwargs.get("verify") is True

    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token", return_value="fake-token")
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_ssl_verify_true_explicit_keeps_verification_enabled(self, mock_get, mock_fetch_token):
        mock_get.side_effect = [_make_response(200, []), _make_response(200, [])]

        with patch.dict(os.environ, {"GITLAB_SSL_VERIFY": "true"}):
            tool_fn = build_gitlab_tool()
            tool_fn(
                repo_id=FAKE_REPO_ID,
                base_url=FAKE_BASE_URL,
                project_path=FAKE_PROJECT_PATH,
                author=FAKE_AUTHOR,
                since=FAKE_SINCE,
            )

        for _, kwargs in mock_get.call_args_list:
            assert kwargs.get("verify") is True
