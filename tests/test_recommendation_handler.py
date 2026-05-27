"""Tests for ``backend.handlers.recommendation_handler``.

The handler is the I/O boundary: it reads pricing config from SSM, scans
user stats from DynamoDB, builds ``UserUsageData`` instances, and shapes
the JSON response. These tests focus on (a) the new ``period`` block in
the response, and (b) the fact that ``daysActive`` is propagated from
``scan_user_stats`` into ``UserUsageData`` so the engine projects from
active days rather than calendar days.
"""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def pricing_config_dict() -> dict:
    return {
        "tiers": {
            "PRO": {"monthlyPrice": 20, "includedCredits": 1000},
            "PRO_PLUS": {"monthlyPrice": 40, "includedCredits": 2000},
            "POWER": {"monthlyPrice": 200, "includedCredits": 10000},
        },
        "overagePricePerCredit": 0.04,
    }


@pytest.fixture
def mock_ssm(pricing_config_dict: dict):
    """Returns an SSM client mock that yields the standard 3-tier pricing."""
    import json
    from unittest.mock import MagicMock

    ssm = MagicMock()
    ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(pricing_config_dict)}
    }
    # Match the ParameterNotFound exception the handler catches.
    ssm.exceptions.ParameterNotFound = type("ParameterNotFound", (Exception,), {})
    return ssm


class TestPeriodBlock:
    """Every successful response includes a ``period`` block describing the
    analysis window. The frontend renders this as
    "Based on usage from X to Y (N days)" so admins know how to interpret
    the recommendations."""

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "USER_NAMES_TABLE": ""})
    def test_period_echoes_caller_provided_dates(self, mock_ssm) -> None:
        from backend.handlers.recommendation_handler import handle_get_recommendations

        with patch(
            "backend.handlers.recommendation_handler.AnalyticsRepository"
        ) as MockRepo:
            MockRepo.return_value.scan_user_stats.return_value = {"users": []}

            resp = handle_get_recommendations(
                {"startDate": "2026-04-01", "endDate": "2026-05-01"},
                ssm_client=mock_ssm,
            )

        assert resp["period"]["startDate"] == "2026-04-01"
        assert resp["period"]["endDate"] == "2026-05-01"
        # 31 days inclusive (April has 30 days + May 1).
        assert resp["period"]["daysWindow"] == 31

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "USER_NAMES_TABLE": ""})
    def test_period_defaults_to_30_day_rolling_window(self, mock_ssm) -> None:
        from backend.handlers.recommendation_handler import handle_get_recommendations

        with patch(
            "backend.handlers.recommendation_handler.AnalyticsRepository"
        ) as MockRepo:
            MockRepo.return_value.scan_user_stats.return_value = {"users": []}

            resp = handle_get_recommendations({}, ssm_client=mock_ssm)

        # 30-day window inclusive on both ends → 31 days total.
        assert resp["period"]["daysWindow"] == 31
        assert resp["period"]["startDate"] is not None
        assert resp["period"]["endDate"] is not None


