"""Shared utility for resolving user display names from UserNamesTable.

Used by backend handlers that need to enrich responses with human-readable
names stored in DynamoDB (populated by the ETL pipeline via IAM Identity Center).
"""

from __future__ import annotations

import os

import boto3


def lookup_user_name(user_id: str, dynamodb_client=None) -> tuple[str, str]:
    """Look up displayName and userName for a single user from UserNamesTable.

    Args:
        user_id: The Kiro userId to look up.
        dynamodb_client: Optional boto3 DynamoDB client for testing.

    Returns:
        (displayName, userName) tuple. Falls back to ("", "") on any error
        or when the table is not configured.
    """
    table_name = os.environ.get("USER_NAMES_TABLE", "")
    if not table_name:
        return ("", "")

    client = dynamodb_client or boto3.client("dynamodb")
    try:
        response = client.get_item(
            TableName=table_name,
            Key={"userId": {"S": user_id}},
        )
        item = response.get("Item", {})
        display_name = item.get("displayName", {}).get("S", "")
        user_name = item.get("userName", {}).get("S", "")
        return (display_name, user_name)
    except Exception:
        return ("", "")
