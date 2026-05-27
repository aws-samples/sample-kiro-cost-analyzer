"""Tests for backend.handlers.user_details_handler module (DynamoDB-backed)."""

import os
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from backend.handlers.user_details_handler import (
    _compute_distributions,
    handle_user_details,
)
from shared.user_name_resolver import lookup_user_name as _lookup_user_name


ANALYTICS_TABLE = "TestAnalyticsTable"
USER_NAMES_TABLE = "TestUserNamesTable"


def _create_analytics_table(resource):
    """Create the mocked Analytics_Table."""
    resource.create_table(
        TableName=ANALYTICS_TABLE,
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
    return resource.Table(ANALYTICS_TABLE)


def _create_user_names_table(client):
    """Create the mocked UserNamesTable."""
    client.create_table(
        TableName=USER_NAMES_TABLE,
        KeySchema=[{"AttributeName": "userId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "userId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def _put_daily_stat(table, user_id, date, credits, overage=0, messages=0, conversations=0, interactions=0):
    table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": f"STATS#DAILY#{date}",
        "totalCredits": Decimal(str(credits)),
        "overageCredits": Decimal(str(overage)),
        "totalMessages": messages,
        "totalConversations": conversations,
        "totalInteractions": interactions,
    })


def _put_model_dist(table, user_id, normalized_id, raw_id, count):
    table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": f"STATS#MODEL#{normalized_id}",
        "count": count,
        "rawModelId": raw_id,
    })


def _put_trigger_dist(table, user_id, normalized_type, raw_type, count):
    table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": f"STATS#TRIGGER#{normalized_type}",
        "count": count,
        "rawTriggerType": raw_type,
    })


def _put_prompt(table, user_id, timestamp, request_id, model_id="model-a", trigger_type="CHAT",
                prompt_length=100, response_length=200):
    table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": f"PROMPT#{timestamp}#{request_id}",
        "timestamp": timestamp,
        "requestId": request_id,
        "modelId": model_id,
        "triggerType": trigger_type,
        "promptLength": prompt_length,
        "responseLength": response_length,
    })


def _put_user_name(client, user_id, display_name, user_name):
    client.put_item(
        TableName=USER_NAMES_TABLE,
        Item={
            "userId": {"S": user_id},
            "displayName": {"S": display_name},
            "userName": {"S": user_name},
        },
    )


class TestComputeDistributions:
    def test_computes_percentages(self):
        items = [
            {"count": 7, "rawModelId": "Model A"},
            {"count": 3, "rawModelId": "Model B"},
        ]
        result = _compute_distributions(items, "modelId", "rawModelId")
        assert len(result) == 2
        assert result[0]["modelId"] == "Model A"
        assert result[0]["count"] == 7
        assert result[0]["percentage"] == 70.0
        assert result[1]["modelId"] == "Model B"
        assert result[1]["count"] == 3
        assert result[1]["percentage"] == 30.0

    def test_empty_items(self):
        result = _compute_distributions([], "modelId", "rawModelId")
        assert result == []


class TestLookupUserName:
    @mock_aws
    def test_returns_name_from_table(self):
        client = boto3.client("dynamodb", region_name="us-east-1")
        _create_user_names_table(client)
        _put_user_name(client, "user-1", "Alice Smith", "alice.smith")

        os.environ["USER_NAMES_TABLE"] = USER_NAMES_TABLE
        display, user = _lookup_user_name("user-1", dynamodb_client=client)
        assert display == "Alice Smith"
        assert user == "alice.smith"

    @mock_aws
    def test_returns_empty_when_not_found(self):
        client = boto3.client("dynamodb", region_name="us-east-1")
        _create_user_names_table(client)

        os.environ["USER_NAMES_TABLE"] = USER_NAMES_TABLE
        display, user = _lookup_user_name("nonexistent", dynamodb_client=client)
        assert display == ""
        assert user == ""

    def test_returns_empty_when_no_table_configured(self):
        os.environ.pop("USER_NAMES_TABLE", None)
        display, user = _lookup_user_name("user-1")
        assert display == ""
        assert user == ""


