"""Tests for etl.writer_handler module."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from etl.writer_handler import (
    _write_activity_record,
    _write_csv_record,
    _write_prompt_record,
    writer_handler,
)
from shared.structured_logger import StructuredLogger

TABLE_NAME = "Analytics_Table"
DATA_BUCKET = "test-data-bucket"

ENV_VARS = {
    "ANALYTICS_TABLE": TABLE_NAME,
    "DATA_BUCKET": DATA_BUCKET,
}


@pytest.fixture
def aws_env():
    """Create mocked DynamoDB table and S3 bucket."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=DATA_BUCKET)
        yield dynamodb, s3


@pytest.fixture
def table(aws_env):
    dynamodb, _ = aws_env
    return dynamodb.Table(TABLE_NAME)


# ------------------------------------------------------------------
# _write_csv_record
# ------------------------------------------------------------------

class TestWriteCsvRecord:
    def test_writes_daily_and_global_stats(self, aws_env, table):
        from shared.analytics_writer import AnalyticsWriter

        dynamodb, s3 = aws_env
        writer = AnalyticsWriter(TABLE_NAME, DATA_BUCKET, dynamodb_resource=dynamodb, s3_client=s3)

        record = {
            "userId": "user-1",
            "date": "2025-01-15",
            "totalCredits": 10.5,
            "overageCredits": 2.0,
            "totalMessages": 5,
            "totalConversations": 2,
            "totalInteractions": 8,
        }
        items = _write_csv_record(writer, record, StructuredLogger("test"))

        assert items == 3  # daily + global + activity_summary

        # Check daily stats
        daily = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]
        assert daily["totalCredits"] == Decimal("10.5")
        assert daily["totalInteractions"] == 8

        # Check global stats
        global_item = table.get_item(
            Key={"PK": "GLOBAL", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]
        assert global_item["totalCredits"] == Decimal("10.5")
        assert global_item["totalUsers"] == {"user-1"}


class TestWriteOptionalSourceMetrics:
    def test_token_cost_record_does_not_materialize_credit_fields(self, aws_env, table):
        """A non-credit source accumulates only metrics it actually defines."""
        from shared.analytics_writer import AnalyticsWriter

        dynamodb, s3 = aws_env
        writer = AnalyticsWriter(
            TABLE_NAME, DATA_BUCKET, dynamodb_resource=dynamodb, s3_client=s3
        )
        record = {
            "userId": "bedrock-user",
            "date": "2026-09-14",
            "clientType": "CLAUDE_CODE",
            "totalInteractions": 1,
            "inputTokens": 1200,
            "outputTokens": 300,
            "cacheReadTokens": 800,
            "cacheWriteTokens": 40,
            "estimatedCostUsd": 0.0125,
        }

        items = _write_activity_record(writer, record, StructuredLogger("test"))

        assert items == 4  # daily + global + client + activity summary
        for key in (
            {"PK": "USER#bedrock-user", "SK": "STATS#DAILY#2026-09-14"},
            {"PK": "GLOBAL", "SK": "STATS#DAILY#2026-09-14"},
            {"PK": "GLOBAL", "SK": "STATS#CLIENT#CLAUDE_CODE#2026-09-14"},
        ):
            item = table.get_item(Key=key)["Item"]
            assert "totalCredits" not in item
            assert "overageCredits" not in item
            assert "totalMessages" not in item
            assert "totalConversations" not in item
            assert item["totalInteractions"] == 1
            assert item["inputTokens"] == 1200
            assert item["outputTokens"] == 300
            assert item["cacheReadTokens"] == 800
            assert item["cacheWriteTokens"] == 40
            assert item["estimatedCostUsd"] == Decimal("0.0125")

    def test_kiro_record_keeps_credit_attributes_and_no_token_fields(self, aws_env, table):
        """The generalized path does not alter the existing Kiro item shape."""
        from shared.analytics_writer import AnalyticsWriter

        dynamodb, s3 = aws_env
        writer = AnalyticsWriter(
            TABLE_NAME, DATA_BUCKET, dynamodb_resource=dynamodb, s3_client=s3
        )
        record = {
            "userId": "kiro-user",
            "date": "2026-09-14",
            "totalCredits": 2.5,
            "overageCredits": 0.25,
            "totalMessages": 4,
            "totalConversations": 1,
            "totalInteractions": 5,
            "clientType": "KIRO_IDE",
            "subscriptionTier": "PRO",
        }

        _write_activity_record(writer, record, StructuredLogger("test"))
        item = table.get_item(
            Key={"PK": "USER#kiro-user", "SK": "STATS#DAILY#2026-09-14"}
        )["Item"]

        assert item["totalCredits"] == Decimal("2.5")
        assert item["overageCredits"] == Decimal("0.25")
        assert item["totalMessages"] == 4
        assert item["totalConversations"] == 1
        assert item["totalInteractions"] == 5
        assert item["clientType"] == "KIRO_IDE"
        assert item["subscriptionTier"] == "PRO"
        assert not {
            "inputTokens",
            "outputTokens",
            "cacheReadTokens",
            "cacheWriteTokens",
            "estimatedCostUsd",
        }.intersection(item)


# ------------------------------------------------------------------
# _write_prompt_record
# ------------------------------------------------------------------

class TestWritePromptRecord:
    def test_writes_prompt_and_all_counters(self, aws_env, table):
        from shared.analytics_writer import AnalyticsWriter

        dynamodb, s3 = aws_env
        writer = AnalyticsWriter(TABLE_NAME, DATA_BUCKET, dynamodb_resource=dynamodb, s3_client=s3)

        record = {
            "userId": "user-1",
            "timestamp": "2025-01-15T14:30:25Z",
            "requestId": "req-001",
            "date": "2025-01-15",
            "modelId": "anthropic.claude-sonnet-4-20250514-v1:0",
            "triggerType": "CHAT",
            "promptLength": 100,
            "responseLength": 200,
            "prompt": "hello",
            "response": "world",
            "contentInS3": False,
        }
        items = _write_prompt_record(writer, record, StructuredLogger("test"))

        # prompt + daily stats + model + trigger + global + activity_summary = 6
        assert items == 6

        # Check prompt metadata
        prompt_item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "PROMPT#2025-01-15T14:30:25Z#req-001"}
        )["Item"]
        assert prompt_item["requestId"] == "req-001"
        assert prompt_item["contentInS3"] is False

        # Check daily stats (interactions only)
        daily = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]
        assert daily["totalInteractions"] == 1
        assert daily["totalCredits"] == Decimal("0")

        # Check model distribution
        model = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#MODEL#anthropic-claude-sonnet-4-20250514-v1-0"}
        )["Item"]
        assert model["count"] == 1
        assert model["rawModelId"] == "anthropic.claude-sonnet-4-20250514-v1:0"

        # Check trigger distribution
        trigger = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#TRIGGER#chat"}
        )["Item"]
        assert trigger["count"] == 1
        assert trigger["rawTriggerType"] == "CHAT"

        # Check global stats
        global_item = table.get_item(
            Key={"PK": "GLOBAL", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]
        assert global_item["totalUsers"] == {"user-1"}

    def test_prompt_without_model_or_trigger(self, aws_env, table):
        from shared.analytics_writer import AnalyticsWriter

        dynamodb, s3 = aws_env
        writer = AnalyticsWriter(TABLE_NAME, DATA_BUCKET, dynamodb_resource=dynamodb, s3_client=s3)

        record = {
            "userId": "user-2",
            "timestamp": "2025-01-15T10:00:00Z",
            "requestId": "req-002",
            "date": "2025-01-15",
            "modelId": "",
            "triggerType": "",
            "prompt": "hi",
            "response": "hey",
            "contentInS3": False,
        }
        items = _write_prompt_record(writer, record, StructuredLogger("test"))

        # prompt + daily stats + global + activity_summary = 4 (no model, no trigger)
        assert items == 4

    def test_prompt_date_fallback_from_timestamp(self, aws_env, table):
        from shared.analytics_writer import AnalyticsWriter

        dynamodb, s3 = aws_env
        writer = AnalyticsWriter(TABLE_NAME, DATA_BUCKET, dynamodb_resource=dynamodb, s3_client=s3)

        record = {
            "userId": "user-3",
            "timestamp": "2025-02-20T08:00:00Z",
            "requestId": "req-003",
            "modelId": "",
            "triggerType": "",
            "prompt": "q",
            "response": "a",
            "contentInS3": False,
        }
        _write_prompt_record(writer, record, StructuredLogger("test"))

        daily = table.get_item(
            Key={"PK": "USER#user-3", "SK": "STATS#DAILY#2025-02-20"}
        )["Item"]
        assert daily["totalInteractions"] == 1

    def test_prompt_missing_content_in_s3_key_defaults_to_inline(self, aws_env, table):
        """A record from an in-flight Map child still running the previous
        Parse output (deploy window) never set contentInS3 — it must default
        to False and write inline, matching that output's actual content."""
        from shared.analytics_writer import AnalyticsWriter

        dynamodb, s3 = aws_env
        writer = AnalyticsWriter(TABLE_NAME, DATA_BUCKET, dynamodb_resource=dynamodb, s3_client=s3)

        record = {
            "userId": "user-4",
            "timestamp": "2025-01-15T12:00:00Z",
            "requestId": "req-004",
            "date": "2025-01-15",
            "modelId": "",
            "triggerType": "",
            "prompt": "legacy prompt",
            "response": "legacy response",
            # contentInS3 deliberately absent
        }
        _write_prompt_record(writer, record, StructuredLogger("test"))

        prompt_item = table.get_item(
            Key={"PK": "USER#user-4", "SK": "PROMPT#2025-01-15T12:00:00Z#req-004"}
        )["Item"]
        assert prompt_item["contentInS3"] is False
        assert prompt_item["prompt"] == "legacy prompt"
        assert prompt_item["response"] == "legacy response"


# ------------------------------------------------------------------
# writer_handler — CSV
# ------------------------------------------------------------------

class TestWriterHandlerCsv:
    @patch.dict(os.environ, ENV_VARS)
    def test_csv_happy_path(self, aws_env, table):
        dynamodb, s3 = aws_env

        with patch("etl.writer_handler.AnalyticsWriter") as MockWriter:
            MockWriter.return_value = MockWriter
            MockWriter.increment_daily_stats = lambda *a, **kw: None
            MockWriter.increment_global_daily_stats = lambda *a, **kw: None
            MockWriter.upsert_activity_summary = lambda *a, **kw: None

            event = {
                "records": [
                    {
                        "userId": "u1",
                        "date": "2025-01-15",
                        "totalCredits": 10,
                        "overageCredits": 0,
                        "totalMessages": 5,
                        "totalConversations": 2,
                        "totalInteractions": 8,
                    },
                ],
                "fileType": "csv",
                "key": "activities/file.csv",
                "correlationId": "exec-123",
            }
            result = writer_handler(event, None)

        assert result["recordCount"] == 1
        assert result["itemsWritten"] == 3  # daily + global + activity_summary
        assert "durationMs" in result

    @patch.dict(os.environ, ENV_VARS)
    def test_csv_multiple_records(self, aws_env):
        with patch("etl.writer_handler.AnalyticsWriter") as MockWriter:
            MockWriter.return_value = MockWriter
            MockWriter.increment_daily_stats = lambda *a, **kw: None
            MockWriter.increment_global_daily_stats = lambda *a, **kw: None
            MockWriter.upsert_activity_summary = lambda *a, **kw: None

            event = {
                "records": [
                    {"userId": "u1", "date": "2025-01-15", "totalCredits": 5},
                    {"userId": "u2", "date": "2025-01-15", "totalCredits": 10},
                ],
                "fileType": "csv",
                "key": "file.csv",
                "correlationId": "",
            }
            result = writer_handler(event, None)

        assert result["recordCount"] == 2
        assert result["itemsWritten"] == 6  # 2 records × 3 items each (daily + global + activity_summary)


# ------------------------------------------------------------------
# writer_handler — Prompt
# ------------------------------------------------------------------

class TestWriterHandlerPrompt:
    @patch.dict(os.environ, ENV_VARS)
    def test_prompt_happy_path(self, aws_env):
        with patch("etl.writer_handler.AnalyticsWriter") as MockWriter:
            MockWriter.return_value = MockWriter
            MockWriter.write_prompt = lambda *a, **kw: None
            MockWriter.increment_daily_stats = lambda *a, **kw: None
            MockWriter.increment_model_count = lambda *a, **kw: None
            MockWriter.increment_trigger_count = lambda *a, **kw: None
            MockWriter.increment_global_daily_stats = lambda *a, **kw: None
            MockWriter.upsert_activity_summary = lambda *a, **kw: None

            event = {
                "records": [
                    {
                        "userId": "u1",
                        "timestamp": "2025-01-15T14:30:25Z",
                        "requestId": "req-001",
                        "date": "2025-01-15",
                        "modelId": "claude-sonnet",
                        "triggerType": "CHAT",
                        "prompt": "hello",
                        "response": "world",
                        "contentInS3": False,
                    },
                ],
                "fileType": "prompt",
                "key": "prompts/file.json.gz",
                "correlationId": "exec-456",
            }
            result = writer_handler(event, None)

        assert result["recordCount"] == 1
        assert result["itemsWritten"] == 6  # prompt + daily + model + trigger + global + activity_summary
        assert "durationMs" in result


# ------------------------------------------------------------------
# writer_handler — Empty records
# ------------------------------------------------------------------

class TestWriterHandlerEmpty:
    @patch.dict(os.environ, ENV_VARS)
    def test_empty_records(self, aws_env):
        with patch("etl.writer_handler.AnalyticsWriter") as MockWriter:
            MockWriter.return_value = MockWriter

            event = {
                "records": [],
                "fileType": "csv",
                "key": "file.csv",
                "correlationId": "",
            }
            result = writer_handler(event, None)

        assert result["recordCount"] == 0
        assert result["itemsWritten"] == 0


# ------------------------------------------------------------------
# writer_handler — Error handling
# ------------------------------------------------------------------

class TestWriterHandlerErrors:
    @patch.dict(os.environ, ENV_VARS)
    def test_unknown_file_type_raises(self, aws_env):
        with patch("etl.writer_handler.AnalyticsWriter") as MockWriter:
            MockWriter.return_value = MockWriter

            event = {
                "records": [{"userId": "u1"}],
                "fileType": "parquet",
                "key": "file.parquet",
                "correlationId": "",
            }
            with pytest.raises(ValueError, match="Unknown fileType"):
                writer_handler(event, None)

    @patch.dict(os.environ, ENV_VARS)
    def test_writer_error_propagates(self, aws_env):
        with patch("etl.writer_handler.AnalyticsWriter") as MockWriter:
            MockWriter.return_value = MockWriter
            MockWriter.increment_daily_stats = lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("DynamoDB error")
            )

            event = {
                "records": [{"userId": "u1", "date": "2025-01-15"}],
                "fileType": "csv",
                "key": "file.csv",
                "correlationId": "",
            }
            with pytest.raises(RuntimeError, match="DynamoDB error"):
                writer_handler(event, None)


@pytest.mark.parametrize("file_type", ["kiro_csv", "kiro_prompt_log"])
@patch.dict(os.environ, ENV_VARS)
def test_writer_accepts_canonical_file_types(file_type, aws_env):
    """Canonical names resolve during a rolling deploy, even for empty batches."""
    with patch("etl.writer_handler.AnalyticsWriter"):
        result = writer_handler(
            {
                "records": [],
                "fileType": file_type,
                "key": "key",
                "correlationId": "deploy-window",
            },
            None,
        )

    assert result["recordCount"] == 0
    assert result["itemsWritten"] == 0
