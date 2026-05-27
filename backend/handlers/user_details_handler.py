"""Handler for GET /api/usage/{userId}/details — user detail via DynamoDB."""

import os

from repository.analytics_repository import AnalyticsRepository
from shared.user_name_resolver import lookup_user_name


def _compute_distributions(items, key_field, raw_field):
    """Compute distribution with percentages from DynamoDB items.

    Each item is expected to have ``count`` and *raw_field* attributes.
    Returns a list of dicts with the key field, count, and percentage.
    """
    total = sum(int(item.get("count", 0)) for item in items)
    result = []
    for item in items:
        count = int(item.get("count", 0))
        pct = round(count / total * 100, 1) if total > 0 else 0.0
        result.append({
            key_field: item.get(raw_field, ""),
            "count": count,
            "percentage": pct,
        })
    return result


def handle_user_details(
    user_id: str,
    query_params: dict,
    dynamodb_resource=None,
    dynamodb_client=None,
) -> dict:
    """Handle GET /api/usage/{userId}/details request.

    Queries DynamoDB via AnalyticsRepository to build a detailed user profile
    combining daily stats, model/trigger distributions, and recent prompts.

    Args:
        user_id: The userId to look up.
        query_params: Dict with optional startDate and endDate.
        dynamodb_resource: Optional boto3 DynamoDB resource for testing.
        dynamodb_client: Optional boto3 DynamoDB client for testing (user name lookup).

    Returns:
        Response dict with user details, or error dict with _status_code for 404.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = AnalyticsRepository(table_name, dynamodb_resource=dynamodb_resource)

    start_date = query_params.get("startDate")
    end_date = query_params.get("endDate")

    # 1. Daily stats
    daily_stats = repo.get_user_daily_stats(user_id, start_date=start_date, end_date=end_date)

    # 2. Model distribution
    model_items = repo.get_user_model_distribution(user_id)

    # 3. Trigger distribution
    trigger_items = repo.get_user_trigger_distribution(user_id)

    # 3b. Category distribution
    category_items = repo.get_user_category_distribution(user_id)

    # 4. Recent prompts (newest first, limit 20)
    prompts_result = repo.get_user_prompts(
        user_id,
        limit=20,
        start_date=start_date,
        end_date=end_date,
        scan_forward=False,
    )
    prompt_items = prompts_result.get("items", [])

    # If no data at all, return 404
    if not daily_stats and not prompt_items:
        error = {
            "error": "NotFound",
            "message": f"No data found for userId '{user_id}'",
        }
        error["_status_code"] = 404
        return error

    # Look up displayName/userName from UserNamesTable
    display_name, user_name = lookup_user_name(user_id, dynamodb_client=dynamodb_client)

    # Build daily usage from STATS#DAILY# items
    daily_usage = []
    total_credits = 0.0
    total_overage = 0.0
    total_messages = 0
    total_interactions = 0

    for stat in daily_stats:
        sk = stat.get("SK", "")
        date = sk.replace("STATS#DAILY#", "") if sk.startswith("STATS#DAILY#") else ""
        credits = float(stat.get("totalCredits", 0))
        messages = int(stat.get("totalMessages", 0))
        interactions = int(stat.get("totalInteractions", 0))
        overage = float(stat.get("overageCredits", 0))
        cpi = round(credits / interactions, 2) if interactions > 0 else None

        daily_usage.append({
            "date": date,
            "credits": round(credits, 2),
            "interactions": interactions,
            "costPerInteraction": cpi,
            "messages": messages,
            "overageCredits": round(overage, 2),
        })

        total_credits += credits
        total_overage += overage
        total_messages += messages
        total_interactions += interactions

    daily_usage.sort(key=lambda x: x["date"])

    avg_cost = round(total_credits / total_interactions, 2) if total_interactions > 0 else 0.0

    # Resolve subscription tier from the most recent daily stat that has one
    subscription_tier = ""
    latest_tier_date = ""
    for stat in daily_stats:
        tier = stat.get("subscriptionTier", "")
        if tier:
            sk = stat.get("SK", "")
            stat_date = sk.replace("STATS#DAILY#", "") if sk.startswith("STATS#DAILY#") else ""
            if stat_date >= latest_tier_date:
                subscription_tier = tier
                latest_tier_date = stat_date

    # Build distributions
    model_distribution = _compute_distributions(model_items, "modelId", "rawModelId")
    trigger_distribution = _compute_distributions(trigger_items, "triggerType", "rawTriggerType")
    category_distribution = _compute_distributions(category_items, "category", "rawCategory")

    # Build recent prompts
    recent_prompts = []
    for item in prompt_items:
        recent_prompts.append({
            "timestamp": item.get("timestamp", ""),
            "modelId": item.get("modelId", ""),
            "triggerType": item.get("triggerType", ""),
            "promptLength": int(item.get("promptLength", 0)),
            "responseLength": int(item.get("responseLength", 0)),
            "requestId": item.get("requestId", ""),
            "category": item.get("category", ""),
        })

    # Build period
    period = {}
    if start_date:
        period["startDate"] = start_date
    if end_date:
        period["endDate"] = end_date

    return {
        "userId": user_id,
        "displayName": display_name,
        "userName": user_name,
        "subscriptionTier": subscription_tier,
        "summary": {
            "totalCredits": round(total_credits, 2),
            "totalOverageCredits": round(total_overage, 2),
            "totalInteractions": total_interactions,
            "averageCostPerInteraction": avg_cost,
            "totalMessages": total_messages,
        },
        "dailyUsage": daily_usage,
        "modelDistribution": model_distribution,
        "triggerDistribution": trigger_distribution,
        "categoryDistribution": category_distribution,
        "recentPrompts": recent_prompts,
        "period": period,
    }
