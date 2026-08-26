"""Tests for AnalyticsRepository summary aggregation and scan_user_stats.

Covers the dashboard-active-user-count spec: the summary must be aggregated
over the ENTIRE filtered population, invariant to pagination, so the
"Total Users" card is no longer capped at the 50-row page size.

- Pure-function property tests exercise ``aggregate_user_summary`` (Properties
  3 and 4 from the design, plus count totality on the pure input).
- moto-based integration tests exercise ``scan_user_stats`` end to end:
  count totality across >50 users, pagination invariance (Property 2), and
  tier-filter soundness (Property 5).
"""

import boto3
import pytest
from decimal import Decimal
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from backend.repository.analytics_repository import (
    AnalyticsRepository,
    aggregate_user_summary,
)


TABLE_NAME = "TestAnalyticsTable"


# ---------------------------------------------------------------------------
# Pure-function unit tests: aggregate_user_summary
# ---------------------------------------------------------------------------


class TestAggregateUserSummary:
    def test_basic_totals(self):
        users = [
            {"totalCredits": 100.0, "overageCredits": 10.0},
            {"totalCredits": 200.0, "overageCredits": 20.0},
            {"totalCredits": 50.0, "overageCredits": 5.0},
        ]
        summary = aggregate_user_summary(users)
        assert summary["totalUsers"] == 3
        assert summary["totalCredits"] == 350.0
        assert summary["totalOverageCredits"] == 35.0
        assert summary["averageCreditsPerUser"] == round(350.0 / 3, 2)

    def test_empty_list(self):
        summary = aggregate_user_summary([])
        assert summary["totalUsers"] == 0
        assert summary["totalCredits"] == 0
        assert summary["totalOverageCredits"] == 0
        assert summary["averageCreditsPerUser"] == 0

    def test_missing_fields_default_to_zero(self):
        users = [{"userId": "u1"}, {"userId": "u2", "totalCredits": 10.0}]
        summary = aggregate_user_summary(users)
        assert summary["totalUsers"] == 2
        assert summary["totalCredits"] == 10.0
        assert summary["totalOverageCredits"] == 0


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis, 100+ iterations) — pure function
# ---------------------------------------------------------------------------

_user_strategy = st.fixed_dictionaries(
    {
        "totalCredits": st.floats(min_value=0, max_value=1_000_000, allow_nan=False, allow_infinity=False),
        "overageCredits": st.floats(min_value=0, max_value=1_000_000, allow_nan=False, allow_infinity=False),
    }
)


class TestAggregateSummaryProperties:
    @settings(max_examples=100)
    @given(users=st.lists(_user_strategy, max_size=300))
    def test_count_totality(self, users):
        """Property 1: totalUsers equals the number of users in the input."""
        summary = aggregate_user_summary(users)
        assert summary["totalUsers"] == len(users)

    @settings(max_examples=100)
    @given(users=st.lists(_user_strategy, max_size=300))
    def test_total_conservation(self, users):
        """Property 3: summary totals equal the sum over the whole list."""
        summary = aggregate_user_summary(users)
        expected_credits = round(sum(float(u["totalCredits"]) for u in users), 2)
        expected_overage = round(sum(float(u["overageCredits"]) for u in users), 2)
        assert summary["totalCredits"] == expected_credits
        assert summary["totalOverageCredits"] == expected_overage

    @settings(max_examples=100)
    @given(users=st.lists(_user_strategy, max_size=300))
    def test_average_coherence(self, users):
        """Property 4: average equals total/count (2dp), or 0 when empty."""
        summary = aggregate_user_summary(users)
        if summary["totalUsers"] > 0:
            expected = round(summary["totalCredits"] / summary["totalUsers"], 2)
            assert summary["averageCreditsPerUser"] == expected
        else:
            assert summary["averageCreditsPerUser"] == 0


# ---------------------------------------------------------------------------
# Integration tests (moto): scan_user_stats
# ---------------------------------------------------------------------------


