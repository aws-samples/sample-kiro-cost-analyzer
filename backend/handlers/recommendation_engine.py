"""Tier optimization recommendation engine — pure computation logic.

Analyzes per-user credit consumption, projects monthly usage, and determines
whether upgrading or downgrading a subscription tier would reduce costs. All
functions are pure (no I/O, no boto3, no os, no logging) to enable comprehensive
property-based testing via Hypothesis.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class TierConfig:
    """Single tier definition.

    Attributes:
        name: Non-empty tier identifier.
        monthly_price: Non-negative monthly subscription cost (USD).
        included_credits: Positive integer of credits included in the tier.
    """

    name: str
    monthly_price: Decimal
    included_credits: int


@dataclass(frozen=True)
class PricingConfig:
    """Complete pricing configuration.

    Attributes:
        tiers: List of tier definitions ordered by ascending monthly_price.
        overage_price_per_credit: Positive rate charged per credit beyond included.
    """

    tiers: list[TierConfig]
    overage_price_per_credit: Decimal


@dataclass(frozen=True)
class UserUsageData:
    """Aggregated usage data for a single user.

    Attributes:
        user_id: Unique user identifier.
        display_name: Human-readable user name.
        current_tier_name: Name of the user's current subscription tier.
        total_credits_current_month: Total credits consumed in the active window.
        days_elapsed: Calendar days in the requested date range.
        days_active: Days the user actually had any activity in the range.
            ``days_active <= days_elapsed``. When ``> 0``, the engine projects
            monthly usage from this value (``(credits / days_active) * 30``)
            so a user who used 50 credits across two days is not extrapolated
            to 50 credits/month — the signal is the *intensity* of the days
            they actually showed up. When ``0`` (no activity), the user is
            skipped because there is no usage signal to project from.
        overage_enabled: Whether the user's subscription has overage billing enabled.
    """

    user_id: str
    display_name: str
    current_tier_name: str
    total_credits_current_month: Decimal
    days_elapsed: int
    days_active: int
    overage_enabled: bool


@dataclass(frozen=True)
class Recommendation:
    """A single tier optimization recommendation.

    Attributes:
        user_id: Unique user identifier.
        display_name: Human-readable user name.
        current_tier: Name of the user's current tier.
        recommended_tier: Name of the recommended tier.
        recommendation_type: Either "upgrade" or "downgrade".
        projected_monthly_usage: Estimated full-month credit usage.
        projected_overage_cost: Projected monthly overage cost at current tier.
        annual_savings: Projected yearly cost reduction if recommendation is applied.
        current_monthly_cost: Current tier monthly price plus projected overage.
        recommended_monthly_cost: Recommended tier monthly price plus any overage there.
    """

    user_id: str
    display_name: str
    current_tier: str
    recommended_tier: str
    recommendation_type: Literal["upgrade", "downgrade"]
    projected_monthly_usage: Decimal
    projected_overage_cost: Decimal
    annual_savings: Decimal
    current_monthly_cost: Decimal
    recommended_monthly_cost: Decimal


@dataclass(frozen=True)
class RecommendationSummary:
    """Aggregate summary of all recommendations.

    Attributes:
        total_recommendations: Total number of recommendations produced.
        total_projected_annual_savings: Sum of annual_savings across all recommendations.
        upgrade_count: Number of upgrade recommendations.
        downgrade_count: Number of downgrade recommendations.
    """

    total_recommendations: int
    total_projected_annual_savings: Decimal
    upgrade_count: int
    downgrade_count: int


@dataclass(frozen=True)
class RecommendationResult:
    """Complete result from the recommendation engine.

    Attributes:
        recommendations: List of recommendations sorted by annual_savings descending.
        summary: Aggregate summary of all recommendations.
    """

    recommendations: list[Recommendation]
    summary: RecommendationSummary


def validate_pricing_config(config_dict: dict) -> tuple[bool, str]:
    """Validate a raw pricing config dict.

    Checks:
    - 2–10 tiers
    - Non-empty tier names
    - Non-negative monthlyPrice per tier
    - Positive includedCredits (int) per tier
    - Ascending monthlyPrice across tiers
    - Positive overagePricePerCredit

    Args:
        config_dict: Dictionary with expected structure:
            {"tiers": {"<name>": {"monthlyPrice": num, "includedCredits": int}},
             "overagePricePerCredit": num}

    Returns:
        Tuple of (is_valid, error_message). Error message is empty when valid.
    """
    # Check top-level structure
    if not isinstance(config_dict, dict):
        return False, "Configuration must be a dictionary"

    if "tiers" not in config_dict:
        return False, "Missing required field: tiers"

    if "overagePricePerCredit" not in config_dict:
        return False, "Missing required field: overagePricePerCredit"

    tiers = config_dict["tiers"]
    if not isinstance(tiers, dict):
        return False, "tiers must be a dictionary"

    # Validate tier count
    tier_count = len(tiers)
    if tier_count < 2:
        return False, "Configuration must have at least 2 tiers"
    if tier_count > 10:
        return False, "Configuration must have at most 10 tiers"

    # Validate overagePricePerCredit
    overage_rate = config_dict["overagePricePerCredit"]
    if not isinstance(overage_rate, (int, float, Decimal)):
        return False, "overagePricePerCredit must be a positive number"
    if isinstance(overage_rate, bool):
        return False, "overagePricePerCredit must be a positive number"
    if Decimal(str(overage_rate)) <= 0:
        return False, "overagePricePerCredit must be a positive number"

    # Validate each tier
    prices = []
    for tier_name, tier_data in tiers.items():
        # Non-empty tier name
        if not isinstance(tier_name, str) or not tier_name.strip():
            return False, "Tier names must be non-empty strings"

        if not isinstance(tier_data, dict):
            return False, f"tiers.{tier_name} must be a dictionary"

        # monthlyPrice
        if "monthlyPrice" not in tier_data:
            return False, f"tiers.{tier_name}.monthlyPrice is required"
        monthly_price = tier_data["monthlyPrice"]
        if isinstance(monthly_price, bool):
            return False, f"tiers.{tier_name}.monthlyPrice must be a non-negative number"
        if not isinstance(monthly_price, (int, float, Decimal)):
            return False, f"tiers.{tier_name}.monthlyPrice must be a non-negative number"
        if Decimal(str(monthly_price)) < 0:
            return False, f"tiers.{tier_name}.monthlyPrice must be a non-negative number"

        # includedCredits
        if "includedCredits" not in tier_data:
            return False, f"tiers.{tier_name}.includedCredits is required"
        included_credits = tier_data["includedCredits"]
        if isinstance(included_credits, bool):
            return False, f"tiers.{tier_name}.includedCredits must be a positive integer"
        if not isinstance(included_credits, int):
            return False, f"tiers.{tier_name}.includedCredits must be a positive integer"
        if included_credits <= 0:
            return False, f"tiers.{tier_name}.includedCredits must be a positive integer"

        prices.append(Decimal(str(monthly_price)))

    # Validate ascending monthlyPrice
    for i in range(1, len(prices)):
        if prices[i] <= prices[i - 1]:
            return False, "Tiers must have strictly ascending monthlyPrice values"

    return True, ""


def parse_pricing_config(config_dict: dict) -> PricingConfig:
    """Parse a validated config dict into a PricingConfig.

    Validates the config first, then converts to typed dataclasses with tiers
    sorted by ascending monthly price.

    Args:
        config_dict: Dictionary with pricing configuration.

    Returns:
        PricingConfig instance with tiers sorted by ascending monthly_price.

    Raises:
        ValueError: If the configuration is invalid.
    """
    is_valid, error_message = validate_pricing_config(config_dict)
    if not is_valid:
        raise ValueError(error_message)

    tiers_dict = config_dict["tiers"]
    overage_rate = Decimal(str(config_dict["overagePricePerCredit"]))

    tier_configs = []
    for tier_name, tier_data in tiers_dict.items():
        tier_configs.append(
            TierConfig(
                name=tier_name,
                monthly_price=Decimal(str(tier_data["monthlyPrice"])),
                included_credits=tier_data["includedCredits"],
            )
        )

    # Sort by ascending monthly_price
    tier_configs.sort(key=lambda t: t.monthly_price)

    return PricingConfig(tiers=tier_configs, overage_price_per_credit=overage_rate)


@dataclass(frozen=True)
class InactiveSubscriber:
    """A paid subscriber with no recent activity.

    Distinct from :class:`Recommendation` because the suggested action is
    qualitatively different — there is no recommended_tier to switch to,
    only a question for the admin: keep paying for an idle seat, or revoke
    the subscription. The annualized wasted cost is the framing that lets
    this signal sit in the same dollar-denominated dashboard as the
    upgrade/downgrade list.

    Attributes:
        user_id: Unique user identifier.
        display_name: Human-readable user name.
        current_tier: Name of the user's paid tier.
        current_monthly_cost: The tier's monthly subscription price.
        days_inactive: Days between ``lastActiveDate`` and ``today``.
            ``None`` when the user has no Activity_Summary record at all
            (never seen, but appears in the user list with a tier).
        last_active_date: ISO date of the user's most recent activity, or
            ``None`` when no activity has ever been recorded.
        annual_wasted_cost: Projected yearly subscription cost if the
            inactivity continues. Equal to ``current_monthly_cost × 12``.
    """

    user_id: str
    display_name: str
    current_tier: str
    current_monthly_cost: Decimal
    days_inactive: int | None
    last_active_date: str | None
    annual_wasted_cost: Decimal


@dataclass(frozen=True)
class InactiveSubscriberInput:
    """Input shape for :func:`compute_inactive_subscribers`.

    Each item represents a subscriber and the freshest signal we have
    about their last activity. ``last_active_date`` is the ISO date string
    pulled from ``Activity_Summary``. ``None`` means the user is on a paid
    tier but has no Activity_Summary at all — usually a brand-new account
    or a corrupt aggregate. The engine treats both cases as "candidate
    inactive" and lets the threshold gate them out.
    """

    user_id: str
    display_name: str
    current_tier_name: str
    last_active_date: str | None


def compute_inactive_subscribers(
    users: list[InactiveSubscriberInput],
    pricing: PricingConfig,
    today: str,
    threshold_days: int = 30,
) -> list[InactiveSubscriber]:
    """Identify paid subscribers with no activity for at least ``threshold_days``.

    Pure function — deterministic for identical inputs. Sorted by
    ``annual_wasted_cost`` descending so the most expensive idle seats
    appear first.

    The threshold is a closed lower bound: a user with exactly
    ``threshold_days`` of inactivity SHALL be flagged. Users with no
    ``last_active_date`` at all are flagged unconditionally because we
    have no evidence they have ever used the product.

    Args:
        users: Subscribers to evaluate. Users without a tier in ``pricing``
            are skipped silently — the engine cannot price their seat.
        pricing: Tier pricing configuration. The user's current tier must
            appear here for the cost to be priced.
        today: ISO date string (``YYYY-MM-DD``) representing the reference
            "now". Passed in explicitly so tests can pin time and so the
            handler controls the clock.
        threshold_days: Minimum days of inactivity to flag. Default 30
            mirrors the existing ``engagement-thresholds`` Dormant cutoff.

    Returns:
        List of inactive subscribers sorted by ``annual_wasted_cost``
        descending.
    """
    from datetime import date

    today_date = date.fromisoformat(today)
    tier_by_name: dict[str, TierConfig] = {t.name: t for t in pricing.tiers}

    inactive: list[InactiveSubscriber] = []

    for user in users:
        # Only price subscribers whose tier is in the pricing config.
        tier = tier_by_name.get(user.current_tier_name)
        if tier is None:
            continue

        days_inactive: int | None
        if user.last_active_date is None:
            # No Activity_Summary at all → flag unconditionally.
            days_inactive = None
        else:
            try:
                last = date.fromisoformat(user.last_active_date)
            except (TypeError, ValueError):
                # Corrupt or non-string date → treat as "never seen" rather
                # than raising; the engine must be total over its inputs.
                days_inactive = None
            else:
                days_inactive = (today_date - last).days
                if days_inactive < threshold_days:
                    continue

        annual_wasted_cost = tier.monthly_price * Decimal("12")

        inactive.append(
            InactiveSubscriber(
                user_id=user.user_id,
                display_name=user.display_name,
                current_tier=user.current_tier_name,
                current_monthly_cost=tier.monthly_price,
                days_inactive=days_inactive,
                last_active_date=user.last_active_date,
                annual_wasted_cost=annual_wasted_cost,
            )
        )

    inactive.sort(key=lambda s: s.annual_wasted_cost, reverse=True)
    return inactive


def compute_recommendations(
    users: list[UserUsageData],
    pricing: PricingConfig,
) -> RecommendationResult:
    """Compute tier optimization recommendations for all users.

    Pure function — deterministic for identical inputs.

    Algorithm:
    1. Filter to overage_enabled users only
    2. Skip users with no activity in the window (``days_active == 0``)
    3. For each user, project monthly usage from active days:
       ``(total_credits / days_active) × 30``. Active-day projection
       reflects the intensity of the days the user actually used the
       product, so a sporadic user is not penalized by the calendar gaps.
    4. Compute overage cost at current tier: max(0, projected - included) × rate
    5. Search for optimal upgrade tier (maximizes annual savings)
    6. Check for downgrade opportunity (projected < lower tier's included credits)
    7. Sort recommendations by annual_savings descending

    Args:
        users: List of user usage data.
        pricing: Complete pricing configuration.

    Returns:
        RecommendationResult with sorted recommendations and summary.
    """
    recommendations: list[Recommendation] = []
    tiers = pricing.tiers  # Already sorted by ascending monthly_price

    # Build tier lookup by name
    tier_by_name: dict[str, TierConfig] = {t.name: t for t in tiers}

    # Build tier index lookup (position in sorted list)
    tier_index_by_name: dict[str, int] = {t.name: i for i, t in enumerate(tiers)}

    for user in users:
        # Only process users with overage_enabled = True
        if not user.overage_enabled:
            continue

        # Skip users whose tier is not in the pricing config
        if user.current_tier_name not in tier_by_name:
            continue

        current_tier = tier_by_name[user.current_tier_name]
        current_tier_idx = tier_index_by_name[user.current_tier_name]

        # Project monthly usage from the days the user was actually active.
        # Days with zero activity are not noise — they're absence of signal.
        # Extrapolating a sporadic user across the calendar window inflates
        # apparent consumption and drowns out the downgrade case.
        if user.days_active <= 0:
            continue

        projected_monthly_usage = (
            user.total_credits_current_month / Decimal(str(user.days_active))
        ) * Decimal("30")

        # Compute overage cost at current tier
        overage_credits = max(
            Decimal("0"), projected_monthly_usage - Decimal(str(current_tier.included_credits))
        )
        projected_overage_cost = overage_credits * pricing.overage_price_per_credit

        # Current monthly cost = tier price + projected overage
        current_monthly_cost = current_tier.monthly_price + projected_overage_cost

        # --- Upgrade logic ---
        # Skip upgrade for highest-tier users
        # Skip upgrade for users with zero projected overage
        upgrade_rec = None
        if current_tier_idx < len(tiers) - 1 and projected_overage_cost > 0:
            best_savings = Decimal("0")
            best_tier: TierConfig | None = None

            # Search all higher tiers for optimal upgrade
            for higher_tier in tiers[current_tier_idx + 1:]:
                tier_delta = higher_tier.monthly_price - current_tier.monthly_price
                # Annual savings = (projected_overage_cost - tier_delta) × 12
                annual_savings = (projected_overage_cost - tier_delta) * Decimal("12")

                if annual_savings > best_savings:
                    best_savings = annual_savings
                    best_tier = higher_tier

            if best_tier is not None and best_savings > 0:
                # Compute recommended monthly cost
                rec_overage_credits = max(
                    Decimal("0"),
                    projected_monthly_usage - Decimal(str(best_tier.included_credits)),
                )
                rec_overage_cost = rec_overage_credits * pricing.overage_price_per_credit
                recommended_monthly_cost = best_tier.monthly_price + rec_overage_cost

                upgrade_rec = Recommendation(
                    user_id=user.user_id,
                    display_name=user.display_name,
                    current_tier=user.current_tier_name,
                    recommended_tier=best_tier.name,
                    recommendation_type="upgrade",
                    projected_monthly_usage=projected_monthly_usage,
                    projected_overage_cost=projected_overage_cost,
                    annual_savings=best_savings,
                    current_monthly_cost=current_monthly_cost,
                    recommended_monthly_cost=recommended_monthly_cost,
                )

        # --- Downgrade logic ---
        # Skip downgrade for lowest-tier users
        downgrade_rec = None
        if current_tier_idx > 0:
            # Check the next lower tier
            lower_tier = tiers[current_tier_idx - 1]

            # Downgrade iff projected < lower tier's included credits
            if projected_monthly_usage < Decimal(str(lower_tier.included_credits)):
                # Annual savings = (current_tier.monthly_price - lower_tier.monthly_price) × 12
                annual_savings = (
                    current_tier.monthly_price - lower_tier.monthly_price
                ) * Decimal("12")

                # Compute recommended monthly cost for downgrade
                rec_overage_credits = max(
                    Decimal("0"),
                    projected_monthly_usage - Decimal(str(lower_tier.included_credits)),
                )
                rec_overage_cost = rec_overage_credits * pricing.overage_price_per_credit
                recommended_monthly_cost = lower_tier.monthly_price + rec_overage_cost

                downgrade_rec = Recommendation(
                    user_id=user.user_id,
                    display_name=user.display_name,
                    current_tier=user.current_tier_name,
                    recommended_tier=lower_tier.name,
                    recommendation_type="downgrade",
                    projected_monthly_usage=projected_monthly_usage,
                    projected_overage_cost=projected_overage_cost,
                    annual_savings=annual_savings,
                    current_monthly_cost=current_monthly_cost,
                    recommended_monthly_cost=recommended_monthly_cost,
                )

        # Add recommendations (a user can have both upgrade and downgrade)
        if upgrade_rec is not None:
            recommendations.append(upgrade_rec)
        if downgrade_rec is not None:
            recommendations.append(downgrade_rec)

    # Sort by annual_savings descending
    recommendations.sort(key=lambda r: r.annual_savings, reverse=True)

    # Build summary
    upgrade_count = sum(1 for r in recommendations if r.recommendation_type == "upgrade")
    downgrade_count = sum(1 for r in recommendations if r.recommendation_type == "downgrade")
    total_annual_savings = sum(
        (r.annual_savings for r in recommendations), Decimal("0")
    )

    summary = RecommendationSummary(
        total_recommendations=len(recommendations),
        total_projected_annual_savings=total_annual_savings,
        upgrade_count=upgrade_count,
        downgrade_count=downgrade_count,
    )

    return RecommendationResult(recommendations=recommendations, summary=summary)
