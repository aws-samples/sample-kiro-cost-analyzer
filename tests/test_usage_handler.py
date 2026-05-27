"""Tests for backend.handlers.usage_handler module (DynamoDB-backed)."""

import os
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from backend.handlers.usage_handler import (
    _compute_summary,
    _format_user,
    handle_usage,
)


TABLE_NAME = "TestAnalyticsTable"


@pytest.fixture
def dynamodb_resource():
    """Create a mocked DynamoDB table for testing."""
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        yield resource


def _put_daily_stat(table, user_id, date, credits, overage=0, messages=0, conversations=0, interactions=0, subscription_tier=""):
    """Helper to insert a STATS#DAILY# item."""
    item = {
        "PK": f"USER#{user_id}",
        "SK": f"STATS#DAILY#{date}",
        "totalCredits": Decimal(str(credits)),
        "overageCredits": Decimal(str(overage)),
        "totalMessages": messages,
        "totalConversations": conversations,
        "totalInteractions": interactions,
    }
    if subscription_tier:
        item["subscriptionTier"] = subscription_tier
    table.put_item(Item=item)


class TestComputeSummary:
    def test_computes_summary(self):
        users = [
            {"totalCredits": 100.0, "overageCredits": 10.0},
            {"totalCredits": 200.0, "overageCredits": 20.0},
            {"totalCredits": 50.0, "overageCredits": 5.0},
        ]
        summary = _compute_summary(users)
        assert summary["totalUsers"] == 3
        assert summary["totalCredits"] == 350.0
        assert summary["totalOverageCredits"] == 35.0
        assert summary["averageCreditsPerUser"] == round(350.0 / 3, 2)

    def test_empty_users(self):
        summary = _compute_summary([])
        assert summary["totalUsers"] == 0
        assert summary["totalCredits"] == 0
        assert summary["totalOverageCredits"] == 0
        assert summary["averageCreditsPerUser"] == 0


class TestFormatUser:
    def test_formats_all_fields(self):
        user = {
            "userId": "user-abc",
            "displayName": "Alice",
            "userName": "alice",
            "subscriptionTier": "PRO_PLUS",
            "totalCredits": 125.5,
            "overageCredits": 12.3,
            "totalMessages": 450,
            "totalConversations": 28,
            "daysActive": 30,
        }
        result = _format_user(user)
        assert result["userId"] == "user-abc"
        assert result["subscriptionTier"] == "PRO_PLUS"
        assert result["totalCredits"] == 125.5
        assert result["overageCredits"] == 12.3
        assert result["totalMessages"] == 450
        assert result["totalConversations"] == 28
        assert result["averageDailyCredits"] == round(125.5 / 30, 2)

    def test_zero_days_active(self):
        user = {"userId": "user-x", "totalCredits": 100, "daysActive": 0}
        result = _format_user(user)
        assert result["averageDailyCredits"] == 0.0

    def test_missing_fields_default(self):
        user = {"userId": "user-y"}
        result = _format_user(user)
        assert result["totalCredits"] == 0
        assert result["overageCredits"] == 0
        assert result["totalMessages"] == 0
        assert result["totalConversations"] == 0
        assert result["averageDailyCredits"] == 0.0
        assert result["displayName"] == ""
        assert result["userName"] == ""
        assert result["subscriptionTier"] == ""


