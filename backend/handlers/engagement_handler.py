"""Handler for engagement segmentation API endpoints.

Provides GET /api/usage/engagement, GET /api/config/engagement-thresholds,
and PUT /api/config/engagement-thresholds. Reads aggregated user activity
from Amazon DynamoDB, classifies users via the segmentation engine, computes funnel
stages and derived metrics, and manages threshold configuration in AWS Systems Manager Parameter Store.
"""

import json
import logging
import os
from datetime import date

import boto3

try:
    from handlers.segmentation_engine import (
        Thresholds,
        UserActivity,
        classify_users,
        parse_thresholds,
        reclassify_dormant,
        validate_thresholds,
    )
    from handlers.funnel_calculator import compute_funnel, compute_derived_metrics
    from repository.analytics_repository import AnalyticsRepository
except ImportError:
    from backend.handlers.segmentation_engine import (
        Thresholds,
        UserActivity,
        classify_users,
        parse_thresholds,
        reclassify_dormant,
        validate_thresholds,
    )
    from backend.handlers.funnel_calculator import compute_funnel, compute_derived_metrics
    from backend.repository.analytics_repository import AnalyticsRepository

logger = logging.getLogger(__name__)

SSM_PARAM_PATH = "/kiro-cost-analyzer/engagement-thresholds"


def _get_ssm_client(ssm_client=None):
    """Return the provided client or create a new SSM client."""
    return ssm_client or boto3.client("ssm")


def _read_thresholds(ssm_client=None) -> Thresholds:
    """Read thresholds from SSM Parameter Store, falling back to defaults.

    Args:
        ssm_client: Optional pre-configured SSM client for testing.

    Returns:
        Thresholds instance (defaults if parameter is missing or invalid).
    """
    ssm = _get_ssm_client(ssm_client)
    param_name = os.environ.get("SSM_ENGAGEMENT_THRESHOLDS", SSM_PARAM_PATH)

    try:
        resp = ssm.get_parameter(Name=param_name)
        raw_value = resp["Parameter"]["Value"]
        return parse_thresholds(raw_value)
    except Exception:
        logger.warning("Could not read engagement thresholds from SSM, using defaults")
        return Thresholds()


