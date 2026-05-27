"""Tests for ``backend.handlers.recommendation_engine``.

The engine is pure (no I/O), so these tests construct ``UserUsageData`` and
``PricingConfig`` directly. They cover the active-day projection contract
introduced after a sporadic-user regression: a user with low calendar-day
average but high active-day intensity must be classified by the intensity
of the days they actually used the product.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.handlers.recommendation_engine import (
    PricingConfig,
    Recommendation,
    TierConfig,
    UserUsageData,
    compute_recommendations,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pricing_three_tier() -> PricingConfig:
    """PRO ($20/1000) → PRO_PLUS ($40/2000) → POWER ($200/10000) at $0.04/credit overage."""
    return PricingConfig(
        tiers=[
            TierConfig(name="PRO", monthly_price=Decimal("20"), included_credits=1000),
            TierConfig(name="PRO_PLUS", monthly_price=Decimal("40"), included_credits=2000),
            TierConfig(name="POWER", monthly_price=Decimal("200"), included_credits=10000),
        ],
        overage_price_per_credit=Decimal("0.04"),
    )


def _user(
    *,
    user_id: str = "u-1",
    tier: str = "PRO",
    total_credits: Decimal = Decimal("0"),
    days_elapsed: int = 30,
    days_active: int = 0,
    overage_enabled: bool = True,
) -> UserUsageData:
    return UserUsageData(
        user_id=user_id,
        display_name=user_id,
        current_tier_name=tier,
        total_credits_current_month=total_credits,
        days_elapsed=days_elapsed,
        days_active=days_active,
        overage_enabled=overage_enabled,
    )


# ---------------------------------------------------------------------------
# Active-day projection (regression suite)
# ---------------------------------------------------------------------------


class TestActiveDayProjection:
    """The engine projects from days the user was actually active.

    A sporadic user with concentrated usage must not be hidden by calendar
    averaging. The fix replaced ``credits / days_elapsed × 30`` with
    ``credits / days_active × 30`` so a user who consumes 50 credits across
    2 active days within a 30-day window is projected at 750/month rather
    than 50/month.
    """

    def test_projection_uses_active_days(self, pricing_three_tier: PricingConfig) -> None:
        # 50 credits across 2 active days → projection = 750/month.
        user = _user(
            tier="PRO_PLUS",
            total_credits=Decimal("50"),
            days_elapsed=30,
            days_active=2,
        )
        result = compute_recommendations([user], pricing_three_tier)

        assert len(result.recommendations) == 1
        rec = result.recommendations[0]
        # (50 / 2) × 30 = 750
        assert rec.projected_monthly_usage == Decimal("750")
        # 750 < PRO included (1000) → downgrade is valid.
        assert rec.recommendation_type == "downgrade"
        assert rec.recommended_tier == "PRO"

    def test_active_days_zero_user_skipped(self, pricing_three_tier: PricingConfig) -> None:
        """No activity in the window → no recommendation. There is no usage
        signal to project from, regardless of how the calendar window is
        configured. This mirrors the production case where a user whose
        last activity falls outside the requested date range silently drops
        out of the recommendation list."""
        user = _user(
            tier="PRO_PLUS",
            total_credits=Decimal("0"),
            days_elapsed=30,
            days_active=0,
        )
        result = compute_recommendations([user], pricing_three_tier)
        assert result.recommendations == []
        assert result.summary.total_recommendations == 0

    def test_one_active_day_projects_to_full_month(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        """Single high-intensity day → engine projects the full daily rate
        across 30 days. This is the upgrade-detection case for users who
        burst-use the product."""
        # 100 credits in a single day → projection = 3000/month.
        user = _user(
            tier="PRO",
            total_credits=Decimal("100"),
            days_elapsed=30,
            days_active=1,
        )
        result = compute_recommendations([user], pricing_three_tier)

        recs_by_type = {r.recommendation_type: r for r in result.recommendations}
        # 3000 > PRO included (1000) → 2000 overage credits × $0.04 = $80/mo.
        # PRO_PLUS includes 2000 → 1000 overage there × $0.04 = $40/mo + $40 tier = $80/mo.
        # POWER includes 10000 → 0 overage there + $200 tier = $200/mo. Worse than upgrading to PRO_PLUS.
        assert "upgrade" in recs_by_type
        upgrade = recs_by_type["upgrade"]
        assert upgrade.projected_monthly_usage == Decimal("3000")
        assert upgrade.recommended_tier == "PRO_PLUS"

    def test_calendar_window_does_not_affect_projection(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        """Same active-day pattern → same projection regardless of how wide
        the calendar window is. ``days_elapsed`` is informational only."""
        narrow = _user(total_credits=Decimal("50"), days_elapsed=30, days_active=2, tier="PRO_PLUS")
        wide = _user(total_credits=Decimal("50"), days_elapsed=90, days_active=2, tier="PRO_PLUS")

        narrow_proj = compute_recommendations([narrow], pricing_three_tier).recommendations[0]
        wide_proj = compute_recommendations([wide], pricing_three_tier).recommendations[0]

        assert narrow_proj.projected_monthly_usage == wide_proj.projected_monthly_usage


# ---------------------------------------------------------------------------
# Real-world regression case
# ---------------------------------------------------------------------------


class TestUserDeletedFromIdentityCenterScenario:
    """Reproduces the production scenario that prompted the engine fix.

    A PRO_PLUS user had two activity days inside a wider window
    (50.81 credits over 2 days), then disappeared from Identity Center
    and stopped generating new STATS#DAILY# rows. With calendar-day
    projection, the engine projected ~50/month and produced a downgrade
    recommendation. With active-day projection the projection becomes
    ~762/month — still under PRO's 1000 included credits, so the
    downgrade is still surfaced, validating that active-day projection
    does not regress the original signal for this case.
    """

    def test_pro_plus_low_usage_yields_downgrade(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        user = _user(
            user_id="d3ec1a4a-7051-7042-36cd-0e517824d4b1",
            tier="PRO_PLUS",
            total_credits=Decimal("50.807292769"),
            days_elapsed=30,
            days_active=2,
        )
        result = compute_recommendations([user], pricing_three_tier)

        assert len(result.recommendations) == 1
        rec: Recommendation = result.recommendations[0]
        assert rec.recommendation_type == "downgrade"
        assert rec.current_tier == "PRO_PLUS"
        assert rec.recommended_tier == "PRO"
        # PRO_PLUS $40/mo - PRO $20/mo = $20/mo × 12 = $240/year.
        assert rec.annual_savings == Decimal("240")


# ---------------------------------------------------------------------------
# Engine-level invariants preserved by the change
# ---------------------------------------------------------------------------


class TestPreservedInvariants:
    def test_overage_disabled_users_are_skipped(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        user = _user(
            tier="PRO_PLUS",
            total_credits=Decimal("100"),
            days_active=2,
            overage_enabled=False,
        )
        assert compute_recommendations([user], pricing_three_tier).recommendations == []

    def test_unknown_tier_is_skipped(self, pricing_three_tier: PricingConfig) -> None:
        user = _user(
            tier="LEGACY_TIER",
            total_credits=Decimal("100"),
            days_active=2,
        )
        assert compute_recommendations([user], pricing_three_tier).recommendations == []

    def test_lowest_tier_has_no_downgrade(self, pricing_three_tier: PricingConfig) -> None:
        user = _user(tier="PRO", total_credits=Decimal("10"), days_active=1)
        result = compute_recommendations([user], pricing_three_tier)
        assert all(r.recommendation_type != "downgrade" for r in result.recommendations)

    def test_highest_tier_has_no_upgrade(self, pricing_three_tier: PricingConfig) -> None:
        user = _user(tier="POWER", total_credits=Decimal("100000"), days_active=10)
        result = compute_recommendations([user], pricing_three_tier)
        assert all(r.recommendation_type != "upgrade" for r in result.recommendations)



# ---------------------------------------------------------------------------
# Inactive subscriber detection
# ---------------------------------------------------------------------------


from backend.handlers.recommendation_engine import (  # noqa: E402
    InactiveSubscriberInput,
    compute_inactive_subscribers,
)


def _inactive_input(
    *,
    user_id: str = "u-inactive",
    tier: str = "PRO_PLUS",
    last_active: str | None = None,
) -> InactiveSubscriberInput:
    return InactiveSubscriberInput(
        user_id=user_id,
        display_name=user_id,
        current_tier_name=tier,
        last_active_date=last_active,
    )


class TestInactiveSubscribers:
    """Lifetime view: who is paying for an idle seat?

    Distinct from upgrade/downgrade — there is no recommended_tier, only
    an annualized wasted cost framing the dollar impact of letting an
    idle subscription continue.
    """

    def test_user_inactive_beyond_threshold_is_flagged(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        # 45 days of inactivity, threshold default 30 → flag.
        user = _inactive_input(tier="PRO_PLUS", last_active="2026-04-11")
        result = compute_inactive_subscribers(
            [user], pricing_three_tier, today="2026-05-26"
        )

        assert len(result) == 1
        flagged = result[0]
        assert flagged.days_inactive == 45
        assert flagged.last_active_date == "2026-04-11"
        # PRO_PLUS $40/mo × 12 = $480/year.
        assert flagged.annual_wasted_cost == Decimal("480")
        assert flagged.current_monthly_cost == Decimal("40")

    def test_user_inactive_below_threshold_is_not_flagged(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        user = _inactive_input(tier="PRO", last_active="2026-05-20")
        result = compute_inactive_subscribers(
            [user], pricing_three_tier, today="2026-05-26"
        )
        assert result == []

    def test_threshold_is_inclusive_lower_bound(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        """Exactly threshold_days of inactivity → flagged."""
        user = _inactive_input(tier="PRO", last_active="2026-04-26")
        # 30 days inactive at threshold=30 → flag.
        result = compute_inactive_subscribers(
            [user], pricing_three_tier, today="2026-05-26", threshold_days=30
        )
        assert len(result) == 1

    def test_user_with_no_activity_summary_is_flagged(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        """No ``lastActiveDate`` at all → flag with ``days_inactive=None``.
        These are users present in the user list with a paid tier but
        without any record of activity. Treating them as definitely
        inactive matches the operational reality.
        """
        user = _inactive_input(tier="PRO_PLUS", last_active=None)
        result = compute_inactive_subscribers(
            [user], pricing_three_tier, today="2026-05-26"
        )
        assert len(result) == 1
        assert result[0].days_inactive is None
        assert result[0].last_active_date is None

    def test_user_with_corrupt_last_active_is_treated_as_never_seen(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        """The engine must be total over its inputs — a corrupt date
        string is treated the same as a missing one rather than raising.
        """
        user = _inactive_input(tier="PRO", last_active="not-a-date")
        result = compute_inactive_subscribers(
            [user], pricing_three_tier, today="2026-05-26"
        )
        assert len(result) == 1
        assert result[0].days_inactive is None

    def test_user_without_priced_tier_is_skipped(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        """Cannot price a seat for an unknown tier, so the user is
        silently dropped from the inactive list."""
        user = _inactive_input(tier="LEGACY", last_active="2026-04-01")
        result = compute_inactive_subscribers(
            [user], pricing_three_tier, today="2026-05-26"
        )
        assert result == []

    def test_results_are_sorted_by_annual_wasted_cost_desc(
        self, pricing_three_tier: PricingConfig
    ) -> None:
        users = [
            _inactive_input(user_id="cheap", tier="PRO", last_active="2026-04-01"),
            _inactive_input(user_id="expensive", tier="POWER", last_active="2026-04-01"),
            _inactive_input(user_id="medium", tier="PRO_PLUS", last_active="2026-04-01"),
        ]
        result = compute_inactive_subscribers(
            users, pricing_three_tier, today="2026-05-26"
        )
        assert [s.user_id for s in result] == ["expensive", "medium", "cheap"]