class TestHandleUsage:
    @mock_aws
    def test_returns_full_response(self):
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        table = resource.Table(TABLE_NAME)

        _put_daily_stat(table, "user-1", "2026-04-10", 60.0, 5.0, 30, 3, 10)
        _put_daily_stat(table, "user-1", "2026-04-11", 40.0, 5.0, 20, 2, 8)
        _put_daily_stat(table, "user-2", "2026-04-10", 200.0, 0.0, 80, 10, 25)

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        result = handle_usage(
            {"startDate": "2026-04-01", "endDate": "2026-04-30"},
            dynamodb_resource=resource,
        )

        assert result["summary"]["totalUsers"] == 2
        assert result["summary"]["totalCredits"] == 300.0
        assert result["summary"]["totalOverageCredits"] == 10.0
        assert result["summary"]["averageCreditsPerUser"] == 150.0
        assert len(result["users"]) == 2
        assert result["period"] == {
            "startDate": "2026-04-01",
            "endDate": "2026-04-30",
        }

        # Users should be sorted by totalCredits descending
        assert result["users"][0]["userId"] == "user-2"
        assert result["users"][0]["totalCredits"] == 200.0
        assert result["users"][1]["userId"] == "user-1"
        assert result["users"][1]["totalCredits"] == 100.0

    @mock_aws
    def test_no_data_returns_empty(self):
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        result = handle_usage({}, dynamodb_resource=resource)

        assert result["summary"]["totalUsers"] == 0
        assert result["users"] == []
        assert result["period"] == {}

    @mock_aws
    def test_limit_caps_at_50(self):
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        table = resource.Table(TABLE_NAME)

        # Insert data for 3 users
        for i in range(3):
            _put_daily_stat(table, f"user-{i}", "2026-04-10", 10.0 * (i + 1))

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        # Request limit=100, should be capped to 50
        result = handle_usage({"limit": "100"}, dynamodb_resource=resource)
        assert len(result["users"]) == 3  # only 3 users exist

    @mock_aws
    def test_average_daily_credits_computed(self):
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        table = resource.Table(TABLE_NAME)

        # User with 3 days of activity
        _put_daily_stat(table, "user-1", "2026-04-10", 30.0)
        _put_daily_stat(table, "user-1", "2026-04-11", 30.0)
        _put_daily_stat(table, "user-1", "2026-04-12", 30.0)

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        result = handle_usage({}, dynamodb_resource=resource)

        assert len(result["users"]) == 1
        user = result["users"][0]
        assert user["totalCredits"] == 90.0
        # 90 credits / 3 days = 30.0
        assert user["averageDailyCredits"] == 30.0

    @mock_aws
    def test_global_items_excluded(self):
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        table = resource.Table(TABLE_NAME)

        # Insert a GLOBAL stats item (should be excluded)
        table.put_item(Item={
            "PK": "GLOBAL",
            "SK": "STATS#DAILY#2026-04-10",
            "totalCredits": Decimal("999"),
            "overageCredits": Decimal("0"),
            "totalMessages": 100,
            "totalConversations": 10,
            "totalUsers": 5,
        })
        _put_daily_stat(table, "user-1", "2026-04-10", 50.0)

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        result = handle_usage({}, dynamodb_resource=resource)

        assert result["summary"]["totalUsers"] == 1
        assert result["summary"]["totalCredits"] == 50.0

    @mock_aws
    def test_response_schema_matches_typescript_interface(self):
        """Verify the response matches the UsageResponse TypeScript interface."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        table = resource.Table(TABLE_NAME)
        _put_daily_stat(table, "user-1", "2026-04-10", 100.0, 10.0, 50, 5, 20)

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        result = handle_usage(
            {"startDate": "2026-04-01", "endDate": "2026-04-30"},
            dynamodb_resource=resource,
        )

        # Verify top-level keys
        assert "summary" in result
        assert "users" in result
        assert "period" in result

        # Verify summary keys
        summary = result["summary"]
        assert "totalUsers" in summary
        assert "totalCredits" in summary
        assert "totalOverageCredits" in summary
        assert "averageCreditsPerUser" in summary

        # Verify user keys match UserUsage interface
        user = result["users"][0]
        expected_keys = {
            "userId", "displayName", "userName", "subscriptionTier",
            "totalCredits", "overageCredits", "totalMessages",
            "totalConversations", "averageDailyCredits",
            "lastActiveDate", "daysSinceLastActive",
            "tombstoned",
        }
        assert set(user.keys()) == expected_keys

        # Verify period keys
        assert "startDate" in result["period"]
        assert "endDate" in result["period"]


class TestTierResolution:
    """Tests that scan_user_stats returns the most recent tier for each user."""

    @mock_aws
    def test_returns_latest_tier_after_upgrade(self):
        """User upgraded from PRO to POWER — dashboard should show POWER."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        table = resource.Table(TABLE_NAME)

        # Older records with PRO
        _put_daily_stat(table, "user-1", "2026-04-01", 30.0, subscription_tier="PRO")
        _put_daily_stat(table, "user-1", "2026-04-02", 25.0, subscription_tier="PRO")
        # User upgraded to POWER on April 10
        _put_daily_stat(table, "user-1", "2026-04-10", 40.0, subscription_tier="POWER")
        _put_daily_stat(table, "user-1", "2026-04-11", 35.0, subscription_tier="POWER")

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        result = handle_usage({}, dynamodb_resource=resource)

        assert len(result["users"]) == 1
        assert result["users"][0]["subscriptionTier"] == "POWER"

    @mock_aws
    def test_returns_latest_tier_regardless_of_scan_order(self):
        """Tier should be from the most recent date even if scan returns items out of order."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        table = resource.Table(TABLE_NAME)

        # Insert in non-chronological order
        _put_daily_stat(table, "user-1", "2026-04-15", 10.0, subscription_tier="POWER")
        _put_daily_stat(table, "user-1", "2026-04-01", 20.0, subscription_tier="PRO")
        _put_daily_stat(table, "user-1", "2026-04-10", 15.0, subscription_tier="PRO_PLUS")

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        result = handle_usage({}, dynamodb_resource=resource)

        # April 15 is the most recent — should be POWER
        assert result["users"][0]["subscriptionTier"] == "POWER"

    @mock_aws
    def test_tier_missing_on_some_days(self):
        """If some daily stats lack a tier, the most recent one that has it should win."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        table = resource.Table(TABLE_NAME)

        _put_daily_stat(table, "user-1", "2026-04-01", 10.0, subscription_tier="PRO")
        # Days without tier info
        _put_daily_stat(table, "user-1", "2026-04-05", 15.0)
        _put_daily_stat(table, "user-1", "2026-04-10", 20.0)
        # Latest day with tier
        _put_daily_stat(table, "user-1", "2026-04-12", 25.0, subscription_tier="POWER")
        # Another day without tier after the upgrade
        _put_daily_stat(table, "user-1", "2026-04-13", 30.0)

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        result = handle_usage({}, dynamodb_resource=resource)

        assert result["users"][0]["subscriptionTier"] == "POWER"

    @mock_aws
    def test_multiple_users_each_get_own_latest_tier(self):
        """Each user should independently resolve to their own most recent tier."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        table = resource.Table(TABLE_NAME)

        # User 1: PRO → POWER
        _put_daily_stat(table, "user-1", "2026-04-01", 10.0, subscription_tier="PRO")
        _put_daily_stat(table, "user-1", "2026-04-10", 20.0, subscription_tier="POWER")

        # User 2: stays PRO_PLUS
        _put_daily_stat(table, "user-2", "2026-04-01", 50.0, subscription_tier="PRO_PLUS")
        _put_daily_stat(table, "user-2", "2026-04-10", 60.0, subscription_tier="PRO_PLUS")

        # User 3: PRO_PLUS → PRO (downgrade)
        _put_daily_stat(table, "user-3", "2026-04-01", 5.0, subscription_tier="PRO_PLUS")
        _put_daily_stat(table, "user-3", "2026-04-10", 8.0, subscription_tier="PRO")

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        result = handle_usage({}, dynamodb_resource=resource)

        tier_by_user = {u["userId"]: u["subscriptionTier"] for u in result["users"]}
        assert tier_by_user["user-1"] == "POWER"
        assert tier_by_user["user-2"] == "PRO_PLUS"
        assert tier_by_user["user-3"] == "PRO"

    @mock_aws
    def test_internal_tier_date_field_not_exposed(self):
        """The _latestTierDate helper field must not leak into the API response."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
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
        table = resource.Table(TABLE_NAME)

        _put_daily_stat(table, "user-1", "2026-04-01", 10.0, subscription_tier="PRO")

        os.environ["ANALYTICS_TABLE"] = TABLE_NAME

        result = handle_usage({}, dynamodb_resource=resource)

        user = result["users"][0]
        assert "_latestTierDate" not in user
