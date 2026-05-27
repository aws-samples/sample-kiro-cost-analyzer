"""Kiro Data Tool — Strands @tool for fetching Kiro usage data.

Queries the DynamoDB Analytics_Table directly via boto3 (no dependency
on the backend repository layer). Uses a factory pattern:
`build_kiro_tool(table_name)` returns a @tool decorated function.
"""

from __future__ import annotations

import logging
import os

import boto3
from boto3.dynamodb.conditions import Key
from strands import tool

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 500
DEFAULT_MAX_PROMPTS = 50


def _truncate(text: str, max_len: int = MAX_PROMPT_CHARS) -> str:
    """Truncate text to max_len characters, appending '...' if truncated."""
    if not text or len(text) <= max_len:
        return text or ""
    return text[:max_len] + "..."


def build_kiro_tool(table_name: str, dynamodb_resource=None):
    """Factory that returns a @tool decorated function for Kiro data access.

    Args:
        table_name: DynamoDB table name for the Analytics_Table.
        dynamodb_resource: Optional boto3 DynamoDB resource (for testing).

    Returns:
        A @tool decorated function that the Strands Agent can call.
    """
    resource = dynamodb_resource or boto3.resource("dynamodb", region_name="sa-east-1")
    table = resource.Table(table_name or "kiro-cost-analyzer-analytics")

    @tool
    def get_kiro_usage(user_id: str, start_date: str, end_date: str) -> dict:
        """Fetch Kiro AI assistant usage data for a user in a date range.

        Args:
            user_id: Kiro user identifier
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Dict with prompts (list), dailyStats (list), categoryDistribution (list)
        """
        if not user_id:
            return {"error": "MISSING_USER_ID", "message": "userId is required"}
        if not start_date or not end_date:
            return {"error": "MISSING_DATE_RANGE", "message": "startDate and endDate are required"}

        pk = f"USER#{user_id}"

        # Query daily stats
        daily_response = table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").between(
                f"STATS#DAILY#{start_date}", f"STATS#DAILY#{end_date}~"
            ),
        )
        daily_items = daily_response.get("Items", [])

        if not daily_items:
            return {
                "error": "USER_NOT_FOUND",
                "message": f"No data found for user {user_id} in the specified period",
            }

        # Query prompts
        prompts_response = table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").between(
                f"PROMPT#{start_date}", f"PROMPT#{end_date}~"
            ),
            Limit=DEFAULT_MAX_PROMPTS,
            ScanIndexForward=False,
        )
        prompts_raw = prompts_response.get("Items", [])

        # Query category distribution
        cat_response = table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("STATS#CATEGORY#"),
        )
        cat_items = cat_response.get("Items", [])

        # Format output — exclude "Empty" category prompts (turn-by-turn
        # conversation fragments with no meaningful content for analysis).
        # The literal "Empty" must match ``shared.categories.CATEGORY_EMPTY``
        # in the main app — this agent runs in a separate AgentCore
        # deployment and does not import the Lambda layer, so the value is
        # duplicated here. Update both files together.
        prompts = [
            {
                "timestamp": p.get("timestamp", ""),
                "content": _truncate(str(p.get("prompt", p.get("content", "")))),
                "category": p.get("category", "unknown"),
            }
            for p in prompts_raw
            if p.get("category", "unknown") != "Empty"
        ]

        daily_stats = [
            {
                "date": s.get("SK", "").replace("STATS#DAILY#", ""),
                "interactions": int(s.get("totalInteractions", 0)),
                "messages": int(s.get("totalMessages", 0)),
            }
            for s in daily_items
        ]

        category_distribution = [
            {
                "category": c.get("SK", "").replace("STATS#CATEGORY#", ""),
                "count": int(c.get("count", 0)),
            }
            for c in cat_items
        ]

        return {
            "prompts": prompts,
            "dailyStats": daily_stats,
            "categoryDistribution": category_distribution,
        }

    return get_kiro_usage
