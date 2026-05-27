"""Handler for tier optimization recommendation API endpoints.

Provides GET /api/recommendations/tier-optimization, GET /api/config/tier-pricing,
and PUT /api/config/tier-pricing. Reads pricing configuration from SSM Parameter
Store, scans user stats from DynamoDB, and delegates computation to the pure
recommendation engine.
"""

import json
import logging
import os
from datetime import date
from decimal import Decimal

import boto3

try:
    from handlers.recommendation_engine import (
        InactiveSubscriberInput,
        UserUsageData,
        compute_inactive_subscribers,
        compute_recommendations,
        parse_pricing_config,
        validate_pricing_config,
    )
    from repository.analytics_repository import AnalyticsRepository
except ImportError:
    from backend.handlers.recommendation_engine import (
        InactiveSubscriberInput,
        UserUsageData,
        compute_inactive_subscribers,
        compute_recommendations,
        parse_pricing_config,
        validate_pricing_config,
    )
    from backend.repository.analytics_repository import AnalyticsRepository

logger = logging.getLogger(__name__)

SSM_PARAM_PATH = "/kiro-cost-analyzer/tier-pricing"


def _get_ssm_client(ssm_client=None):
    """Return the provided client or create a new SSM client."""
    return ssm_client or boto3.client("ssm")


def _read_pricing_config(ssm_client=None) -> dict | None:
    """Read pricing config from SSM Parameter Store.

    Args:
        ssm_client: Optional pre-configured SSM client for testing.

    Returns:
        Parsed config dict, or None if the parameter does not exist.

    Raises:
        ValueError: If the parameter contains invalid JSON.
    """
    ssm = _get_ssm_client(ssm_client)
    param_name = os.environ.get("SSM_TIER_PRICING", SSM_PARAM_PATH)

    try:
        resp = ssm.get_parameter(Name=param_name)
        raw_value = resp["Parameter"]["Value"]
        return json.loads(raw_value)
    except ssm.exceptions.ParameterNotFound:
        return None
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in tier pricing SSM parameter", extra={"error": str(exc)})
        raise ValueError("Pricing configuration is corrupted. Please reconfigure.") from exc


