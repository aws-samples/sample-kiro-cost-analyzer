"""Tests for Kiro Data Tool (agent/app/GitCorrelationAgent/tools/kiro_data.py)."""

import sys
import os
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent", "app", "GitCorrelationAgent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agent.app.GitCorrelationAgent.tools.kiro_data import build_kiro_tool, _truncate


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_exact_limit_unchanged(self):
        text = "a" * 500
        assert _truncate(text) == text

    def test_long_text_truncated(self):
        text = "a" * 600
        result = _truncate(text)
        assert len(result) == 503  # 500 + "..."
        assert result.endswith("...")

    def test_empty_string(self):
        assert _truncate("") == ""

    def test_none_returns_empty(self):
        assert _truncate(None) == ""


class TestBuildKiroTool:
    def test_factory_returns_callable(self):
        tool_fn = build_kiro_tool("TestTable")
        assert callable(tool_fn)

    def test_tool_has_docstring(self):
        tool_fn = build_kiro_tool("TestTable")
        # Strands tools have a docstring used for the tool description
        assert tool_fn.__doc__ is not None
        assert "Kiro" in tool_fn.__doc__ or "usage" in tool_fn.__doc__


class TestKiroToolFunction:
    def _build_tool_with_mock_repo(self, daily_stats=None, prompts=None, categories=None):
        """Build a kiro tool with a mocked DynamoDB resource."""
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_resource.Table.return_value = mock_table

        # We need to patch AnalyticsRepository to use our mock
        repo_mock = MagicMock()
        repo_mock.get_user_daily_stats.return_value = daily_stats or []
        repo_mock.get_user_prompts.return_value = {"items": prompts or [], "nextToken": None}
        repo_mock.get_user_category_distribution.return_value = categories or []

        return repo_mock

    def test_missing_user_id(self):
        tool_fn = build_kiro_tool("TestTable", dynamodb_resource=MagicMock())
        result = tool_fn(user_id="", start_date="2026-04-01", end_date="2026-04-30")
        assert result["error"] == "MISSING_USER_ID"

    def test_missing_dates(self):
        tool_fn = build_kiro_tool("TestTable", dynamodb_resource=MagicMock())
        result = tool_fn(user_id="user1", start_date="", end_date="")
        assert result["error"] == "MISSING_DATE_RANGE"

    def test_user_not_found(self):
        import boto3
        from moto import mock_aws
        with mock_aws():
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            ddb.create_table(
                TableName="TestTable",
                KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
                AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            tool_fn = build_kiro_tool("TestTable", dynamodb_resource=ddb)
            result = tool_fn(user_id="nonexistent", start_date="2026-04-01", end_date="2026-04-30")
            assert result["error"] == "USER_NOT_FOUND"

    def test_successful_response(self):
        import boto3
        from moto import mock_aws
        with mock_aws():
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = ddb.create_table(
                TableName="TestTable",
                KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
                AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            table.put_item(Item={"PK": "USER#user1", "SK": "STATS#DAILY#2026-04-15", "totalInteractions": 10, "totalMessages": 5})
            table.put_item(Item={"PK": "USER#user1", "SK": "STATS#DAILY#2026-04-16", "totalInteractions": 8, "totalMessages": 3})
            table.put_item(Item={"PK": "USER#user1", "SK": "PROMPT#2026-04-15T10:00:00Z#r1", "timestamp": "2026-04-15T10:00:00Z", "prompt": "Refactor auth module", "category": "code_generation"})
            table.put_item(Item={"PK": "USER#user1", "SK": "PROMPT#2026-04-16T11:00:00Z#r2", "timestamp": "2026-04-16T11:00:00Z", "prompt": "Fix bug in login", "category": "debugging"})
            table.put_item(Item={"PK": "USER#user1", "SK": "STATS#CATEGORY#code_generation", "count": 15})
            table.put_item(Item={"PK": "USER#user1", "SK": "STATS#CATEGORY#debugging", "count": 8})

            tool_fn = build_kiro_tool("TestTable", dynamodb_resource=ddb)
            result = tool_fn(user_id="user1", start_date="2026-04-01", end_date="2026-04-30")

            assert "error" not in result
            assert len(result["prompts"]) == 2
            prompt_contents = {p["content"] for p in result["prompts"]}
            assert "Refactor auth module" in prompt_contents
            assert "Fix bug in login" in prompt_contents
            assert len(result["dailyStats"]) == 2
            dates = {s["date"] for s in result["dailyStats"]}
            assert "2026-04-15" in dates
            assert len(result["categoryDistribution"]) == 2

    def test_prompts_truncated(self):
        import boto3
        from moto import mock_aws
        long_prompt = "x" * 600
        with mock_aws():
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = ddb.create_table(
                TableName="TestTable",
                KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
                AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            table.put_item(Item={"PK": "USER#user1", "SK": "STATS#DAILY#2026-04-15", "totalInteractions": 1, "totalMessages": 1})
            table.put_item(Item={"PK": "USER#user1", "SK": "PROMPT#2026-04-15T10:00:00Z#r1", "timestamp": "2026-04-15T10:00:00Z", "prompt": long_prompt, "category": "code_generation"})

            tool_fn = build_kiro_tool("TestTable", dynamodb_resource=ddb)
            result = tool_fn(user_id="user1", start_date="2026-04-01", end_date="2026-04-30")

            assert len(result["prompts"][0]["content"]) == 503


# Feature: agent-git-correlation, Property 1: Prompt Truncation Invariant
class TestPromptTruncationProperty:
    """Property 1: Prompt Truncation Invariant.

    For any string of any length, the returned prompt content SHALL never
    exceed 500 characters, AND strings with length <= 500 SHALL be returned unchanged.

    **Validates: Requirements 1.4**
    """

    @given(text=st.text(min_size=0, max_size=10000))
    @settings(max_examples=20)
    def test_truncation_never_exceeds_500_chars(self, text):
        """Output never exceeds 500 chars (plus ellipsis suffix)."""
        result = _truncate(text)
        # Result is at most 503 chars (500 + "...")
        assert len(result) <= 503

    @given(text=st.text(min_size=0, max_size=500))
    @settings(max_examples=20)
    def test_short_strings_unchanged(self, text):
        """Strings with length <= 500 are returned unchanged."""
        result = _truncate(text)
        assert result == text

    @given(text=st.text(min_size=501, max_size=10000))
    @settings(max_examples=20)
    def test_long_strings_truncated_with_ellipsis(self, text):
        """Strings longer than 500 are truncated and end with '...'."""
        result = _truncate(text)
        assert len(result) == 503
        assert result.endswith("...")
        assert result[:500] == text[:500]
