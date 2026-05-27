"""Tests for correlation_worker Lambda."""

import json
from unittest.mock import MagicMock, patch

import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from handlers.correlation_worker import lambda_handler, _clear_pending_flag, _coerce_bilingual_insights


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("ANALYTICS_TABLE", "test-analytics")
    monkeypatch.setenv("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:sa-east-1:123456789012:runtime/TestAgent")


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
