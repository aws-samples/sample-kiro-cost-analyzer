"""Tests for agent_correlation_handler (Group 6) — async pattern."""

import json
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from handlers.agent_correlation_handler import (
    handle_agent_correlation,
    _format_response,
    build_repo_descriptors,
    resolve_token_availability,
    select_token_missing_slug,
)


@pytest.fixture
def mock_repos():
    with patch("handlers.agent_correlation_handler.AnalyticsRepository") as MockAnalytics, \
         patch("handlers.agent_correlation_handler.GitRepository") as MockGit:
        analytics_repo = MockAnalytics.return_value
        git_repo = MockGit.return_value
        yield analytics_repo, git_repo


@pytest.fixture
def mock_table():
    """Mock DynamoDB table for pending flag operations."""
    table = MagicMock()
    table.get_item.return_value = {}
    return table


class TestAuthorization:
    def test_any_authenticated_user_can_view_any_user(self, mock_repos):
        analytics_repo, git_repo = mock_repos
        git_repo.list_user_mappings.return_value = []

        result = handle_agent_correlation(
            "other-user",
            {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            {"userId": "manager1", "groups": []},
        )
        assert result.get("_status_code", 200) != 403
        assert result.get("error") != "Forbidden"


class TestCacheBehavior:
    def test_returns_cache_when_valid(self, mock_repos):
        analytics_repo, git_repo = mock_repos
        git_repo.list_user_mappings.return_value = [{"provider": "github", "gitUsername": "octocat"}]
        analytics_repo.get_latest_analysis.return_value = {
            "impactScore": 72,
            "impactLevel": "high",
            "correlations": [],
            "insights": ["Insight cached"],
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "analyzedAt": "2026-05-05T14:30:00Z",
        }

        result = handle_agent_correlation(
            "user1",
            {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            {"userId": "user1", "groups": ["Admins"]},
        )

        assert result["cached"] is True
        assert result["impactScore"] == 72
        assert result["status"] == "ready"

    def test_force_refresh_dispatches_worker(self, mock_repos):
        analytics_repo, git_repo = mock_repos
        git_repo.list_user_mappings.return_value = [{"provider": "github", "gitUsername": "octocat"}]
        git_repo.list_repo_configs.return_value = []

        with patch("handlers.agent_correlation_handler._is_pending", return_value=False), \
             patch("handlers.agent_correlation_handler.resolve_token_availability", return_value=([{"repoId": "x"}], [])), \
             patch("handlers.agent_correlation_handler._set_pending_flag"), \
             patch("handlers.agent_correlation_handler._dispatch_worker") as mock_dispatch:

            result = handle_agent_correlation(
                "user1",
                {"startDate": "2026-04-28", "endDate": "2026-05-05", "forceRefresh": "true"},
                {"userId": "user1", "groups": ["Admins"]},
            )

            analytics_repo.get_latest_analysis.assert_not_called()
            mock_dispatch.assert_called_once()
            assert result["status"] == "processing"


class TestAsyncDispatch:
    def test_dispatches_worker_when_no_cache(self, mock_repos):
        analytics_repo, git_repo = mock_repos
        git_repo.list_user_mappings.return_value = [{"provider": "github", "gitUsername": "octocat"}]
        git_repo.list_repo_configs.return_value = [
            {"PK": "GITREPO#abc12345", "provider": "github", "url": "https://github.com/org/repo1"}
        ]
        analytics_repo.get_latest_analysis.return_value = None

        with patch("handlers.agent_correlation_handler._is_pending", return_value=False), \
             patch("handlers.agent_correlation_handler.resolve_token_availability") as mock_resolve, \
             patch("handlers.agent_correlation_handler._set_pending_flag") as mock_set_pending, \
             patch("handlers.agent_correlation_handler._dispatch_worker") as mock_dispatch:

            descriptor = {"repoId": "abc12345", "provider": "github", "gitUsername": "octocat", "owner": "org", "repo": "repo1"}
            mock_resolve.return_value = ([descriptor], [])

            result = handle_agent_correlation(
                "user1",
                {"startDate": "2026-04-28", "endDate": "2026-05-05"},
                {"userId": "user1", "groups": ["Admins"]},
            )

            mock_set_pending.assert_called_once()
            mock_dispatch.assert_called_once_with(
                "user1", "2026-04-28", "2026-05-05", "octocat",
                [descriptor],
            )
            assert result["status"] == "processing"
            assert result["userId"] == "user1"

    def test_returns_processing_when_already_pending(self, mock_repos):
        analytics_repo, git_repo = mock_repos
        git_repo.list_user_mappings.return_value = [{"provider": "github", "gitUsername": "octocat"}]
        analytics_repo.get_latest_analysis.return_value = None

        with patch("handlers.agent_correlation_handler._is_pending", return_value=True), \
             patch("handlers.agent_correlation_handler._dispatch_worker") as mock_dispatch:

            result = handle_agent_correlation(
                "user1",
                {"startDate": "2026-04-28", "endDate": "2026-05-05"},
                {"userId": "user1", "groups": ["Admins"]},
            )

            mock_dispatch.assert_not_called()
            assert result["status"] == "processing"
            assert result["insights"] == {"en": [], "pt-BR": []}
            assert "message" not in result

    def test_does_not_dispatch_without_token(self, mock_repos):
        analytics_repo, git_repo = mock_repos
        git_repo.list_user_mappings.return_value = [{"provider": "github", "gitUsername": "octocat"}]
        git_repo.list_repo_configs.return_value = [
            {"PK": "GITREPO#abc12345", "provider": "github", "url": "https://github.com/org/repo1"}
        ]
        analytics_repo.get_latest_analysis.return_value = None

        with patch("handlers.agent_correlation_handler._is_pending", return_value=False), \
             patch("handlers.agent_correlation_handler.resolve_token_availability") as mock_resolve, \
             patch("handlers.agent_correlation_handler._dispatch_worker") as mock_dispatch:

            missing_descriptor = {"repoId": "abc12345", "provider": "github", "gitUsername": "octocat", "owner": "org", "repo": "repo1"}
            mock_resolve.return_value = ([], [missing_descriptor])

            result = handle_agent_correlation(
                "user1",
                {"startDate": "2026-04-28", "endDate": "2026-05-05"},
                {"userId": "user1", "groups": ["Admins"]},
            )

            mock_dispatch.assert_not_called()
            assert result["impactScore"] is None
            assert result["status"] == "GITHUB_TOKEN_MISSING"
            assert result["insights"] == {"en": [], "pt-BR": []}
            assert "message" not in result


class TestNoMapping:
    def test_user_without_mapping_returns_status_slug(self, mock_repos):
        analytics_repo, git_repo = mock_repos
        git_repo.list_user_mappings.return_value = []

        result = handle_agent_correlation(
            "user1",
            {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            {"userId": "user1", "groups": ["Admins"]},
        )

        assert result["impactScore"] is None
        assert result["status"] == "GIT_MAPPING_MISSING"
        assert result["insights"] == {"en": [], "pt-BR": []}
        assert "message" not in result


class TestPendingFlag:
    def test_is_pending_returns_false_when_no_item(self):
        from handlers.agent_correlation_handler import _is_pending
        table = MagicMock()
        table.get_item.return_value = {}

        assert _is_pending(table, "user1", "2026-04-28", "2026-05-05") is False

    def test_is_pending_returns_true_when_valid_item(self):
        from handlers.agent_correlation_handler import _is_pending
        table = MagicMock()
        table.get_item.return_value = {
            "Item": {
                "PK": "USER#user1",
                "SK": "ANALYSIS_PENDING",
                "TTL": int(time.time()) + 300,
            }
        }

        assert _is_pending(table, "user1", "2026-04-28", "2026-05-05") is True

    def test_is_pending_returns_false_when_expired(self):
        from handlers.agent_correlation_handler import _is_pending
        table = MagicMock()
        table.get_item.return_value = {
            "Item": {
                "PK": "USER#user1",
                "SK": "ANALYSIS_PENDING",
                "TTL": int(time.time()) - 100,
            }
        }

        assert _is_pending(table, "user1", "2026-04-28", "2026-05-05") is False


class TestFormatResponse:
    def test_all_keys_present_with_bilingual_insights(self):
        analysis = {
            "impactScore": 72,
            "impactLevel": "high",
            "correlations": [{"promptSummary": "test", "gitActivity": "commit", "confidence": 0.8, "type": "prompt_to_commit"}],
            "insights": {"en": ["Insight 1"], "pt-BR": ["Insight 1 pt"]},
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "analyzedAt": "2026-05-05T14:30:00Z",
        }

        result = _format_response("user1", analysis, cached=False)

        assert result["userId"] == "user1"
        assert result["impactScore"] == 72
        assert result["impactLevel"] == "high"
        assert result["correlations"] == analysis["correlations"]
        assert result["insights"] == {"en": ["Insight 1"], "pt-BR": ["Insight 1 pt"]}
        assert result["period"] == {"startDate": "2026-04-28", "endDate": "2026-05-05"}
        assert result["analyzedAt"] == "2026-05-05T14:30:00Z"
        assert result["cached"] is False
        assert result["status"] == "ready"

    def test_legacy_list_insights_coerced_to_bilingual_map(self):
        """A legacy ``insights: List<String>`` is read-coerced to
        ``{"en": [], "pt-BR": <legacy list>}``."""
        analysis = {
            "impactScore": 50,
            "impactLevel": "moderate",
            "correlations": [],
            "insights": ["Legacy insight 1", "Legacy insight 2"],
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "analyzedAt": "2026-05-05T14:30:00Z",
        }

        result = _format_response("user1", analysis, cached=True)

        assert result["insights"] == {
            "en": [],
            "pt-BR": ["Legacy insight 1", "Legacy insight 2"],
        }
        assert "en" in result["insights"]
        assert "pt-BR" in result["insights"]

    def test_missing_insights_yields_empty_bilingual_map(self):
        analysis = {
            "impactScore": None,
            "impactLevel": None,
            "correlations": [],
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "analyzedAt": None,
        }

        result = _format_response("user1", analysis, cached=False)

        assert result["insights"] == {"en": [], "pt-BR": []}

    def test_message_field_absent_from_response_body(self):
        """Per Requirements 3.8/8.8, ``message`` prose is dropped from the
        response body. An operator-context ``message`` argument is accepted
        and logged but never echoed back."""
        analysis = {
            "impactScore": 72,
            "impactLevel": "high",
            "correlations": [],
            "insights": {"en": ["x"], "pt-BR": ["x"]},
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "analyzedAt": "2026-05-05T14:30:00Z",
        }

        result = _format_response(
            "user1",
            analysis,
            cached=False,
            message="for ops only — should not surface in the response",
        )

        assert "message" not in result

    def test_status_slug_passes_through_when_provided(self):
        """Optional ``status`` argument is included in the response (used by
        non-success branches once task 12.2 wires them)."""
        analysis = {
            "impactScore": None,
            "impactLevel": None,
            "correlations": [],
            "insights": {"en": [], "pt-BR": []},
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "analyzedAt": None,
        }

        result = _format_response(
            "user1",
            analysis,
            cached=False,
            status="GIT_MAPPING_MISSING",
        )

        assert result["status"] == "GIT_MAPPING_MISSING"
        assert result["insights"] == {"en": [], "pt-BR": []}
        assert "message" not in result

    def test_default_status_is_ready_when_status_is_none(self):
        analysis = {
            "impactScore": 30,
            "impactLevel": "moderate",
            "correlations": [],
            "insights": {"en": [], "pt-BR": []},
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "analyzedAt": "2026-05-05T14:30:00Z",
        }

        result = _format_response("user1", analysis, cached=False)

        assert result["status"] == "ready"


# Feature: agent-git-correlation, Property 9: Response Contract Completeness
class TestResponseContractProperty:
    """Property 9: Response Contract Completeness.

    For any successful analysis (cached or fresh), _format_response SHALL produce
    a dict containing ALL of: userId, status, impactScore, impactLevel, correlations,
    insights, period, analyzedAt, and cached.

    **Validates: Requirements 3.6, 3.8**
    """

    @given(
        impact_score=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
        impact_level=st.sampled_from(["low", "moderate", "high", "veryHigh"]),
        num_correlations=st.integers(min_value=0, max_value=5),
        num_insights=st.integers(min_value=0, max_value=5),
        cached=st.booleans(),
    )
    @settings(max_examples=20)
    def test_all_required_keys_present(self, impact_score, impact_level, num_correlations, num_insights, cached):
        """All required keys present in response."""
        analysis = {
            "impactScore": impact_score,
            "impactLevel": impact_level,
            "correlations": [
                {"promptSummary": f"p{i}", "gitActivity": f"g{i}", "confidence": 0.8, "type": "prompt_to_commit"}
                for i in range(num_correlations)
            ],
            "insights": [f"insight {i}" for i in range(num_insights)],
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "analyzedAt": "2026-05-05T14:30:00Z",
        }

        result = _format_response("user1", analysis, cached=cached)

        required_keys = {"userId", "status", "impactScore", "impactLevel", "correlations", "insights", "period", "analyzedAt", "cached"}
        assert required_keys.issubset(set(result.keys()))
        assert isinstance(result["correlations"], list)
        # 12.1: insights is now the bilingual map shape with both keys present.
        assert isinstance(result["insights"], dict)
        assert "en" in result["insights"] and "pt-BR" in result["insights"]
        assert isinstance(result["insights"]["en"], list)
        assert isinstance(result["insights"]["pt-BR"], list)
        assert isinstance(result["cached"], bool)
        assert result["status"] == "ready"


class TestBuildRepoDescriptorsExample:
    """Example test for ``build_repo_descriptors`` (task 10.8).

    Fixed set of repo_configs mixing github and gitlab, plus one
    unsupported provider, asserting the exact descriptor list and the
    exact excluded list with reasons.
    """

    def test_mixed_providers_and_unsupported_provider(self):
        repo_configs = [
            {
                "PK": "GITREPO#aaaaaaaa",
                "provider": "github",
                "url": "https://github.com/org/repo1",
            },
            {
                "PK": "GITREPO#bbbbbbbb",
                "provider": "gitlab",
                "url": "https://gitlab.com/group/subgroup/repo2",
            },
            {
                "PK": "GITREPO#cccccccc",
                "provider": "bitbucket",
                "url": "https://bitbucket.org/org/repo3",
            },
        ]
        mappings = [
            {"provider": "github", "gitUsername": "octocat"},
            {"provider": "gitlab", "gitUsername": "gluser"},
        ]

        descriptors, excluded = build_repo_descriptors(repo_configs, mappings)

        assert descriptors == [
            {
                "repoId": "aaaaaaaa",
                "provider": "github",
                "gitUsername": "octocat",
                "owner": "org",
                "repo": "repo1",
            },
            {
                "repoId": "bbbbbbbb",
                "provider": "gitlab",
                "gitUsername": "gluser",
                "baseUrl": "https://gitlab.com",
                "projectPath": "group/subgroup/repo2",
            },
        ]
        assert excluded == [
            {
                "repoId": "cccccccc",
                "provider": "bitbucket",
                "reason": "UNSUPPORTED_PROVIDER",
            },
        ]

    def test_unparseable_url_and_no_user_mapping_reasons(self):
        """Round out the exclusion reasons: UNPARSEABLE_URL and
        NO_USER_MAPPING, each landing in exactly one list."""
        repo_configs = [
            {
                "PK": "GITREPO#dddddddd",
                "provider": "github",
                "url": "not-a-valid-url",
            },
            {
                "PK": "GITREPO#eeeeeeee",
                "provider": "gitlab",
                "url": "https://gitlab.com/group/repo3",
            },
        ]
        # No gitlab mapping at all — the gitlab repo has an unresolved provider.
        mappings = [{"provider": "github", "gitUsername": "octocat"}]

        descriptors, excluded = build_repo_descriptors(repo_configs, mappings)

        assert descriptors == []
        assert excluded == [
            {"repoId": "dddddddd", "provider": "github", "reason": "UNPARSEABLE_URL"},
            {"repoId": "eeeeeeee", "provider": "gitlab", "reason": "NO_USER_MAPPING"},
        ]


class TestGitMappingMissingBranch:
    """**Validates: Requirements 7.4**

    IF the user has no Git mappings for any provider, THEN THE
    Correlation_Handler SHALL return the ``GIT_MAPPING_MISSING`` Status_Slug.
    """

    def test_zero_mappings_returns_git_mapping_missing_slug(self, mock_repos):
        analytics_repo, git_repo = mock_repos
        git_repo.list_user_mappings.return_value = []

        result = handle_agent_correlation(
            "user1",
            {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            {"userId": "user1", "groups": ["Admins"]},
        )

        assert result["status"] == "GIT_MAPPING_MISSING"
        assert result["impactScore"] is None
        assert result["cached"] is False
        # No lookup of repo configs or tokens should happen once mappings are absent.
        git_repo.list_repo_configs.assert_not_called()
        analytics_repo.get_latest_analysis.assert_not_called()


class TestTokenMissingSlugPerProvider:
    """Token-missing branches per provider (task 10.8).

    When no repository has a resolvable token, ``GITHUB_TOKEN_MISSING`` is
    returned in a github-only scenario and ``GITLAB_TOKEN_MISSING`` in a
    gitlab-only scenario.
    """

    def test_select_token_missing_slug_github_only(self):
        missing = [
            {"repoId": "aaaaaaaa", "provider": "github"},
            {"repoId": "bbbbbbbb", "provider": "github"},
        ]

        assert select_token_missing_slug(missing) == "GITHUB_TOKEN_MISSING"

    def test_select_token_missing_slug_gitlab_only(self):
        missing = [{"repoId": "cccccccc", "provider": "gitlab"}]

        assert select_token_missing_slug(missing) == "GITLAB_TOKEN_MISSING"

    def test_resolve_token_availability_github_only_all_missing(self):
        ssm_client = MagicMock()
        ssm_client.exceptions.ParameterNotFound = Exception
        ssm_client.get_parameter.side_effect = ssm_client.exceptions.ParameterNotFound

        descriptors = [
            {"repoId": "aaaaaaaa", "provider": "github"},
            {"repoId": "bbbbbbbb", "provider": "github"},
        ]

        available, missing = resolve_token_availability(descriptors, ssm_client=ssm_client)

        assert available == []
        assert missing == descriptors
        assert select_token_missing_slug(missing) == "GITHUB_TOKEN_MISSING"

    def test_resolve_token_availability_gitlab_only_all_missing(self):
        ssm_client = MagicMock()
        ssm_client.exceptions.ParameterNotFound = Exception
        ssm_client.get_parameter.side_effect = ssm_client.exceptions.ParameterNotFound

        descriptors = [{"repoId": "cccccccc", "provider": "gitlab"}]

        available, missing = resolve_token_availability(descriptors, ssm_client=ssm_client)

        assert available == []
        assert missing == descriptors
        assert select_token_missing_slug(missing) == "GITLAB_TOKEN_MISSING"

    def test_handler_returns_github_token_missing_for_github_only_repos(self, mock_repos):
        analytics_repo, git_repo = mock_repos
        git_repo.list_user_mappings.return_value = [
            {"provider": "github", "gitUsername": "octocat"}
        ]
        git_repo.list_repo_configs.return_value = [
            {"PK": "GITREPO#aaaaaaaa", "provider": "github", "url": "https://github.com/org/repo1"}
        ]
        analytics_repo.get_latest_analysis.return_value = None

        missing_descriptor = {
            "repoId": "aaaaaaaa",
            "provider": "github",
            "gitUsername": "octocat",
            "owner": "org",
            "repo": "repo1",
        }

        with patch("handlers.agent_correlation_handler._is_pending", return_value=False), \
             patch("handlers.agent_correlation_handler.resolve_token_availability", return_value=([], [missing_descriptor])), \
             patch("handlers.agent_correlation_handler._dispatch_worker") as mock_dispatch:

            result = handle_agent_correlation(
                "user1",
                {"startDate": "2026-04-28", "endDate": "2026-05-05"},
                {"userId": "user1", "groups": ["Admins"]},
            )

            mock_dispatch.assert_not_called()
            assert result["status"] == "GITHUB_TOKEN_MISSING"
            assert result["impactScore"] is None

    def test_handler_returns_gitlab_token_missing_for_gitlab_only_repos(self, mock_repos):
        analytics_repo, git_repo = mock_repos
        git_repo.list_user_mappings.return_value = [
            {"provider": "gitlab", "gitUsername": "glabuser"}
        ]
        git_repo.list_repo_configs.return_value = [
            {"PK": "GITREPO#cccccccc", "provider": "gitlab", "url": "https://gitlab.com/group/repo3"}
        ]
        analytics_repo.get_latest_analysis.return_value = None

        missing_descriptor = {
            "repoId": "cccccccc",
            "provider": "gitlab",
            "gitUsername": "glabuser",
            "baseUrl": "https://gitlab.com",
            "projectPath": "group/repo3",
        }

        with patch("handlers.agent_correlation_handler._is_pending", return_value=False), \
             patch("handlers.agent_correlation_handler.resolve_token_availability", return_value=([], [missing_descriptor])), \
             patch("handlers.agent_correlation_handler._dispatch_worker") as mock_dispatch:

            result = handle_agent_correlation(
                "user1",
                {"startDate": "2026-04-28", "endDate": "2026-05-05"},
                {"userId": "user1", "groups": ["Admins"]},
            )

            mock_dispatch.assert_not_called()
            assert result["status"] == "GITLAB_TOKEN_MISSING"
            assert result["impactScore"] is None
