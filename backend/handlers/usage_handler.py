"""Handler for GET /api/usage — per-user usage aggregation via DynamoDB."""

import os
from datetime import date

import boto3

try:
    from repository.analytics_repository import AnalyticsRepository
except ImportError:
    from backend.repository.analytics_repository import AnalyticsRepository


def _lookup_user_names(user_ids: list[str], dynamodb_client=None) -> dict[str, tuple[str, str]]:
    """Batch lookup displayName/userName from UserNamesTable.

    Returns dict mapping userId → (displayName, userName).

    Kept for backward compatibility with callers that only need names.
    For new code that also needs the tombstone status, use
    :func:`_lookup_user_metadata`.
    """
    metadata = _lookup_user_metadata(user_ids, dynamodb_client=dynamodb_client)
    return {uid: (meta["displayName"], meta["userName"]) for uid, meta in metadata.items()}


def _lookup_user_metadata(user_ids: list[str], dynamodb_client=None) -> dict[str, dict]:
    """Batch lookup the full UserNamesTable row for a list of userIds.

    Returns dict mapping userId → ``{displayName, userName, status,
    tombstonedAt}``. A missing ``status`` field is reported as
    ``"ACTIVE"`` so callers can compare without a special case.

    The tombstone fields are sourced from the reconcile step (see
    ``etl/reconcile_users_handler.py`` and the ``user-tombstoning`` spec).
    """
    table_name = os.environ.get("USER_NAMES_TABLE", "")
    if not table_name or not user_ids:
        return {}

    client = dynamodb_client or boto3.client("dynamodb")
    result: dict[str, dict] = {}
    for uid in user_ids:
        try:
            resp = client.get_item(
                TableName=table_name,
                Key={"userId": {"S": uid}},
            )
            item = resp.get("Item", {})
            result[uid] = {
                "displayName": item.get("displayName", {}).get("S", ""),
                "userName": item.get("userName", {}).get("S", ""),
                "status": item.get("status", {}).get("S", "ACTIVE") or "ACTIVE",
                "tombstonedAt": item.get("tombstonedAt", {}).get("S") or None,
            }
        except Exception:
            result[uid] = {
                "displayName": "",
                "userName": "",
                "status": "ACTIVE",
                "tombstonedAt": None,
            }
    return result


def _compute_summary(users: list[dict]) -> dict:
    """Compute summary statistics from the list of user records."""
    total_users = len(users)
    total_credits = sum(u.get("totalCredits", 0) for u in users)
    total_overage = sum(u.get("overageCredits", 0) for u in users)
    avg_credits = round(total_credits / total_users, 2) if total_users > 0 else 0

    return {
        "totalUsers": total_users,
        "totalCredits": total_credits,
        "totalOverageCredits": total_overage,
        "averageCreditsPerUser": avg_credits,
    }


def _format_user(user: dict) -> dict:
    """Format a user aggregation dict to match the UsageResponse.UserUsage schema."""
    days_active = user.get("daysActive", 0)
    total_credits = user.get("totalCredits", 0)
    avg_daily = round(total_credits / days_active, 2) if days_active > 0 else 0.0

    return {
        "userId": user.get("userId", ""),
        "displayName": user.get("displayName", ""),
        "userName": user.get("userName", ""),
        "subscriptionTier": user.get("subscriptionTier", ""),
        "totalCredits": total_credits,
        "overageCredits": user.get("overageCredits", 0),
        "totalMessages": user.get("totalMessages", 0),
        "totalConversations": user.get("totalConversations", 0),
        "averageDailyCredits": avg_daily,
        "lastActiveDate": None,
        "daysSinceLastActive": None,
        "tombstoned": False,
    }