class TestActiveDayPropagation:
    """``scan_user_stats`` returns ``daysActive`` per user; the handler
    must thread it into ``UserUsageData`` so the engine projects from
    active days rather than calendar days. A regression here would cause
    sporadic users (e.g., 2 active days in a 30-day window) to be projected
    against the calendar denominator and either disappear from the
    downgrade list (low projection) or pollute the upgrade list."""

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "USER_NAMES_TABLE": ""})
    def test_days_active_is_threaded_to_engine(self, mock_ssm) -> None:
        from backend.handlers.recommendation_handler import handle_get_recommendations

        with patch(
            "backend.handlers.recommendation_handler.AnalyticsRepository"
        ) as MockRepo, patch(
            "backend.handlers.recommendation_handler.compute_recommendations"
        ) as mock_compute:
            from backend.handlers.recommendation_engine import (
                RecommendationResult,
                RecommendationSummary,
            )

            MockRepo.return_value.scan_user_stats.return_value = {
                "users": [
                    {
                        "userId": "u-sporadic",
                        "subscriptionTier": "PRO_PLUS",
                        "totalCredits": Decimal("50.81"),
                        "daysActive": 2,
                        "displayName": "Sporadic User",
                    }
                ]
            }
            mock_compute.return_value = RecommendationResult(
                recommendations=[],
                summary=RecommendationSummary(
                    total_recommendations=0,
                    total_projected_annual_savings=Decimal("0"),
                    upgrade_count=0,
                    downgrade_count=0,
                ),
            )

            handle_get_recommendations({}, ssm_client=mock_ssm)

        # The engine receives the user with ``days_active=2`` so projection
        # becomes (50.81 / 2) × 30 = 762.15 — well below PRO's 1000 included
        # credits, surfacing the downgrade. With the old calendar-day
        # denominator the projection would be ~50.81/month, equally below
        # PRO but driven by the wrong rationale.
        users_arg = mock_compute.call_args[0][0]
        assert len(users_arg) == 1
        assert users_arg[0].user_id == "u-sporadic"
        assert users_arg[0].days_active == 2

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "USER_NAMES_TABLE": ""})
    def test_missing_days_active_defaults_to_zero(self, mock_ssm) -> None:
        """A user record missing ``daysActive`` defaults to 0 — the engine
        will skip them. This matches the behavior of users whose last
        activity falls outside the requested window."""
        from backend.handlers.recommendation_handler import handle_get_recommendations

        with patch(
            "backend.handlers.recommendation_handler.AnalyticsRepository"
        ) as MockRepo, patch(
            "backend.handlers.recommendation_handler.compute_recommendations"
        ) as mock_compute:
            from backend.handlers.recommendation_engine import (
                RecommendationResult,
                RecommendationSummary,
            )

            MockRepo.return_value.scan_user_stats.return_value = {
                "users": [
                    {
                        "userId": "u-no-days",
                        "subscriptionTier": "PRO",
                        "totalCredits": Decimal("100"),
                        # no daysActive field
                    }
                ]
            }
            mock_compute.return_value = RecommendationResult(
                recommendations=[],
                summary=RecommendationSummary(
                    total_recommendations=0,
                    total_projected_annual_savings=Decimal("0"),
                    upgrade_count=0,
                    downgrade_count=0,
                ),
            )

            handle_get_recommendations({}, ssm_client=mock_ssm)

        users_arg = mock_compute.call_args[0][0]
        assert users_arg[0].days_active == 0



# ---------------------------------------------------------------------------
# Inactive subscribers integration
# ---------------------------------------------------------------------------


class TestInactiveSubscribersResponse:
    """The handler runs a second, unwindowed scan to enumerate every paid
    user (including those who have not been active inside the date picker
    window) and merges with ``Activity_Summary`` to produce the inactive
    list. The response carries both ``inactiveSubscribers`` (per-user) and
    ``inactiveSummary`` (aggregate) so the frontend can render header copy
    without re-aggregating client-side.
    """

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "USER_NAMES_TABLE": ""})
    def test_response_includes_inactive_subscribers_block(self, mock_ssm) -> None:
        from backend.handlers.recommendation_handler import handle_get_recommendations

        with patch(
            "backend.handlers.recommendation_handler.AnalyticsRepository"
        ) as MockRepo:
            repo = MockRepo.return_value
            # Windowed call — empty (the inactive user has no activity in window).
            # Lifetime call — returns the inactive PRO_PLUS subscriber.
            repo.scan_user_stats.side_effect = [
                {"users": []},  # windowed
                {  # lifetime
                    "users": [
                        {
                            "userId": "u-stale",
                            "subscriptionTier": "PRO_PLUS",
                            "displayName": "Stale User",
                        }
                    ]
                },
            ]
            repo.scan_activity_summaries.return_value = {
                "u-stale": {"lastActiveDate": "2026-04-01"}
            }

            resp = handle_get_recommendations(
                {"startDate": "2026-04-26", "endDate": "2026-05-26"},
                ssm_client=mock_ssm,
            )

        assert "inactiveSubscribers" in resp
        assert "inactiveSummary" in resp
        assert resp["inactiveSummary"]["thresholdDays"] == 30
        assert resp["inactiveSummary"]["totalInactive"] == 1
        # PRO_PLUS at $40/mo × 12 = $480/year.
        assert resp["inactiveSummary"]["totalAnnualWastedCost"] == 480.0
        item = resp["inactiveSubscribers"][0]
        assert item["userId"] == "u-stale"
        assert item["currentTier"] == "PRO_PLUS"
        assert item["annualWastedCost"] == 480.0

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "USER_NAMES_TABLE": ""})
    def test_lifetime_scan_runs_unwindowed(self, mock_ssm) -> None:
        """The second scan (for lifetime tier presence) must NOT carry the
        date filter — otherwise dormant users would be invisible, exactly
        the bug this feature is meant to surface.
        """
        from backend.handlers.recommendation_handler import handle_get_recommendations

        with patch(
            "backend.handlers.recommendation_handler.AnalyticsRepository"
        ) as MockRepo:
            repo = MockRepo.return_value
            repo.scan_user_stats.side_effect = [
                {"users": []},
                {"users": []},
            ]
            repo.scan_activity_summaries.return_value = {}

            handle_get_recommendations(
                {"startDate": "2026-05-01", "endDate": "2026-05-26"},
                ssm_client=mock_ssm,
            )

        # Two calls: first windowed, second lifetime.
        assert repo.scan_user_stats.call_count == 2
        windowed_kwargs = repo.scan_user_stats.call_args_list[0].kwargs
        lifetime_kwargs = repo.scan_user_stats.call_args_list[1].kwargs

        # Windowed: must have date params.
        assert windowed_kwargs.get("start_date") == "2026-05-01"
        assert windowed_kwargs.get("end_date") == "2026-05-26"
        # Lifetime: must NOT have date params (else dormant users are filtered out).
        assert "start_date" not in lifetime_kwargs
        assert "end_date" not in lifetime_kwargs



