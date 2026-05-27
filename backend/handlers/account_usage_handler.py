"""Handler for GET /api/usage/account — account-level usage aggregation via DynamoDB."""

import os
from collections import defaultdict
from datetime import datetime

from repository.analytics_repository import AnalyticsRepository

_VALID_GRANULARITIES = ("day", "week", "month")


def _parse_date(value: str) -> datetime | None:
    """Parse a YYYY-MM-DD date string, returning None if invalid."""
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _compute_totals(daily_items: list[dict]) -> dict:
    """Sum all daily global items into account-level totals."""
    total_credits = 0.0
    total_overage = 0.0
    total_messages = 0
    total_conversations = 0

    for item in daily_items:
        total_credits += float(item.get("totalCredits", 0))
        total_overage += float(item.get("overageCredits", 0))
        total_messages += int(item.get("totalMessages", 0))
        total_conversations += int(item.get("totalConversations", 0))

    return {
        "totalCredits": round(total_credits, 2),
        "totalOverageCredits": round(total_overage, 2),
        "totalMessages": total_messages,
        "totalConversations": total_conversations,
    }


def _extract_date_from_sk(sk: str) -> str:
    """Extract the date portion from a STATS#DAILY#YYYY-MM-DD sort key."""
    prefix = "STATS#DAILY#"
    return sk[len(prefix):] if sk.startswith(prefix) else sk


def _group_key_for_date(date_str: str, granularity: str) -> str:
    """Return the grouping key for a date string given the granularity.

    - day: date as-is (YYYY-MM-DD)
    - week: Monday of the ISO week (YYYY-MM-DD)
    - month: first day of the month (YYYY-MM-01)
    """
    if granularity == "month":
        return date_str[:7] + "-01"

    if granularity == "week":
        dt = _parse_date(date_str)
        if dt:
            monday = dt - __import__("datetime").timedelta(days=dt.weekday())
            return monday.strftime("%Y-%m-%d")
        return date_str

    # day — return as-is
    return date_str


def _aggregate_breakdown(items: list[dict], sk_prefix: str, start_date: str | None, end_date: str | None, name_key: str = "name") -> list[dict]:
    """Aggregate breakdown items (STATS#TIER# or STATS#CLIENT#) by category.

    SK format: {sk_prefix}{category}#{date}
    Returns list of dicts with name, totalCredits, totalOverageCredits, percentage.
    """
    category_totals: dict[str, dict] = {}

    for item in items:
        sk = item.get("SK", "")
        # Extract category and date from SK
        remainder = sk.removeprefix(sk_prefix)
        parts = remainder.rsplit("#", 1)
        if len(parts) != 2:
            continue
        category, date_str = parts

        # Filter by date range if provided
        if start_date and date_str < start_date:
            continue
        if end_date and date_str > end_date:
            continue

        if category not in category_totals:
            category_totals[category] = {
                "totalCredits": 0.0,
                "totalOverageCredits": 0.0,
            }

        entry = category_totals[category]
        entry["totalCredits"] += float(item.get("totalCredits", 0))
        entry["totalOverageCredits"] += float(item.get("overageCredits", 0))

    # Compute percentages
    grand_total = sum(e["totalCredits"] for e in category_totals.values())
    result = []
    for name, totals in sorted(category_totals.items(), key=lambda x: x[1]["totalCredits"], reverse=True):
        pct = round(totals["totalCredits"] / grand_total * 100, 1) if grand_total > 0 else 0.0
        result.append({
            name_key: name,
            "totalCredits": round(totals["totalCredits"], 2),
            "totalOverageCredits": round(totals["totalOverageCredits"], 2),
            "percentage": pct,
        })

    return result


def _build_timeline(daily_items: list[dict], granularity: str) -> list[dict]:
    """Group daily items by the requested granularity and build timeline entries."""
    groups: dict[str, dict] = defaultdict(lambda: {
        "totalCredits": 0.0,
        "totalOverageCredits": 0.0,
        "totalMessages": 0,
        "totalConversations": 0,
    })

    for item in daily_items:
        date_str = _extract_date_from_sk(item.get("SK", ""))
        key = _group_key_for_date(date_str, granularity)

        bucket = groups[key]
        bucket["totalCredits"] += float(item.get("totalCredits", 0))
        bucket["totalOverageCredits"] += float(item.get("overageCredits", 0))
        bucket["totalMessages"] += int(item.get("totalMessages", 0))
        bucket["totalConversations"] += int(item.get("totalConversations", 0))

    timeline = []
    for period_key in sorted(groups.keys()):
        entry = groups[period_key]
        timeline.append({
            "period": period_key,
            "totalCredits": round(entry["totalCredits"], 2),
            "totalOverageCredits": round(entry["totalOverageCredits"], 2),
            "totalMessages": entry["totalMessages"],
            "totalConversations": entry["totalConversations"],
        })

    return timeline


def handle_account_usage(query_params: dict, dynamodb_resource=None) -> dict:
    """Handle GET /api/usage/account request.

    Args:
        query_params: Dict of query string parameters (startDate, endDate, granularity).
        dynamodb_resource: Optional boto3 DynamoDB resource for testing.

    Returns:
        Response dict with totals, timeline, breakdownByTier, breakdownByClientType, and period.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = AnalyticsRepository(table_name, dynamodb_resource=dynamodb_resource)

    granularity = query_params.get("granularity", "day")
    if granularity not in _VALID_GRANULARITIES:
        granularity = "day"

    start_date = query_params.get("startDate")
    end_date = query_params.get("endDate")

    # Validate dates
    if start_date and not _parse_date(start_date):
        start_date = None
    if end_date and not _parse_date(end_date):
        end_date = None

    daily_items = repo.get_global_daily_stats(
        start_date=start_date,
        end_date=end_date,
    )

    totals = _compute_totals(daily_items)
    timeline = _build_timeline(daily_items, granularity)

    # Breakdown by tier
    tier_items = repo.get_global_tier_breakdown(start_date=start_date, end_date=end_date)
    breakdown_by_tier = _aggregate_breakdown(tier_items, "STATS#TIER#", start_date, end_date, "subscriptionTier")

    # Breakdown by client type
    client_items = repo.get_global_client_type_breakdown(start_date=start_date, end_date=end_date)
    breakdown_by_client_type = _aggregate_breakdown(client_items, "STATS#CLIENT#", start_date, end_date, "clientType")

    period: dict = {"granularity": granularity}
    if start_date:
        period["startDate"] = start_date
    if end_date:
        period["endDate"] = end_date

    return {
        "totals": totals,
        "timeline": timeline,
        "breakdownByTier": breakdown_by_tier,
        "breakdownByClientType": breakdown_by_client_type,
        "period": period,
    }