def _create_table(resource):
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
    return resource.Table(TABLE_NAME)


def _put_daily_stat(table, user_id, date, credits, overage=0.0, subscription_tier=""):
    item = {
        "PK": f"USER#{user_id}",
        "SK": f"STATS#DAILY#{date}",
        "totalCredits": Decimal(str(credits)),
        "overageCredits": Decimal(str(overage)),
        "totalMessages": 1,
        "totalConversations": 1,
        "totalInteractions": 1,
    }
    if subscription_tier:
        item["subscriptionTier"] = subscription_tier
    table.put_item(Item=item)


class TestScanUserStatsSummary:
    @mock_aws
    def test_summary_counts_all_users_beyond_page(self):
        """totalUsers reflects every active user, not the 50-row page cap."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_table(resource)

        for i in range(60):
            _put_daily_stat(table, f"user-{i:03d}", "2026-04-10", credits=float(i + 1))

        repo = AnalyticsRepository(TABLE_NAME, dynamodb_resource=resource)
        result = repo.scan_user_stats(limit=50)

        # Page is capped at 50, but the summary counts all 60.
        assert len(result["users"]) == 50
        assert result["nextToken"] is not None
        assert result["summary"]["totalUsers"] == 60
        # Credits sum = 1 + 2 + ... + 60 = 1830
        assert result["summary"]["totalCredits"] == 1830.0

    @mock_aws
    def test_summary_invariant_across_pages(self):
        """Property 2: the summary is identical on page 1 and page 2."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_table(resource)

        for i in range(60):
            _put_daily_stat(table, f"user-{i:03d}", "2026-04-10", credits=float(i + 1))

        repo = AnalyticsRepository(TABLE_NAME, dynamodb_resource=resource)
        page1 = repo.scan_user_stats(limit=50)
        page2 = repo.scan_user_stats(limit=50, next_token=page1["nextToken"])

        assert page1["summary"] == page2["summary"]
        assert len(page2["users"]) == 10  # remaining users
        assert page2["nextToken"] is None

    @mock_aws
    def test_summary_scoped_to_tier_filter(self):
        """Property 5: with a tier filter, the summary counts only that tier."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_table(resource)

        for i in range(10):
            _put_daily_stat(table, f"pro-{i}", "2026-04-10", credits=10.0, subscription_tier="PRO")
        for i in range(5):
            _put_daily_stat(table, f"power-{i}", "2026-04-10", credits=20.0, subscription_tier="POWER")

        repo = AnalyticsRepository(TABLE_NAME, dynamodb_resource=resource)
        result = repo.scan_user_stats(limit=50, subscription_tier="POWER")

        assert result["summary"]["totalUsers"] == 5
        assert result["summary"]["totalCredits"] == 100.0
        assert all(u["subscriptionTier"] == "POWER" for u in result["users"])

    @mock_aws
    def test_summary_scoped_to_date_range(self):
        """A date range restricts the summary to daily stats inside the window."""
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_table(resource)

        _put_daily_stat(table, "user-1", "2026-03-01", credits=100.0)  # outside
        _put_daily_stat(table, "user-1", "2026-04-10", credits=40.0)   # inside
        _put_daily_stat(table, "user-2", "2026-04-15", credits=60.0)   # inside

        repo = AnalyticsRepository(TABLE_NAME, dynamodb_resource=resource)
        result = repo.scan_user_stats(
            limit=50, start_date="2026-04-01", end_date="2026-04-30"
        )

        assert result["summary"]["totalUsers"] == 2
        assert result["summary"]["totalCredits"] == 100.0

    @mock_aws
    def test_empty_table_summary(self):
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(resource)

        repo = AnalyticsRepository(TABLE_NAME, dynamodb_resource=resource)
        result = repo.scan_user_stats(limit=50)

        assert result["users"] == []
        assert result["nextToken"] is None
        assert result["summary"]["totalUsers"] == 0
        assert result["summary"]["averageCreditsPerUser"] == 0
