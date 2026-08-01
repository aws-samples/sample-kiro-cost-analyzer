"""Tests for correlation_worker Lambda."""

import json
from unittest.mock import MagicMock, patch

import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from handlers.correlation_worker import (
    lambda_handler,
    _clear_pending_flag,
    _coerce_bilingual_insights,
    _invoke_agent,
)


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("ANALYTICS_TABLE", "test-analytics")
    monkeypatch.setenv("CORRELATION_AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:sa-east-1:123456789012:runtime/TestAgent")


@pytest.fixture
def worker_event():
    return {
        "userId": "user1",
        "startDate": "2026-04-28",
        "endDate": "2026-05-05",
        "gitUsername": "octocat",
        "repos": [{"owner": "org", "repo": "repo1"}],
        "token": "ghp_test_token",
    }


class TestWorkerLambda:
    def test_successful_invocation(self, mock_env, worker_event):
        with patch("handlers.correlation_worker.boto3.resource") as mock_resource, \
             patch("handlers.correlation_worker.boto3.client") as mock_client, \
             patch("handlers.correlation_worker.AnalyticsRepository") as MockRepo:

            # Mock DynamoDB table
            mock_table = MagicMock()
            mock_dynamo = MagicMock()
            mock_dynamo.Table.return_value = mock_table
            mock_resource.return_value = mock_dynamo

            # Mock AgentCore response
            mock_agentcore = MagicMock()
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({
                "impactScore": 75,
                "impactLevel": "high",
                "correlations": [],
                "insights": ["Test insight"],
                "tokensUsed": 1500,
            }).encode("utf-8")
            mock_agentcore.invoke_agent_runtime.return_value = {"response": mock_response}
            mock_client.return_value = mock_agentcore

            # Mock analytics repo
            mock_repo = MockRepo.return_value

            result = lambda_handler(worker_event, None)

            assert result["status"] == "completed"
            assert result["userId"] == "user1"
            mock_repo.put_analysis.assert_called_once()
            mock_table.delete_item.assert_called_once_with(
                Key={"PK": "USER#user1", "SK": "ANALYSIS_PENDING"}
            )

    def test_unconfigured_runtime_arn_fails_clean(self, monkeypatch, worker_event):
        """When CORRELATION_AGENT_RUNTIME_ARN is the 'NONE' placeholder (agent not
        yet deployed), the worker must NOT call AgentCore — it fails fast, logs,
        and still clears the pending flag. Guards the regression where the worker
        invoked a stale/non-existent runtime ARN.
        """
        monkeypatch.setenv("ANALYTICS_TABLE", "test-analytics")
        monkeypatch.setenv("CORRELATION_AGENT_RUNTIME_ARN", "NONE")

        with patch("handlers.correlation_worker.boto3.resource") as mock_resource, \
             patch("handlers.correlation_worker.boto3.client") as mock_client, \
             patch("handlers.correlation_worker.AnalyticsRepository") as MockRepo:

            mock_table = MagicMock()
            mock_dynamo = MagicMock()
            mock_dynamo.Table.return_value = mock_table
            mock_resource.return_value = mock_dynamo

            result = lambda_handler(worker_event, None)

            assert result["status"] == "completed"
            # AgentCore must never be invoked when the ARN is unconfigured.
            mock_client.assert_not_called()
            MockRepo.return_value.put_analysis.assert_not_called()
            # Pending flag is still cleared so the UI doesn't hang on "processing".
            mock_table.delete_item.assert_called_once_with(
                Key={"PK": "USER#user1", "SK": "ANALYSIS_PENDING"}
            )

    def test_agent_failure_clears_pending(self, mock_env, worker_event):
        with patch("handlers.correlation_worker.boto3.resource") as mock_resource, \
             patch("handlers.correlation_worker.boto3.client") as mock_client, \
             patch("handlers.correlation_worker.AnalyticsRepository") as MockRepo:

            # Mock DynamoDB table
            mock_table = MagicMock()
            mock_dynamo = MagicMock()
            mock_dynamo.Table.return_value = mock_table
            mock_resource.return_value = mock_dynamo

            # Mock AgentCore failure
            mock_agentcore = MagicMock()
            mock_agentcore.invoke_agent_runtime.side_effect = RuntimeError("Agent crashed")
            mock_client.return_value = mock_agentcore

            result = lambda_handler(worker_event, None)

            assert result["status"] == "completed"
            # Pending flag should still be cleared even on failure
            mock_table.delete_item.assert_called_once_with(
                Key={"PK": "USER#user1", "SK": "ANALYSIS_PENDING"}
            )
            # Analysis should NOT be persisted on failure
            MockRepo.return_value.put_analysis.assert_not_called()


