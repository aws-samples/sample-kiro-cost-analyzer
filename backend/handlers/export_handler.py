"""Handler for GET /api/usage/export — export usage data as CSV or JSON."""

import csv
import io
import json

from handlers.usage_handler import handle_usage

CSV_COLUMNS = [
    "UserId",
    "SubscriptionTier",
    "TotalCredits",
    "OverageCredits",
    "TotalMessages",
    "TotalConversations",
    "AverageDailyCredits",
]

_USER_KEY_TO_CSV = {
    "userId": "UserId",
    "subscriptionTier": "SubscriptionTier",
    "totalCredits": "TotalCredits",
    "overageCredits": "OverageCredits",
    "totalMessages": "TotalMessages",
    "totalConversations": "TotalConversations",
    "averageDailyCredits": "AverageDailyCredits",
}


def _serialize_csv(users: list[dict]) -> str:
    """Serialize a list of user dicts to CSV with header row."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for user in users:
        row = {_USER_KEY_TO_CSV[k]: v for k, v in user.items() if k in _USER_KEY_TO_CSV}
        writer.writerow(row)
    return output.getvalue()


def _serialize_json(users: list[dict]) -> str:
    """Serialize a list of user dicts to JSON."""
    return json.dumps(users)


def handle_export(query_params: dict, dynamodb_resource=None) -> dict:
    """Handle GET /api/usage/export request.

    Reuses handle_usage to fetch data, then serializes to CSV or JSON
    based on the ``format`` query parameter.

    Args:
        query_params: Dict of query string parameters. Supports all
            parameters from /api/usage plus ``format`` (csv|json, default json).
        dynamodb_resource: Optional boto3 DynamoDB resource for testing.

    Returns:
        Dict with ``statusCode``, ``body`` (serialized data), and
        ``contentType`` (text/csv or application/json).
    """
    export_format = query_params.get("format", "json").lower()

    usage_params = {k: v for k, v in query_params.items() if k != "format"}
    usage_result = handle_usage(usage_params, dynamodb_resource=dynamodb_resource)
    users = usage_result.get("users", [])

    if export_format == "csv":
        body = _serialize_csv(users)
        content_type = "text/csv"
    else:
        body = _serialize_json(users)
        content_type = "application/json"

    return {
        "statusCode": 200,
        "body": body,
        "contentType": content_type,
    }
