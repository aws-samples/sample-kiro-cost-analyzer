"""Unit tests for etl.repository.analytics_writer.AnalyticsWriter."""

from __future__ import annotations

import json
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from shared.analytics_writer import AnalyticsWriter

TABLE_NAME = "Analytics_Table"
DATA_BUCKET = "test-data-bucket"


@pytest.fixture
def aws_resources():
    """Create a mocked DynamoDB table and S3 bucket."""
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
def writer(aws_resources):
    dynamodb, s3 = aws_resources
    return AnalyticsWriter(TABLE_NAME, DATA_BUCKET, dynamodb_resource=dynamodb, s3_client=s3)


@pytest.fixture
def table(aws_resources):
    dynamodb, _ = aws_resources
    return dynamodb.Table(TABLE_NAME)


# ------------------------------------------------------------------
# write_prompt — inline (≤4KB)
# ------------------------------------------------------------------

class TestWritePromptInline:
    def test_inline_stores_content_in_item(self, writer, table):
        record = {
            "requestId": "req-001",
            "timestamp": "2025-01-15T14:30:25Z",
            "modelId": "claude-sonnet",
            "triggerType": "CHAT",
            "promptLength": 10,
            "responseLength": 20,
        }
        writer.write_prompt("user-1", record, "hello", "world", content_in_s3=False)

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "PROMPT#2025-01-15T14:30:25Z#req-001"}
        )["Item"]

        assert item["contentInS3"] is False
        assert item["prompt"] == "hello"
        assert item["response"] == "world"
        assert item["requestId"] == "req-001"
        assert item["modelId"] == "claude-sonnet"

    def test_inline_boundary_exactly_4096(self, writer, table):
        """Content exactly at 4096 bytes, caller decides inline (contentInS3=False)."""
        # 4096 bytes total: 2048 + 2048
        prompt = "a" * 2048
        response = "b" * 2048
        record = {"requestId": "req-boundary", "timestamp": "2025-01-15T00:00:00Z"}

        writer.write_prompt("user-1", record, prompt, response, content_in_s3=False)

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "PROMPT#2025-01-15T00:00:00Z#req-boundary"}
        )["Item"]

        assert item["contentInS3"] is False
        assert item["prompt"] == prompt
        assert item["response"] == response


# ------------------------------------------------------------------
# write_prompt — S3 (>4KB)
# ------------------------------------------------------------------

class TestWritePromptS3:
    def test_content_in_s3_true_does_not_write_s3_again(self, writer, table, aws_resources):
        """When the caller has already decided content_in_s3=True (Parse already
        wrote the object), write_prompt must record the flag but NOT re-upload —
        the object is assumed to already exist at prompts-content/{requestId}.json."""
        _, s3 = aws_resources
        record = {"requestId": "req-large", "timestamp": "2025-01-15T10:00:00Z"}

        # Content strings are irrelevant here — Parse would have already
        # cleared them to "" before Writer ever sees the record — but pass
        # non-empty values to prove they are NOT persisted anywhere by Writer.
        writer.write_prompt("user-1", record, "", "", content_in_s3=True)

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "PROMPT#2025-01-15T10:00:00Z#req-large"}
        )["Item"]

        assert item["contentInS3"] is True
        assert "prompt" not in item
        assert "response" not in item

        # No object was written by Writer — Parse owns that write exclusively.
        with pytest.raises(s3.exceptions.NoSuchKey):
            s3.get_object(Bucket=DATA_BUCKET, Key="prompts-content/req-large.json")

    def test_content_in_s3_false_writes_inline_regardless_of_size(self, writer, table):
        """content_in_s3 is taken as given — write_prompt no longer recomputes
        the threshold from content length, so even large content stored inline
        by the caller's decision is written inline here."""
        prompt = "x" * 3000
        response = "y" * 2000  # 5000 bytes, but caller decided contentInS3=False
        record = {"requestId": "req-caller-decides", "timestamp": "2025-01-15T10:00:00Z"}

        writer.write_prompt("user-1", record, prompt, response, content_in_s3=False)

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "PROMPT#2025-01-15T10:00:00Z#req-caller-decides"}
        )["Item"]

        assert item["contentInS3"] is False
        assert item["prompt"] == prompt
        assert item["response"] == response


# ------------------------------------------------------------------
# increment_daily_stats
# ------------------------------------------------------------------