def handle_engagement(query_params: dict, dynamodb_resource=None, ssm_client=None) -> dict:
    """Handle GET /api/usage/engagement request.

    Reads thresholds from SSM (fallback to defaults), scans user stats from
    DynamoDB, classifies users, computes funnel stages and derived metrics.

    Args:
        query_params: Dict with optional startDate, endDate.
        dynamodb_resource: Optional boto3 DynamoDB resource for testing.
        ssm_client: Optional boto3 SSM client for testing.

    Returns:
        Response dict with segmentation, funnel, derivedMetrics, and period.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")

    # Read thresholds
    thresholds = _read_thresholds(ssm_client)

    # Get aggregated user stats from DynamoDB
    repo = AnalyticsRepository(table_name, dynamodb_resource=dynamodb_resource)
    start_date = query_params.get("startDate")
    end_date = query_params.get("endDate")
    result = repo.scan_user_stats(limit=10000, start_date=start_date, end_date=end_date)

    # Build UserActivity list from aggregated stats
    users_data = result.get("users", [])
    activities = [
        UserActivity(
            user_id=u["userId"],
            total_messages=u.get("totalMessages", 0),
            total_conversations=u.get("totalConversations", 0),
            days_active=u.get("daysActive", 0),
        )
        for u in users_data
    ]

    # Classify users
    classifications = classify_users(activities, thresholds)

    # Fetch ALL Activity_Summary items to include users absent from the period
    # Users with Activity_Summary but no activity in the selected period are "idle"
    all_summaries = repo.scan_activity_summaries()

    # Add absent users as idle (they have an Activity_Summary but no stats in the period)
    active_user_ids = set(a.user_id for a in activities)
    for uid, summary in all_summaries.items():
        if uid not in active_user_ids:
            # User exists but had no activity in the selected period → idle
            activities.append(UserActivity(
                user_id=uid,
                total_messages=0,
                total_conversations=0,
                days_active=0,
            ))
            classifications[uid] = "idle"

    # Compute daysSinceLastActive for all users
    user_ids = [a.user_id for a in activities]

    today = date.today()
    frequency_data: dict[str, int | None] = {}
    for uid in user_ids:
        summary = all_summaries.get(uid)
        if summary and summary.get("lastActiveDate"):
            last_active = date.fromisoformat(summary["lastActiveDate"])
            frequency_data[uid] = (today - last_active).days
        else:
            frequency_data[uid] = None

    # Reclassify idle users as dormant based on frequency data
    classifications = reclassify_dormant(
        classifications, frequency_data, thresholds.dormant_days_threshold
    )

    # Compute funnel
    funnel_stages = compute_funnel(activities, classifications)

    # Compute derived metrics
    derived_metrics = compute_derived_metrics(len(activities), classifications)

    # Build segmentation distribution
    category_counts: dict[str, int] = {"power": 0, "active": 0, "light": 0, "idle": 0, "dormant": 0}
    for category in classifications.values():
        category_counts[category] += 1

    total_users = len(activities)
    segmentation = []
    for cat in ("power", "active", "light", "idle", "dormant"):
        count = category_counts[cat]
        percentage = round((count / total_users) * 100, 1) if total_users > 0 else 0.0
        segmentation.append({
            "category": cat,
            "count": count,
            "percentage": percentage,
        })

    # Build funnel response
    funnel = [
        {
            "name": stage.name,
            "count": stage.count,
            "conversionRate": stage.conversion_rate,
        }
        for stage in funnel_stages
    ]

    # Build period
    period: dict = {}
    if query_params.get("startDate"):
        period["startDate"] = query_params["startDate"]
    if query_params.get("endDate"):
        period["endDate"] = query_params["endDate"]

    return {
        "segmentation": segmentation,
        "funnel": funnel,
        "derivedMetrics": derived_metrics,
        "period": period,
    }


def handle_get_thresholds(ssm_client=None) -> dict:
    """Handle GET /api/config/engagement-thresholds request.

    Reads the current threshold configuration from SSM Parameter Store.

    Args:
        ssm_client: Optional pre-configured SSM client for testing.

    Returns:
        Dict with the current threshold configuration and status.
    """
    ssm = _get_ssm_client(ssm_client)
    param_name = os.environ.get("SSM_ENGAGEMENT_THRESHOLDS", SSM_PARAM_PATH)

    try:
        resp = ssm.get_parameter(Name=param_name)
        raw_value = resp["Parameter"]["Value"]
        config = json.loads(raw_value)
        return {
            "thresholds": config,
            "status": "valid",
            "message": "Current engagement thresholds",
        }
    except Exception:
        # Return defaults when parameter doesn't exist
        default_config = {
            "power": {"messages": Thresholds.power_messages, "daysActive": Thresholds.power_days_active},
            "active": {"messages": Thresholds.active_messages, "daysActive": Thresholds.active_days_active},
            "dormantDaysThreshold": Thresholds.dormant_days_threshold,
        }
        return {
            "thresholds": default_config,
            "status": "defaults",
            "message": "Using default thresholds (no custom configuration found)",
        }


def handle_put_thresholds(body: dict, ssm_client=None) -> dict:
    """Handle PUT /api/config/engagement-thresholds request.

    Validates the provided threshold configuration and writes to SSM on success.

    Args:
        body: Request body with threshold configuration.
        ssm_client: Optional pre-configured SSM client for testing.

    Returns:
        Dict with status and message indicating success or validation error.
    """
    is_valid, error_message = validate_thresholds(body)

    if not is_valid:
        return {
            "status": "error",
            "message": error_message,
        }

    ssm = _get_ssm_client(ssm_client)
    param_name = os.environ.get("SSM_ENGAGEMENT_THRESHOLDS", SSM_PARAM_PATH)

    ssm.put_parameter(
        Name=param_name,
        Value=json.dumps(body),
        Type="String",
        Overwrite=True,
    )

    return {
        "thresholds": body,
        "status": "valid",
        "message": "Engagement thresholds updated successfully",
    }