def _serialize_decimal(obj):
    """Convert Decimal values to float for JSON serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _serialize_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_decimal(item) for item in obj]
    return obj


def handle_get_recommendations(query_params: dict, dynamodb_resource=None, ssm_client=None) -> dict:
    """Handle GET /api/recommendations/tier-optimization.

    Reads pricing config from SSM, scans user stats from DynamoDB for the
    current month, builds UserUsageData list, calls compute_recommendations(),
    and serializes the result for JSON response.

    Args:
        query_params: Dict with optional query parameters.
        dynamodb_resource: Optional boto3 DynamoDB resource for testing.
        ssm_client: Optional boto3 SSM client for testing.

    Returns:
        Response dict with recommendations and summary, or error dict.
    """
    # Read pricing config from SSM
    try:
        config_dict = _read_pricing_config(ssm_client)
    except ValueError:
        return {
            "_status_code": 500,
            "error": "InternalError",
            "message": "Pricing configuration is corrupted. Please reconfigure.",
        }

    if config_dict is None:
        return {
            "_status_code": 400,
            "error": "PricingNotConfigured",
            "message": "Tier pricing configuration is required. Configure it in Settings.",
        }

    # Parse pricing config
    try:
        pricing = parse_pricing_config(config_dict)
    except ValueError as exc:
        logger.error("Invalid pricing config in SSM", extra={"error": str(exc)})
        return {
            "_status_code": 500,
            "error": "InternalError",
            "message": "Pricing configuration is corrupted. Please reconfigure.",
        }

    # Compute date boundaries from query params (default: last 30 days)
    today = date.today()
    start_date = query_params.get("startDate")
    end_date = query_params.get("endDate")

    if not start_date:
        from datetime import timedelta
        start_date = (today - timedelta(days=30)).isoformat()
    if not end_date:
        end_date = today.isoformat()

    # Days elapsed between start and end (inclusive)
    start_dt = date.fromisoformat(start_date)
    end_dt = date.fromisoformat(end_date)
    days_elapsed = (end_dt - start_dt).days + 1

    # Scan user stats from DynamoDB
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = AnalyticsRepository(table_name, dynamodb_resource=dynamodb_resource)
    result = repo.scan_user_stats(limit=10000, start_date=start_date, end_date=end_date)

    # Build UserUsageData list
    users_data = result.get("users", [])

    # Enrich with displayName/userName + tombstone status from UserNamesTable.
    # Tombstoned users are filtered out below — they no longer exist in
    # Identity Center and recommendations against them would be inactionable.
    user_names_table = os.environ.get("USER_NAMES_TABLE", "")
    metadata_map: dict[str, dict] = {}
    if user_names_table:
        dynamodb_client = boto3.client("dynamodb")
        for u in users_data:
            uid = u.get("userId", "")
            if uid:
                try:
                    resp = dynamodb_client.get_item(
                        TableName=user_names_table,
                        Key={"userId": {"S": uid}},
                    )
                    item = resp.get("Item", {})
                    metadata_map[uid] = {
                        "displayName": item.get("displayName", {}).get("S", ""),
                        "userName": item.get("userName", {}).get("S", ""),
                        "status": item.get("status", {}).get("S", "ACTIVE") or "ACTIVE",
                    }
                except Exception:
                    pass

    def _is_tombstoned(user_id: str) -> bool:
        """Read-side default: missing status is treated as ACTIVE so rows
        written before this feature are not accidentally hidden."""
        return metadata_map.get(user_id, {}).get("status", "ACTIVE") == "TOMBSTONED"

    users: list[UserUsageData] = []
    for u in users_data:
        user_id = u.get("userId", "")
        if _is_tombstoned(user_id):
            continue
        # Resolve display name: UserNamesTable > DynamoDB stat > userId
        meta = metadata_map.get(user_id, {})
        dn = meta.get("displayName", "")
        un = meta.get("userName", "")
        display_name = dn or un or u.get("displayName") or u.get("userName") or user_id
        current_tier = u.get("subscriptionTier", "")
        total_credits = Decimal(str(u.get("totalCredits", 0)))
        # ``daysActive`` is incremented by ``scan_user_stats`` once per
        # STATS#DAILY# row aggregated for the user. A row only exists for
        # days where the user generated at least one event, so this is the
        # active-day signal the engine needs.
        days_active = int(u.get("daysActive", 0))

        # Treat users with a non-empty subscriptionTier as overage_enabled
        overage_enabled = bool(current_tier)

        users.append(
            UserUsageData(
                user_id=user_id,
                display_name=display_name,
                current_tier_name=current_tier,
                total_credits_current_month=total_credits,
                days_elapsed=days_elapsed,
                days_active=days_active,
                overage_enabled=overage_enabled,
            )
        )

    # Compute recommendations
    recommendation_result = compute_recommendations(users, pricing)

    # ── Inactive subscribers (paid users with no recent activity) ───────────
    # Independent of the date picker: the question "is this user paying for
    # an idle seat?" is a lifetime question, not a window question. We run
    # a second, unwindowed ``scan_user_stats`` to enumerate every user with
    # a tier (the windowed call above only returns users active inside the
    # date range, so dormant users would otherwise be invisible). The two
    # scans are merged — windowed for projection, lifetime for tier
    # presence — and ``Activity_Summary`` provides the freshest
    # ``lastActiveDate``.
    lifetime_result = repo.scan_user_stats(limit=10000)
    activity_summaries = repo.scan_activity_summaries()

    # Extend the metadata cache with users seen only in the lifetime scan so
    # we can filter tombstones consistently across both views.
    if user_names_table:
        dynamodb_client = boto3.client("dynamodb")
        for u in lifetime_result.get("users", []):
            uid = u.get("userId", "")
            if uid and uid not in metadata_map:
                try:
                    resp = dynamodb_client.get_item(
                        TableName=user_names_table,
                        Key={"userId": {"S": uid}},
                    )
                    item = resp.get("Item", {})
                    metadata_map[uid] = {
                        "displayName": item.get("displayName", {}).get("S", ""),
                        "userName": item.get("userName", {}).get("S", ""),
                        "status": item.get("status", {}).get("S", "ACTIVE") or "ACTIVE",
                    }
                except Exception:
                    pass

    inactive_inputs: list[InactiveSubscriberInput] = []
    for u in lifetime_result.get("users", []):
        user_id = u.get("userId", "")
        current_tier = u.get("subscriptionTier", "")
        if not current_tier:
            continue
        if _is_tombstoned(user_id):
            continue

        meta = metadata_map.get(user_id, {})
        dn = meta.get("displayName", "")
        un = meta.get("userName", "")
        display_name = dn or un or u.get("displayName") or u.get("userName") or user_id

        summary = activity_summaries.get(user_id, {})
        last_active = summary.get("lastActiveDate") if summary else None
        inactive_inputs.append(
            InactiveSubscriberInput(
                user_id=user_id,
                display_name=display_name,
                current_tier_name=current_tier,
                last_active_date=last_active,
            )
        )

    inactive_subscribers = compute_inactive_subscribers(
        inactive_inputs, pricing, today=today.isoformat()
    )

    # Serialize to JSON-safe format
    recommendations = [
        {
            "userId": r.user_id,
            "displayName": r.display_name,
            "currentTier": r.current_tier,
            "recommendedTier": r.recommended_tier,
            "recommendationType": r.recommendation_type,
            "projectedMonthlyUsage": float(r.projected_monthly_usage),
            "projectedOverageCost": float(r.projected_overage_cost),
            "annualSavings": float(r.annual_savings),
            "currentMonthlyCost": float(r.current_monthly_cost),
            "recommendedMonthlyCost": float(r.recommended_monthly_cost),
        }
        for r in recommendation_result.recommendations
    ]

    summary = {
        "totalRecommendations": recommendation_result.summary.total_recommendations,
        "totalProjectedAnnualSavings": float(
            recommendation_result.summary.total_projected_annual_savings
        ),
        "upgradeCount": recommendation_result.summary.upgrade_count,
        "downgradeCount": recommendation_result.summary.downgrade_count,
    }

    # Expose the analysis window so the frontend can show
    # "Based on usage from X to Y (N days)".
    period = {
        "startDate": start_date,
        "endDate": end_date,
        "daysWindow": days_elapsed,
    }

    inactive_subscribers_payload = [
        {
            "userId": s.user_id,
            "displayName": s.display_name,
            "currentTier": s.current_tier,
            "currentMonthlyCost": float(s.current_monthly_cost),
            "daysInactive": s.days_inactive,
            "lastActiveDate": s.last_active_date,
            "annualWastedCost": float(s.annual_wasted_cost),
        }
        for s in inactive_subscribers
    ]
    inactive_summary = {
        "totalInactive": len(inactive_subscribers),
        "totalAnnualWastedCost": float(
            sum((s.annual_wasted_cost for s in inactive_subscribers), Decimal("0"))
        ),
        "thresholdDays": 30,
    }

    return {
        "recommendations": recommendations,
        "summary": summary,
        "period": period,
        "inactiveSubscribers": inactive_subscribers_payload,
        "inactiveSummary": inactive_summary,
    }


def handle_get_tier_pricing(ssm_client=None) -> dict:
    """Handle GET /api/config/tier-pricing.

    Reads the current pricing configuration from SSM Parameter Store.

    Args:
        ssm_client: Optional pre-configured SSM client for testing.

    Returns:
        Dict with the current pricing config and status, or not_configured status.
    """
    try:
        config_dict = _read_pricing_config(ssm_client)
    except ValueError:
        return {
            "_status_code": 500,
            "error": "InternalError",
            "message": "Pricing configuration is corrupted. Please reconfigure.",
        }

    if config_dict is None:
        return {
            "config": None,
            "status": "not_configured",
            "message": "Tier pricing has not been configured yet.",
        }

    return {
        "config": config_dict,
        "status": "valid",
    }


def handle_put_tier_pricing(body: dict, ssm_client=None) -> dict:
    """Handle PUT /api/config/tier-pricing.

    Validates the provided pricing configuration and writes to SSM on success.

    Args:
        body: Request body with pricing configuration.
        ssm_client: Optional pre-configured SSM client for testing.

    Returns:
        Dict with status and message indicating success or validation error.
    """
    is_valid, error_message = validate_pricing_config(body)

    if not is_valid:
        return {
            "_status_code": 400,
            "status": "error",
            "message": error_message,
        }

    ssm = _get_ssm_client(ssm_client)
    param_name = os.environ.get("SSM_TIER_PRICING", SSM_PARAM_PATH)

    ssm.put_parameter(
        Name=param_name,
        Value=json.dumps(body),
        Type="String",
        Overwrite=True,
    )

    return {
        "status": "valid",
        "message": "Tier pricing configuration updated successfully.",
    }
