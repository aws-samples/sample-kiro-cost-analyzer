"""Repository layer encapsulating all read/write access patterns to the FeedbackTable."""

from __future__ import annotations

import base64
import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr


class FeedbackRepository:
    """Encapsulates all DynamoDB operations for the FeedbackTable.

    Uses the boto3 DynamoDB *resource* (Table) API with dependency injection
    for testability.
    """

    def __init__(self, table_name: str | None = None, dynamodb_resource=None):
        """Initialize the repository.

        Args:
            table_name: DynamoDB table name. Defaults to the FEEDBACK_TABLE
                environment variable.
            dynamodb_resource: Optional boto3 DynamoDB resource for dependency
                injection (used in tests).
        """
        resolved_table = table_name or os.environ.get("FEEDBACK_TABLE", "")
        resource = dynamodb_resource or boto3.resource("dynamodb")
        self._table = resource.Table(resolved_table)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_decimals(obj):
        """Recursively convert Decimal values to int or float."""
        if isinstance(obj, list):
            return [FeedbackRepository._convert_decimals(i) for i in obj]
        if isinstance(obj, dict):
            return {k: FeedbackRepository._convert_decimals(v) for k, v in obj.items()}
        if isinstance(obj, Decimal):
            if obj == int(obj):
                return int(obj)
            return float(obj)
        return obj

    @staticmethod
    def _encode_next_token(last_evaluated_key: dict | None) -> str | None:
        """Encode a DynamoDB LastEvaluatedKey as a base64 JSON string.

        Args:
            last_evaluated_key: The LastEvaluatedKey dict from a DynamoDB
                response, or None.

        Returns:
            A base64-encoded JSON string, or None if the input is falsy.
        """
        if not last_evaluated_key:
            return None
        return base64.b64encode(json.dumps(last_evaluated_key).encode()).decode()

    @staticmethod
    def _decode_next_token(token: str | None) -> dict | None:
        """Decode a base64 JSON nextToken back into a DynamoDB ExclusiveStartKey.

        Args:
            token: A base64-encoded JSON string, or None.

        Returns:
            The decoded dict, or None if the input is falsy.
        """
        if not token:
            return None
        return json.loads(base64.b64decode(token.encode()).decode())

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def write_feedback(self, feedback: dict) -> None:
        """Write a feedback record to the FeedbackTable.

        Args:
            feedback: A dict containing at minimum PK, SK, and all required
                feedback attributes (requestId, originalCategory,
                suggestedCategory, promptSnippet, reason, submittedBy,
                status, createdAt, promptPK, promptSK).
        """
        self._table.put_item(Item=feedback)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_pending_by_request_id(self, request_id: str) -> dict | None:
        """Query for a pending feedback record by requestId.

        Uses PK = FEEDBACK#{requestId} and filters by status = "pending".

        Args:
            request_id: The prompt requestId to look up.

        Returns:
            The first pending feedback dict, or None if no pending feedback
            exists for this requestId.
        """
        pk = f"FEEDBACK#{request_id}"
        response = self._table.query(
            KeyConditionExpression=Key("PK").eq(pk),
            FilterExpression=Attr("status").eq("pending"),
        )
        items = response.get("Items", [])
        if not items:
            return None
        return self._convert_decimals(items[0])

    def list_feedbacks(
        self,
        status: str | None = None,
        limit: int = 20,
        next_token: str | None = None,
    ) -> dict:
        """Scan feedbacks with optional status filter and pagination.

        Args:
            status: Optional status filter ("pending", "approved", "rejected").
            limit: Maximum number of items to return (default 20).
            next_token: Pagination token from a previous call.

        Returns:
            A dict with ``feedbacks`` (list of feedback dicts) and
            ``nextToken`` (str or None).
        """
        kwargs: dict = {}

        if status:
            kwargs["FilterExpression"] = Attr("status").eq(status)

        exclusive_start_key = self._decode_next_token(next_token)
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key

        has_filter = status is not None

        if has_filter:
            # With filters, DynamoDB may return fewer items than Limit.
            # Paginate internally to collect enough items.
            collected: list[dict] = []
            last_key = exclusive_start_key

            while len(collected) < limit:
                page_kwargs = {**kwargs, "Limit": limit * 3}
                if last_key:
                    page_kwargs["ExclusiveStartKey"] = last_key

                response = self._table.scan(**page_kwargs)
                page_items = self._convert_decimals(response.get("Items", []))
                collected.extend(page_items)
                last_key = response.get("LastEvaluatedKey")

                if not last_key:
                    break

            items = collected[:limit]

            if len(collected) > limit:
                overflow_item = collected[limit]
                result_next_token = self._encode_next_token(
                    {"PK": overflow_item["PK"], "SK": overflow_item["SK"]}
                )
            elif last_key:
                result_next_token = self._encode_next_token(last_key)
            else:
                result_next_token = None
        else:
            kwargs["Limit"] = limit
            response = self._table.scan(**kwargs)
            items = self._convert_decimals(response.get("Items", []))
            result_next_token = self._encode_next_token(
                response.get("LastEvaluatedKey")
            )

        return {"feedbacks": items, "nextToken": result_next_token}

    def get_feedback_by_pk_sk(self, pk: str, sk: str) -> dict | None:
        """Get a specific feedback record by its composite key.

        Args:
            pk: The partition key (e.g. ``FEEDBACK#{requestId}``).
            sk: The sort key (e.g. ``FEEDBACK#{timestamp}``).

        Returns:
            The feedback dict, or None if not found.
        """
        response = self._table.get_item(Key={"PK": pk, "SK": sk})
        item = response.get("Item")
        if not item:
            return None
        return self._convert_decimals(item)

    # ------------------------------------------------------------------
    # Update operations
    # ------------------------------------------------------------------

    def update_feedback_status(
        self,
        pk: str,
        sk: str,
        status: str,
        reviewed_by: str,
        reviewed_at: str,
    ) -> None:
        """Update the status, reviewedBy, and reviewedAt fields of a feedback.

        Args:
            pk: The partition key of the feedback record.
            sk: The sort key of the feedback record.
            status: The new status ("approved" or "rejected").
            reviewed_by: The username of the reviewing admin.
            reviewed_at: ISO 8601 timestamp of the review.
        """
        self._table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression=(
                "SET #status = :status, "
                "reviewedBy = :reviewed_by, "
                "reviewedAt = :reviewed_at"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":reviewed_by": reviewed_by,
                ":reviewed_at": reviewed_at,
            },
        )