class TestIncrementDailyStats:
    def test_creates_new_stats_item(self, writer, table):
        writer.increment_daily_stats("user-1", "2025-01-15", 10.5, 2.0, 5, 2, 8)

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]

        assert item["totalCredits"] == Decimal("10.5")
        assert item["overageCredits"] == Decimal("2.0")
        assert item["totalMessages"] == 5
        assert item["totalConversations"] == 2
        assert item["totalInteractions"] == 8

    def test_accumulates_on_repeated_calls(self, writer, table):
        writer.increment_daily_stats("user-1", "2025-01-15", 10.0, 1.0, 3, 1, 5)
        writer.increment_daily_stats("user-1", "2025-01-15", 5.0, 0.5, 2, 1, 3)

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]

        assert item["totalCredits"] == Decimal("15.0")
        assert item["overageCredits"] == Decimal("1.5")
        assert item["totalMessages"] == 5
        assert item["totalConversations"] == 2
        assert item["totalInteractions"] == 8

    def test_stores_subscription_tier(self, writer, table):
        """First write should persist the subscription tier."""
        writer.increment_daily_stats(
            "user-1", "2025-01-15", 10.0, 0.0, 1, 0, 1,
            subscription_tier="PRO",
        )

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]

        assert item["subscriptionTier"] == "PRO"

    def test_tier_upgrade_overwrites_previous_value(self, writer, table):
        """When a user upgrades tier, the new value must replace the old one."""
        writer.increment_daily_stats(
            "user-1", "2025-01-15", 10.0, 0.0, 1, 0, 1,
            subscription_tier="PRO",
        )
        writer.increment_daily_stats(
            "user-1", "2025-01-15", 5.0, 0.0, 1, 0, 1,
            subscription_tier="POWER",
        )

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]

        assert item["subscriptionTier"] == "POWER"
        # Credits should still accumulate normally
        assert item["totalCredits"] == Decimal("15.0")

    def test_tier_downgrade_also_reflected(self, writer, table):
        """Tier changes in either direction should be reflected."""
        writer.increment_daily_stats(
            "user-1", "2025-01-15", 10.0, 0.0, 1, 0, 1,
            subscription_tier="POWER",
        )
        writer.increment_daily_stats(
            "user-1", "2025-01-15", 5.0, 0.0, 1, 0, 1,
            subscription_tier="PRO",
        )

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]

        assert item["subscriptionTier"] == "PRO"

    def test_client_type_overwrites_previous_value(self, writer, table):
        """Client type should also be updated on subsequent writes."""
        writer.increment_daily_stats(
            "user-1", "2025-01-15", 10.0, 0.0, 1, 0, 1,
            client_type="KIRO_IDE",
        )
        writer.increment_daily_stats(
            "user-1", "2025-01-15", 5.0, 0.0, 1, 0, 1,
            client_type="KIRO_CLI",
        )

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]

        assert item["clientType"] == "KIRO_CLI"

    def test_empty_tier_does_not_clear_existing(self, writer, table):
        """An empty tier string should not overwrite a previously set tier."""
        writer.increment_daily_stats(
            "user-1", "2025-01-15", 10.0, 0.0, 1, 0, 1,
            subscription_tier="POWER",
        )
        # Second call without tier (e.g. from a different data source)
        writer.increment_daily_stats(
            "user-1", "2025-01-15", 5.0, 0.0, 1, 0, 1,
            subscription_tier="",
        )

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]

        assert item["subscriptionTier"] == "POWER"


# ------------------------------------------------------------------
# increment_model_count
# ------------------------------------------------------------------

class TestIncrementModelCount:
    def test_creates_model_item_with_raw_value(self, writer, table):
        writer.increment_model_count("user-1", "claude-sonnet-4", "anthropic.claude-sonnet-4-20250514-v1:0")

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#MODEL#claude-sonnet-4"}
        )["Item"]

        assert item["count"] == 1
        assert item["rawModelId"] == "anthropic.claude-sonnet-4-20250514-v1:0"

    def test_increments_count_preserves_raw(self, writer, table):
        writer.increment_model_count("user-1", "claude-sonnet-4", "anthropic.claude-sonnet-4-20250514-v1:0")
        writer.increment_model_count("user-1", "claude-sonnet-4", "anthropic.claude-sonnet-4-20250514-v1:0")

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#MODEL#claude-sonnet-4"}
        )["Item"]

        assert item["count"] == 2
        assert item["rawModelId"] == "anthropic.claude-sonnet-4-20250514-v1:0"


# ------------------------------------------------------------------
# increment_trigger_count
# ------------------------------------------------------------------

class TestIncrementTriggerCount:
    def test_creates_trigger_item_with_raw_value(self, writer, table):
        writer.increment_trigger_count("user-1", "chat", "CHAT")

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#TRIGGER#chat"}
        )["Item"]

        assert item["count"] == 1
        assert item["rawTriggerType"] == "CHAT"

    def test_increments_count_preserves_raw(self, writer, table):
        writer.increment_trigger_count("user-1", "inline-chat", "INLINE_CHAT")
        writer.increment_trigger_count("user-1", "inline-chat", "INLINE_CHAT")
        writer.increment_trigger_count("user-1", "inline-chat", "INLINE_CHAT")

        item = table.get_item(
            Key={"PK": "USER#user-1", "SK": "STATS#TRIGGER#inline-chat"}
        )["Item"]

        assert item["count"] == 3
        assert item["rawTriggerType"] == "INLINE_CHAT"


# ------------------------------------------------------------------
# increment_global_daily_stats
# ------------------------------------------------------------------

class TestIncrementGlobalDailyStats:
    def test_creates_global_stats_item(self, writer, table):
        writer.increment_global_daily_stats(
            "2025-01-15", 100.0, 10.0, 50, 15, {"user-1", "user-2"}
        )

        item = table.get_item(
            Key={"PK": "GLOBAL", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]

        assert item["totalCredits"] == Decimal("100.0")
        assert item["overageCredits"] == Decimal("10.0")
        assert item["totalMessages"] == 50
        assert item["totalConversations"] == 15
        assert item["totalUsers"] == {"user-1", "user-2"}

    def test_accumulates_users_as_set(self, writer, table):
        writer.increment_global_daily_stats("2025-01-15", 50.0, 5.0, 20, 5, {"user-1"})
        writer.increment_global_daily_stats("2025-01-15", 30.0, 3.0, 10, 3, {"user-2"})
        writer.increment_global_daily_stats("2025-01-15", 20.0, 2.0, 5, 2, {"user-1"})

        item = table.get_item(
            Key={"PK": "GLOBAL", "SK": "STATS#DAILY#2025-01-15"}
        )["Item"]

        assert item["totalCredits"] == Decimal("100.0")
        assert item["totalMessages"] == 35
        # user-1 appears twice but set deduplicates
        assert item["totalUsers"] == {"user-1", "user-2"}