class TestHandleUserDetails:
    @mock_aws
    def test_returns_full_response(self):
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        client = boto3.client("dynamodb", region_name="us-east-1")
        table = _create_analytics_table(resource)
        _create_user_names_table(client)

        uid = "user-abc"
        _put_daily_stat(table, uid, "2026-04-10", 60.0, 5.0, 30, 3, 10)
        _put_daily_stat(table, uid, "2026-04-11", 40.0, 2.0, 20, 2, 8)
        _put_model_dist(table, uid, "claude-sonnet", "anthropic.claude-sonnet", 12)
        _put_model_dist(table, uid, "claude-haiku", "anthropic.claude-haiku", 6)
        _put_trigger_dist(table, uid, "chat", "CHAT", 14)
        _put_trigger_dist(table, uid, "inline-chat", "INLINE_CHAT", 4)
        _put_prompt(table, uid, "2026-04-11T10:00:00Z", "req-1")
        _put_prompt(table, uid, "2026-04-10T09:00:00Z", "req-2")
        _put_user_name(client, uid, "Alice", "alice")

        os.environ["ANALYTICS_TABLE"] = ANALYTICS_TABLE
        os.environ["USER_NAMES_TABLE"] = USER_NAMES_TABLE

        result = handle_user_details(
            uid,
            {"startDate": "2026-04-01", "endDate": "2026-04-30"},
            dynamodb_resource=resource,
            dynamodb_client=client,
        )

        assert result["userId"] == uid
        assert result["displayName"] == "Alice"
        assert result["userName"] == "alice"

        # Summary
        assert result["summary"]["totalCredits"] == 100.0
        assert result["summary"]["totalInteractions"] == 18
        assert result["summary"]["totalMessages"] == 50
        assert result["summary"]["averageCostPerInteraction"] == round(100.0 / 18, 2)

        # Daily usage sorted by date
        assert len(result["dailyUsage"]) == 2
        assert result["dailyUsage"][0]["date"] == "2026-04-10"
        assert result["dailyUsage"][0]["credits"] == 60.0
        assert result["dailyUsage"][0]["interactions"] == 10
        assert result["dailyUsage"][1]["date"] == "2026-04-11"

        # Model distribution
        assert len(result["modelDistribution"]) == 2
        model_ids = {m["modelId"] for m in result["modelDistribution"]}
        assert "anthropic.claude-sonnet" in model_ids
        assert "anthropic.claude-haiku" in model_ids

        # Trigger distribution
        assert len(result["triggerDistribution"]) == 2

        # Recent prompts
        assert len(result["recentPrompts"]) == 2
        # Newest first (scan_forward=False)
        assert result["recentPrompts"][0]["requestId"] == "req-1"
        assert result["recentPrompts"][1]["requestId"] == "req-2"

        # Period
        assert result["period"] == {"startDate": "2026-04-01", "endDate": "2026-04-30"}

    @mock_aws
    def test_returns_404_when_no_data(self):
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        _create_analytics_table(resource)

        os.environ["ANALYTICS_TABLE"] = ANALYTICS_TABLE

        result = handle_user_details("nonexistent", {}, dynamodb_resource=resource)

        assert result.get("_status_code") == 404
        assert result["error"] == "NotFound"
        assert "nonexistent" in result["message"]

    @mock_aws
    def test_cost_per_interaction_none_when_zero_interactions(self):
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_analytics_table(resource)

        uid = "user-zero"
        _put_daily_stat(table, uid, "2026-04-10", 50.0, 0, 10, 1, 0)

        os.environ["ANALYTICS_TABLE"] = ANALYTICS_TABLE
        os.environ.pop("USER_NAMES_TABLE", None)

        result = handle_user_details(uid, {}, dynamodb_resource=resource)

        assert result["dailyUsage"][0]["costPerInteraction"] is None
        assert result["summary"]["averageCostPerInteraction"] == 0.0

    @mock_aws
    def test_prompts_only_no_stats(self):
        """When there are prompts but no daily stats, should still return data."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_analytics_table(resource)

        uid = "user-prompts-only"
        _put_prompt(table, uid, "2026-04-10T08:00:00Z", "req-p1")

        os.environ["ANALYTICS_TABLE"] = ANALYTICS_TABLE
        os.environ.pop("USER_NAMES_TABLE", None)

        result = handle_user_details(uid, {}, dynamodb_resource=resource)

        assert result["userId"] == uid
        assert result["dailyUsage"] == []
        assert result["summary"]["totalCredits"] == 0.0
        assert len(result["recentPrompts"]) == 1

    @mock_aws
    def test_response_schema_matches_typescript_interface(self):
        """Verify the response matches the UserDetailResponse TypeScript interface."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        client = boto3.client("dynamodb", region_name="us-east-1")
        table = _create_analytics_table(resource)
        _create_user_names_table(client)

        uid = "user-schema"
        _put_daily_stat(table, uid, "2026-04-10", 100.0, 10.0, 50, 5, 20)
        _put_model_dist(table, uid, "model-a", "Model A", 10)
        _put_trigger_dist(table, uid, "chat", "CHAT", 10)
        _put_prompt(table, uid, "2026-04-10T12:00:00Z", "req-s1")
        _put_user_name(client, uid, "Bob", "bob")

        os.environ["ANALYTICS_TABLE"] = ANALYTICS_TABLE
        os.environ["USER_NAMES_TABLE"] = USER_NAMES_TABLE

        result = handle_user_details(
            uid,
            {"startDate": "2026-04-01", "endDate": "2026-04-30"},
            dynamodb_resource=resource,
            dynamodb_client=client,
        )

        # Top-level keys from UserDetailResponse
        assert "userId" in result
        assert "displayName" in result
        assert "userName" in result
        assert "summary" in result
        assert "dailyUsage" in result
        assert "modelDistribution" in result
        assert "triggerDistribution" in result
        assert "categoryDistribution" in result
        assert "recentPrompts" in result
        assert "period" in result

        # Summary keys from UserDetailSummary
        summary = result["summary"]
        assert "totalCredits" in summary
        assert "totalInteractions" in summary
        assert "averageCostPerInteraction" in summary
        assert "totalMessages" in summary

        # DailyUsageEntry keys
        day = result["dailyUsage"][0]
        expected_day_keys = {"date", "credits", "interactions", "costPerInteraction", "messages", "overageCredits"}
        assert set(day.keys()) == expected_day_keys

        # ModelDistribution keys
        model = result["modelDistribution"][0]
        assert set(model.keys()) == {"modelId", "count", "percentage"}

        # TriggerDistribution keys
        trigger = result["triggerDistribution"][0]
        assert set(trigger.keys()) == {"triggerType", "count", "percentage"}

        # RecentPrompt keys
        prompt = result["recentPrompts"][0]
        expected_prompt_keys = {"timestamp", "modelId", "triggerType", "promptLength", "responseLength", "requestId", "category"}
        assert set(prompt.keys()) == expected_prompt_keys

        # Period keys
        assert "startDate" in result["period"]
        assert "endDate" in result["period"]

    @mock_aws
    def test_no_period_when_no_dates(self):
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_analytics_table(resource)

        uid = "user-noperiod"
        _put_daily_stat(table, uid, "2026-04-10", 10.0)

        os.environ["ANALYTICS_TABLE"] = ANALYTICS_TABLE
        os.environ.pop("USER_NAMES_TABLE", None)

        result = handle_user_details(uid, {}, dynamodb_resource=resource)

        assert result["period"] == {}