def _handle_single_user_usage(repo, user_id: str, query_params: dict) -> dict:
    """Return usage data scoped to a single user (for non-admin access).

    Queries only the user's partition to avoid full-table scan.
    """
    start_date = query_params.get("startDate")
    end_date = query_params.get("endDate")

    daily_stats = repo.get_user_daily_stats(user_id, start_date=start_date, end_date=end_date)

    if not daily_stats:
        return {
            "summary": {
                "totalUsers": 0,
                "totalCredits": 0,
                "totalOverageCredits": 0,
                "averageCreditsPerUser": 0,
            },
            "users": [],
            "period": {},
        }

    # Aggregate from daily stats
    total_credits = 0.0
    total_overage = 0.0
    total_messages = 0
    total_conversations = 0
    subscription_tier = ""

    for stat in daily_stats:
        total_credits += float(stat.get("totalCredits", 0))
        total_overage += float(stat.get("overageCredits", 0))
        total_messages += int(stat.get("totalMessages", 0))
        total_conversations += int(stat.get("totalConversations", 0))
        tier = stat.get("subscriptionTier", "")
        if tier:
            subscription_tier = tier

    user_data = {
        "userId": user_id,
        "totalCredits": round(total_credits, 2),
        "overageCredits": round(total_overage, 2),
        "totalMessages": total_messages,
        "totalConversations": total_conversations,
        "daysActive": len(daily_stats),
        "subscriptionTier": subscription_tier,
        "displayName": "",
        "userName": "",
    }

    users = [_format_user(user_data)]

    # Enrich with display name
    name_map = _lookup_user_names([user_id])
    if user_id in name_map:
        dn, un = name_map[user_id]
        if dn:
            users[0]["displayName"] = dn
        if un:
            users[0]["userName"] = un

    # Enrich with lastActiveDate
    activity_summaries = repo.batch_get_activity_summaries([user_id])
    summary_data = activity_summaries.get(user_id)
    if summary_data and summary_data.get("lastActiveDate"):
        last_active = summary_data["lastActiveDate"]
        users[0]["lastActiveDate"] = last_active
        users[0]["daysSinceLastActive"] = (date.today() - date.fromisoformat(last_active)).days

    period: dict = {}
    if start_date:
        period["startDate"] = start_date
    if end_date:
        period["endDate"] = end_date

    return {
        "summary": _compute_summary(users),
        "users": users,
        "period": period,
    }


def handle_usage(query_params: dict, dynamodb_resource=None) -> dict:
    """Handle GET /api/usage request.

    Args:
        query_params: Dict of query string parameters (startDate, endDate,
            subscriptionTier, limit, nextToken, userId).
            When userId is provided, returns only that user's aggregated stats
            (used for non-admin user-scoped access).
        dynamodb_resource: Optional boto3 DynamoDB resource for testing.

    Returns:
        Response dict with summary, users list, and period info.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")

    repo = AnalyticsRepository(table_name, dynamodb_resource=dynamodb_resource)

    # If userId is specified, return only that user's data (user-scoped access)
    scoped_user_id = query_params.get("userId")
    if scoped_user_id:
        return _handle_single_user_usage(repo, scoped_user_id, query_params)

    # Parse pagination params
    limit = min(int(query_params.get("limit", 50)), 50)
    next_token = query_params.get("nextToken")
    subscription_tier = query_params.get("subscriptionTier")

    result = repo.scan_user_stats(
        limit=limit,
        next_token=next_token,
        subscription_tier=subscription_tier,
    )

    users = [_format_user(u) for u in result.get("users", [])]

    # Enrich with displayName/userName + tombstone status from UserNamesTable
    user_ids = [u["userId"] for u in users if u["userId"]]
    metadata_map = _lookup_user_metadata(user_ids)
    for u in users:
        uid = u["userId"]
        meta = metadata_map.get(uid)
        if meta:
            if meta["displayName"]:
                u["displayName"] = meta["displayName"]
            if meta["userName"]:
                u["userName"] = meta["userName"]
            u["tombstoned"] = meta["status"] == "TOMBSTONED"
        else:
            u["tombstoned"] = False

    # Enrich with lastActiveDate and daysSinceLastActive from Activity_Summary
    if user_ids:
        activity_summaries = repo.batch_get_activity_summaries(user_ids)
        today = date.today()
        for u in users:
            uid = u["userId"]
            summary = activity_summaries.get(uid)
            if summary and summary.get("lastActiveDate"):
                last_active = summary["lastActiveDate"]
                u["lastActiveDate"] = last_active
                u["daysSinceLastActive"] = (today - date.fromisoformat(last_active)).days
            # else: fields remain None (set in _format_user)

    summary = _compute_summary(users)

    period: dict = {}
    if query_params.get("startDate"):
        period["startDate"] = query_params["startDate"]
    if query_params.get("endDate"):
        period["endDate"] = query_params["endDate"]

    response: dict = {
        "summary": summary,
        "users": users,
        "period": period,
    }

    if result.get("nextToken"):
        response["nextToken"] = result["nextToken"]

    return response
