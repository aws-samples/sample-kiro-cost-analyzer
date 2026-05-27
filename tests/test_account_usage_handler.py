"""Tests for backend.handlers.account_usage_handler — DynamoDB-based."""

import os
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from backend.handlers.account_usage_handler import (
    _compute_totals,
    _extract_date_from_sk,
    _group_key_for_date,
    _build_timeline,
    handle_account_usage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_analytics_table(dynamodb_resource):
    """Create the Analytics_Table in moto."""
    table = dynamodb_resource.create_table(
        TableName="Analytics_Table",
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
    return table


def _put_global_daily(table, date, credits, overage, messages, conversations, users=1):
    """Insert a GLOBAL STATS#DAILY# item."""
    table.put_item(Item={
        "PK": "GLOBAL",
        "SK": f"STATS#DAILY#{date}",
        "totalCredits": Decimal(str(credits)),
        "overageCredits": Decimal(str(overage)),
        "totalMessages": messages,
        "totalConversations": conversations,
        "totalUsers": users,
    })


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestComputeTotals:
    def test_sums_all_items(self):
        items = [
            {"totalCredits": 100.5, "overageCredits": 10.0, "totalMessages": 50, "totalConversations": 5},
            {"totalCredits": 200.0, "overageCredits": 20.0, "totalMessages": 100, "totalConversations": 10},
        ]
        result = _compute_totals(items)
        assert result["totalCredits"] == 300.5
        assert result["totalOverageCredits"] == 30.0
        assert result["totalMessages"] == 150
        assert result["totalConversations"] == 15

    def test_empty_items(self):
        result = _compute_totals([])
        assert result["totalCredits"] == 0.0
        assert result["totalOverageCredits"] == 0.0
        assert result["totalMessages"] == 0
        assert result["totalConversations"] == 0

    def test_missing_fields_default_to_zero(self):
        items = [{}]
        result = _compute_totals(items)
        assert result["totalCredits"] == 0.0


class TestExtractDateFromSk:
    def test_extracts_date(self):
        assert _extract_date_from_sk("STATS#DAILY#2026-04-15") == "2026-04-15"

    def test_no_prefix(self):
        assert _extract_date_from_sk("2026-04-15") == "2026-04-15"


class TestGroupKeyForDate:
    def test_day_returns_as_is(self):
        assert _group_key_for_date("2026-04-15", "day") == "2026-04-15"

    def test_month_returns_first_of_month(self):
        assert _group_key_for_date("2026-04-15", "month") == "2026-04-01"
        assert _group_key_for_date("2026-12-31", "month") == "2026-12-01"

    def test_week_returns_monday(self):
        # 2026-04-15 is a Wednesday → Monday is 2026-04-13
        assert _group_key_for_date("2026-04-15", "week") == "2026-04-13"
        # 2026-04-13 is already Monday
        assert _group_key_for_date("2026-04-13", "week") == "2026-04-13"


class TestBuildTimeline:
    def test_day_granularity(self):
        items = [
            {"SK": "STATS#DAILY#2026-04-01", "totalCredits": 100, "overageCredits": 10, "totalMessages": 50, "totalConversations": 5},
            {"SK": "STATS#DAILY#2026-04-02", "totalCredits": 200, "overageCredits": 20, "totalMessages": 100, "totalConversations": 10},
        ]
        result = _build_timeline(items, "day")
        assert len(result) == 2
        assert result[0]["period"] == "2026-04-01"
        assert result[0]["totalCredits"] == 100.0
        assert result[1]["period"] == "2026-04-02"

    def test_month_granularity_groups(self):
        items = [
            {"SK": "STATS#DAILY#2026-04-01", "totalCredits": 100, "overageCredits": 0, "totalMessages": 10, "totalConversations": 1},
            {"SK": "STATS#DAILY#2026-04-15", "totalCredits": 200, "overageCredits": 0, "totalMessages": 20, "totalConversations": 2},
            {"SK": "STATS#DAILY#2026-05-01", "totalCredits": 50, "overageCredits": 0, "totalMessages": 5, "totalConversations": 1},
        ]
        result = _build_timeline(items, "month")
        assert len(result) == 2
        assert result[0]["period"] == "2026-04-01"
        assert result[0]["totalCredits"] == 300.0
        assert result[0]["totalMessages"] == 30
        assert result[1]["period"] == "2026-05-01"
        assert result[1]["totalCredits"] == 50.0

    def test_week_granularity_groups(self):
        # 2026-04-13 Mon, 2026-04-14 Tue, 2026-04-20 Mon (next week)
        items = [
            {"SK": "STATS#DAILY#2026-04-13", "totalCredits": 100, "overageCredits": 0, "totalMessages": 10, "totalConversations": 1},
            {"SK": "STATS#DAILY#2026-04-14", "totalCredits": 50, "overageCredits": 0, "totalMessages": 5, "totalConversations": 1},
            {"SK": "STATS#DAILY#2026-04-20", "totalCredits": 200, "overageCredits": 0, "totalMessages": 20, "totalConversations": 2},
        ]
        result = _build_timeline(items, "week")
        assert len(result) == 2
        assert result[0]["period"] == "2026-04-13"
        assert result[0]["totalCredits"] == 150.0
        assert result[1]["period"] == "2026-04-20"
        assert result[1]["totalCredits"] == 200.0

    def test_empty_items(self):
        assert _build_timeline([], "day") == []

    def test_sorted_output(self):
        items = [
            {"SK": "STATS#DAILY#2026-04-03", "totalCredits": 30, "overageCredits": 0, "totalMessages": 3, "totalConversations": 1},
            {"SK": "STATS#DAILY#2026-04-01", "totalCredits": 10, "overageCredits": 0, "totalMessages": 1, "totalConversations": 1},
        ]
        result = _build_timeline(items, "day")
        assert result[0]["period"] == "2026-04-01"
        assert result[1]["period"] == "2026-04-03"


# ---------------------------------------------------------------------------
# Integration tests with moto
# ---------------------------------------------------------------------------

@mock_aws
class TestHandleAccountUsage:
    def _setup_table(self):
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_analytics_table(ddb)
        return ddb, table

    def test_returns_full_response_structure(self):
        ddb, table = self._setup_table()
        _put_global_daily(table, "2026-04-01", 500.0, 25.0, 250, 15)
        _put_global_daily(table, "2026-04-02", 500.0, 25.0, 250, 15)

        with _env(ANALYTICS_TABLE="Analytics_Table"):
            result = handle_account_usage(
                {"startDate": "2026-04-01", "endDate": "2026-04-30", "granularity": "day"},
                dynamodb_resource=ddb,
            )

        assert result["totals"]["totalCredits"] == 1000.0
        assert result["totals"]["totalOverageCredits"] == 50.0
        assert result["totals"]["totalMessages"] == 500
        assert result["totals"]["totalConversations"] == 30
        assert len(result["timeline"]) == 2
        assert result["breakdownByTier"] == []
        assert result["breakdownByClientType"] == []
        assert result["period"] == {
            "startDate": "2026-04-01",
            "endDate": "2026-04-30",
            "granularity": "day",
        }

    def test_default_granularity_is_day(self):
        ddb, table = self._setup_table()
        _put_global_daily(table, "2026-04-01", 100, 0, 10, 1)

        with _env(ANALYTICS_TABLE="Analytics_Table"):
            result = handle_account_usage({}, dynamodb_resource=ddb)

        assert result["period"]["granularity"] == "day"

    def test_invalid_granularity_defaults_to_day(self):
        ddb, table = self._setup_table()

        with _env(ANALYTICS_TABLE="Analytics_Table"):
            result = handle_account_usage({"granularity": "invalid"}, dynamodb_resource=ddb)

        assert result["period"]["granularity"] == "day"

    def test_week_granularity(self):
        ddb, table = self._setup_table()
        # Mon-Tue same week, Mon next week
        _put_global_daily(table, "2026-04-13", 100, 0, 10, 1)
        _put_global_daily(table, "2026-04-14", 50, 0, 5, 1)
        _put_global_daily(table, "2026-04-20", 200, 0, 20, 2)

        with _env(ANALYTICS_TABLE="Analytics_Table"):
            result = handle_account_usage({"granularity": "week"}, dynamodb_resource=ddb)

        assert result["period"]["granularity"] == "week"
        assert len(result["timeline"]) == 2
        assert result["timeline"][0]["totalCredits"] == 150.0
        assert result["timeline"][1]["totalCredits"] == 200.0

    def test_month_granularity(self):
        ddb, table = self._setup_table()
        _put_global_daily(table, "2026-04-01", 100, 0, 10, 1)
        _put_global_daily(table, "2026-04-15", 200, 0, 20, 2)
        _put_global_daily(table, "2026-05-01", 50, 0, 5, 1)

        with _env(ANALYTICS_TABLE="Analytics_Table"):
            result = handle_account_usage({"granularity": "month"}, dynamodb_resource=ddb)

        assert result["period"]["granularity"] == "month"
        assert len(result["timeline"]) == 2
        assert result["timeline"][0]["period"] == "2026-04-01"
        assert result["timeline"][0]["totalCredits"] == 300.0
        assert result["timeline"][1]["period"] == "2026-05-01"

    def test_date_range_filtering(self):
        ddb, table = self._setup_table()
        _put_global_daily(table, "2026-03-31", 999, 0, 99, 9)  # outside range
        _put_global_daily(table, "2026-04-01", 100, 10, 50, 5)
        _put_global_daily(table, "2026-04-15", 200, 20, 100, 10)
        _put_global_daily(table, "2026-05-01", 888, 0, 88, 8)  # outside range

        with _env(ANALYTICS_TABLE="Analytics_Table"):
            result = handle_account_usage(
                {"startDate": "2026-04-01", "endDate": "2026-04-30"},
                dynamodb_resource=ddb,
            )

        assert result["totals"]["totalCredits"] == 300.0
        assert result["totals"]["totalOverageCredits"] == 30.0
        assert len(result["timeline"]) == 2

    def test_no_filters_no_period_dates(self):
        ddb, table = self._setup_table()

        with _env(ANALYTICS_TABLE="Analytics_Table"):
            result = handle_account_usage({}, dynamodb_resource=ddb)

        assert "startDate" not in result["period"]
        assert "endDate" not in result["period"]
        assert result["period"]["granularity"] == "day"

    def test_empty_results(self):
        ddb, table = self._setup_table()

        with _env(ANALYTICS_TABLE="Analytics_Table"):
            result = handle_account_usage({}, dynamodb_resource=ddb)

        assert result["totals"]["totalCredits"] == 0.0
        assert result["totals"]["totalOverageCredits"] == 0.0
        assert result["totals"]["totalMessages"] == 0
        assert result["totals"]["totalConversations"] == 0
        assert result["timeline"] == []
        assert result["breakdownByTier"] == []
        assert result["breakdownByClientType"] == []

    def test_invalid_dates_ignored(self):
        ddb, table = self._setup_table()
        _put_global_daily(table, "2026-04-01", 100, 0, 10, 1)

        with _env(ANALYTICS_TABLE="Analytics_Table"):
            result = handle_account_usage(
                {"startDate": "bad", "endDate": "bad"},
                dynamodb_resource=ddb,
            )

        # Invalid dates are ignored → no date filter → returns all items
        assert result["totals"]["totalCredits"] == 100.0

    def test_period_includes_dates_when_provided(self):
        ddb, table = self._setup_table()

        with _env(ANALYTICS_TABLE="Analytics_Table"):
            result = handle_account_usage(
                {"startDate": "2026-04-01", "endDate": "2026-04-30", "granularity": "month"},
                dynamodb_resource=ddb,
            )

        assert result["period"]["startDate"] == "2026-04-01"
        assert result["period"]["endDate"] == "2026-04-30"
        assert result["period"]["granularity"] == "month"


# ---------------------------------------------------------------------------
# Context manager for env vars
# ---------------------------------------------------------------------------

import contextlib

@contextlib.contextmanager
def _env(**kwargs):
    old = {}
    for k, v in kwargs.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