# ---------------------------------------------------------------------------
# Tombstone filtering (Requirement 4.1)
# ---------------------------------------------------------------------------


class TestTombstoneFiltering:
    """Tombstoned users (removed from IDC) must be excluded from both the
    upgrade/downgrade list and the inactive subscribers list. They appear
    in actionable views only as historical noise — the admin already
    deleted them, no recommendation is actionable.
    """

    @patch.dict(os.environ, {
        "ANALYTICS_TABLE": "TestAnalyticsTable",
        "USER_NAMES_TABLE": "TestUserNamesTable",
    })
    def test_tombstoned_user_excluded_from_recommendations(self, mock_ssm) -> None:
        from backend.handlers.recommendation_handler import handle_get_recommendations

        with patch(
            "backend.handlers.recommendation_handler.AnalyticsRepository"
        ) as MockRepo, patch(
            "backend.handlers.recommendation_handler.boto3.client"
        ) as mock_boto_client:
            repo = MockRepo.return_value
            repo.scan_user_stats.side_effect = [
                {"users": [
                    {
                        "userId": "u-tombstoned",
                        "subscriptionTier": "PRO_PLUS",
                        "totalCredits": 100,
                        "daysActive": 2,
                    },
                    {
                        "userId": "u-active",
                        "subscriptionTier": "PRO_PLUS",
                        "totalCredits": 100,
                        "daysActive": 2,
                    },
                ]},
                {"users": []},  # lifetime (not tested here)
            ]
            repo.scan_activity_summaries.return_value = {}

            # Simulate the UserNamesTable lookups: tombstoned for one,
            # active for the other.
            ddb_client = MagicMock()
            ddb_client.get_item.side_effect = [
                {"Item": {
                    "userId": {"S": "u-tombstoned"},
                    "status": {"S": "TOMBSTONED"},
                    "displayName": {"S": "Removed User"},
                }},
                {"Item": {
                    "userId": {"S": "u-active"},
                    "status": {"S": "ACTIVE"},
                    "displayName": {"S": "Active User"},
                }},
            ]
            mock_boto_client.return_value = ddb_client

            resp = handle_get_recommendations({}, ssm_client=mock_ssm)

        # Only the active user should appear (as an upgrade or downgrade —
        # depends on engine logic; the tombstoned one must NOT).
        seen_ids = {r["userId"] for r in resp["recommendations"]}
        assert "u-tombstoned" not in seen_ids