class TestClearPendingFlag:
    def test_deletes_pending_item(self):
        table = MagicMock()
        _clear_pending_flag(table, "user1")

        table.delete_item.assert_called_once_with(
            Key={"PK": "USER#user1", "SK": "ANALYSIS_PENDING"}
        )

    def test_handles_delete_error_gracefully(self):
        from botocore.exceptions import ClientError
        table = MagicMock()
        table.delete_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": ""}},
            "DeleteItem",
        )

        # Should not raise
        _clear_pending_flag(table, "user1")


class TestCoerceBilingualInsights:
    """Worker-side coercion runs at WRITE time so the persisted record already
    has the canonical bilingual shape; we no longer rely on read-side coercion
    in `AnalyticsRepository` to fix legacy items.

    Validates: Requirements 8.2, 8.8.
    """

    def test_modern_dict_preserved(self):
        raw = {"en": ["a"], "pt-BR": ["a-pt"]}
        assert _coerce_bilingual_insights(raw) == {"en": ["a"], "pt-BR": ["a-pt"]}

    def test_legacy_list_treated_as_pt_br(self):
        # Defensive: an old agent that returns insights as List<String>.
        assert _coerce_bilingual_insights(["legacy"]) == {"en": [], "pt-BR": ["legacy"]}

    def test_missing_yields_empty_bilingual_map(self):
        assert _coerce_bilingual_insights(None) == {"en": [], "pt-BR": []}
        assert _coerce_bilingual_insights("unexpected") == {"en": [], "pt-BR": []}

    def test_partial_dict_fills_missing_locale(self):
        # Agent returned only `en` — `pt-BR` defaults to empty list.
        assert _coerce_bilingual_insights({"en": ["only-en"]}) == {"en": ["only-en"], "pt-BR": []}


class TestWorkerPersistsBilingualShape:
    """Validates: Requirements 8.2, 8.8 — the persisted analysis_record always
    carries `insights` as the bilingual map, regardless of what the agent
    emitted (modern dict, legacy list, missing field).
    """

    def _run_worker_with_agent_payload(self, mock_env, worker_event, agent_payload: dict):
        with patch("handlers.correlation_worker.boto3.resource") as mock_resource, \
             patch("handlers.correlation_worker.boto3.client") as mock_client, \
             patch("handlers.correlation_worker.AnalyticsRepository") as MockRepo:

            mock_dynamo = MagicMock()
            mock_dynamo.Table.return_value = MagicMock()
            mock_resource.return_value = mock_dynamo

            mock_agentcore = MagicMock()
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(agent_payload).encode("utf-8")
            mock_agentcore.invoke_agent_runtime.return_value = {"response": mock_response}
            mock_client.return_value = mock_agentcore

            mock_repo = MockRepo.return_value

            lambda_handler(worker_event, None)

            assert mock_repo.put_analysis.call_count == 1
            _user_id, persisted = mock_repo.put_analysis.call_args[0]
            return persisted

    def test_persists_modern_bilingual_map(self, mock_env, worker_event):
        agent_payload = {
            "impactScore": 75,
            "impactLevel": "high",
            "correlations": [],
            "insights": {"en": ["Insight EN"], "pt-BR": ["Insight pt-BR"]},
            "tokensUsed": 1500,
        }
        persisted = self._run_worker_with_agent_payload(mock_env, worker_event, agent_payload)

        assert persisted["insights"] == {"en": ["Insight EN"], "pt-BR": ["Insight pt-BR"]}

    def test_persists_legacy_list_as_pt_br(self, mock_env, worker_event):
        agent_payload = {
            "impactScore": 60,
            "impactLevel": "moderate",
            "correlations": [],
            "insights": ["Legacy 1", "Legacy 2"],
        }
        persisted = self._run_worker_with_agent_payload(mock_env, worker_event, agent_payload)

        assert persisted["insights"] == {"en": [], "pt-BR": ["Legacy 1", "Legacy 2"]}

    def test_persists_missing_field_as_empty_bilingual_map(self, mock_env, worker_event):
        agent_payload = {
            "impactScore": 0,
            "impactLevel": "low",
            "correlations": [],
        }
        persisted = self._run_worker_with_agent_payload(mock_env, worker_event, agent_payload)

        assert persisted["insights"] == {"en": [], "pt-BR": []}


class TestInvokeAgentPayloadForwarding:
    """Concrete examples complementing the general round-trip property
    (Property 12, in `tests/test_gitlab_provider_properties.py`). These
    fix a specific, provider-tagged `repos` shape rather than an arbitrary
    one, so a regression that mangles a *realistic* descriptor is caught
    even if a future change to the property's generator loosens it.

    Validates: Requirements 7.5
    """

    def test_provider_tagged_repos_forwarded_verbatim(self, mock_env):
        """`_invoke_agent` must pass `repos` through unchanged: no
        transformation, no filtering, no defaulting (task 11.1).
        """
        repos = [
            {
                "repoId": "a1b2c3d4",
                "provider": "github",
                "owner": "octo-org",
                "repo": "octo-repo",
                "gitUsername": "octocat",
            },
            {
                "repoId": "e5f6a7b8",
                "provider": "gitlab",
                "baseUrl": "https://gitlab.example.com",
                "projectPath": "group/subgroup/project",
                "gitUsername": "gitlab-user",
            },
        ]

        with patch("handlers.correlation_worker.boto3.client") as mock_client:
            mock_agentcore = MagicMock()
            mock_response = MagicMock()
            mock_response.read.return_value = b"{}"
            mock_agentcore.invoke_agent_runtime.return_value = {"response": mock_response}
            mock_client.return_value = mock_agentcore

            _invoke_agent(
                user_id="user1",
                start_date="2026-04-28",
                end_date="2026-05-05",
                git_username="octocat",
                repos=repos,
            )

            _, call_kwargs = mock_agentcore.invoke_agent_runtime.call_args
            sent_payload = json.loads(call_kwargs["payload"].decode("utf-8"))

            # Same descriptors, same fields per descriptor, same order —
            # exactly as constructed above, nothing added or dropped.
            assert sent_payload["repos"] == repos
            assert sent_payload["gitUsername"] == "octocat"


class TestInvokeAgentUnconfiguredRuntimeArnGuard:
    """The unconfigured-runtime-ARN guard in `_invoke_agent`: a missing or
    placeholder `CORRELATION_AGENT_RUNTIME_ARN` must raise a clear
    `RuntimeError` and never reach `boto3.client("bedrock-agentcore")`.

    Validates: Requirements 7.5
    """

    def test_missing_arn_raises_and_never_calls_boto3_client(self, monkeypatch):
        monkeypatch.delenv("CORRELATION_AGENT_RUNTIME_ARN", raising=False)

        with patch("handlers.correlation_worker.boto3.client") as mock_client:
            with pytest.raises(RuntimeError, match="CORRELATION_AGENT_RUNTIME_ARN"):
                _invoke_agent(
                    user_id="user1",
                    start_date="2026-04-28",
                    end_date="2026-05-05",
                    git_username="octocat",
                    repos=[],
                )

            mock_client.assert_not_called()

    def test_none_placeholder_arn_raises_and_never_calls_boto3_client(self, monkeypatch):
        monkeypatch.setenv("CORRELATION_AGENT_RUNTIME_ARN", "NONE")

        with patch("handlers.correlation_worker.boto3.client") as mock_client:
            with pytest.raises(RuntimeError, match="CORRELATION_AGENT_RUNTIME_ARN"):
                _invoke_agent(
                    user_id="user1",
                    start_date="2026-04-28",
                    end_date="2026-05-05",
                    git_username="octocat",
                    repos=[],
                )

            mock_client.assert_not_called()
