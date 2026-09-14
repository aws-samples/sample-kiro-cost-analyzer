"""Analytics Writer — write operations for the Analytics_Table (DynamoDB STD)."""

from __future__ import annotations

import json
from decimal import Decimal

import boto3

try:
    from shared.sk_normalizer import normalize_sk_value
except ImportError:
    from utils.sk_normalizer import normalize_sk_value


_DECIMAL_METRICS = {"totalCredits", "overageCredits", "estimatedCostUsd"}


def _metric_add_parts(metrics: dict[str, int | float | None]) -> tuple[list[str], dict]:
    """Return DynamoDB ADD clauses/values for metrics that are present.

    ``None`` means the source does not define the metric and therefore must not
    materialize an attribute. Zero is a real value and is retained.
    """
    clauses: list[str] = []
    values: dict = {}
    for attribute, value in metrics.items():
        if value is None:
            continue
        token = f":{attribute}"
        clauses.append(f"{attribute} {token}")
        values[token] = Decimal(str(value)) if attribute in _DECIMAL_METRICS else value
    return clauses, values


class AnalyticsWriter:
    """Encapsulates all DynamoDB write operations for the Analytics_Table.

    Uses dependency injection for the DynamoDB resource and S3 client
    so that tests can substitute mocks without patching.
    """

    def __init__(
        self,
        table_name: str,
        data_bucket: str,
        dynamodb_resource=None,
        s3_client=None,
    ):
        resource = dynamodb_resource or boto3.resource("dynamodb")
        self._table = resource.Table(table_name)
        self._data_bucket = data_bucket
        self._s3 = s3_client or boto3.client("s3")

    # ------------------------------------------------------------------
    # Prompt metadata (PutItem)
    # ------------------------------------------------------------------

    def write_prompt(
        self,
        user_id: str,
        prompt_record: dict,
        prompt_content: str,
        response_content: str,
        content_in_s3: bool,
        category: str = "",
    ) -> None:
        """PutItem for prompt metadata.

        ``content_in_s3`` reflects a placement decision already made
        upstream (by the Parse Lambda, based on the combined UTF-8 byte
        size of prompt/response). When True, the S3 object at
        ``prompts-content/{requestId}.json`` is assumed to already exist
        and is NOT written again here — this method only records the
        flag on the DynamoDB item.
        """
        request_id = prompt_record["requestId"]
        timestamp = prompt_record["timestamp"]

        item = {
            "PK": f"USER#{user_id}",
            "SK": f"PROMPT#{timestamp}#{request_id}",
            "requestId": request_id,
            "modelId": prompt_record.get("modelId", ""),
            "triggerType": prompt_record.get("triggerType", ""),
            "promptLength": prompt_record.get("promptLength", 0),
            "responseLength": prompt_record.get("responseLength", 0),
            "displayName": prompt_record.get("displayName", ""),
            "userName": prompt_record.get("userName", ""),
            "region": prompt_record.get("region", ""),
            "accountId": prompt_record.get("accountId", ""),
            "conversationId": prompt_record.get("conversationId", ""),
            "utteranceId": prompt_record.get("utteranceId", ""),
            "customizationArn": prompt_record.get("customizationArn", ""),
            "contentInS3": content_in_s3,
            "category": category,
        }

        if not content_in_s3:
            item["prompt"] = prompt_content
            item["response"] = response_content

        self._table.put_item(Item=item)

    # ------------------------------------------------------------------
    # Daily stats (UpdateItem ADD)
    # ------------------------------------------------------------------

    def increment_daily_stats(
        self,
        user_id: str,
        date: str,
        credits: float | None,
        overage: float | None,
        messages: int | None,
        conversations: int | None,
        interactions: int | None,
        subscription_tier: str = "",
        client_type: str = "",
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
    ) -> None:
        """Accumulate source-present metrics for ``STATS#DAILY#{date}``.

        ``None`` denotes a metric this source does not define; zero remains a
        real value. Tier and client type are unconditionally refreshed when
        present so upgrades and source changes remain visible.
        """
        add_clauses, expr_values = _metric_add_parts({
            "totalCredits": credits,
            "overageCredits": overage,
            "totalMessages": messages,
            "totalConversations": conversations,
            "totalInteractions": interactions,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cacheReadTokens": cache_read_tokens,
            "cacheWriteTokens": cache_write_tokens,
            "estimatedCostUsd": estimated_cost_usd,
        })

        update_parts: list[str] = []
        set_clauses: list[str] = []
        if subscription_tier:
            set_clauses.append("subscriptionTier = :tier")
            expr_values[":tier"] = subscription_tier
        if client_type:
            set_clauses.append("clientType = :ctype")
            expr_values[":ctype"] = client_type

        if set_clauses:
            update_parts.append("SET " + ", ".join(set_clauses))
        if add_clauses:
            update_parts.append("ADD " + ", ".join(add_clauses))
        if not update_parts:
            return

        self._table.update_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"STATS#DAILY#{date}",
            },
            UpdateExpression=" ".join(update_parts),
            ExpressionAttributeValues=expr_values,
        )

    # ------------------------------------------------------------------
    # Model distribution (UpdateItem ADD + SET if_not_exists)
    # ------------------------------------------------------------------

    def increment_model_count(
        self,
        user_id: str,
        normalized_model_id: str,
        raw_model_id: str,
    ) -> None:
        """UpdateItem ADD for STATS#MODEL#{normalizedModelId}.

        Also persists the original raw value via SET if_not_exists so the
        first write wins and subsequent calls don't overwrite it.
        """
        self._table.update_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"STATS#MODEL#{normalized_model_id}",
            },
            UpdateExpression=(
                "ADD #count :one "
                "SET rawModelId = if_not_exists(rawModelId, :raw)"
            ),
            ExpressionAttributeNames={
                "#count": "count",
            },
            ExpressionAttributeValues={
                ":one": 1,
                ":raw": raw_model_id,
            },
        )

    # ------------------------------------------------------------------
    # Trigger distribution (UpdateItem ADD + SET if_not_exists)
    # ------------------------------------------------------------------

    def increment_trigger_count(
        self,
        user_id: str,
        normalized_trigger: str,
        raw_trigger: str,
    ) -> None:
        """UpdateItem ADD for STATS#TRIGGER#{normalizedTriggerType}.

        Also persists the original raw value via SET if_not_exists.
        """
        self._table.update_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"STATS#TRIGGER#{normalized_trigger}",
            },
            UpdateExpression=(
                "ADD #count :one "
                "SET rawTriggerType = if_not_exists(rawTriggerType, :raw)"
            ),
            ExpressionAttributeNames={
                "#count": "count",
            },
            ExpressionAttributeValues={
                ":one": 1,
                ":raw": raw_trigger,
            },
        )

    # ------------------------------------------------------------------
    # Category distribution (UpdateItem ADD + SET if_not_exists)
    # ------------------------------------------------------------------

    def increment_category_count(
        self,
        user_id: str,
        normalized_category: str,
        raw_category: str,
    ) -> None:
        """UpdateItem ADD for STATS#CATEGORY#{normalizedCategory}.

        Also persists the original raw value via SET if_not_exists so the
        first write wins and subsequent calls don't overwrite it.
        """
        self._table.update_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"STATS#CATEGORY#{normalized_category}",
            },
            UpdateExpression=(
                "ADD #count :one "
                "SET rawCategory = if_not_exists(rawCategory, :raw)"
            ),
            ExpressionAttributeNames={
                "#count": "count",
            },
            ExpressionAttributeValues={
                ":one": 1,
                ":raw": raw_category,
            },
        )

    # ------------------------------------------------------------------
    # Prompt category update (UpdateItem SET)
    # ------------------------------------------------------------------

    def update_prompt_category(
        self,
        pk: str,
        sk: str,
        new_category: str,
    ) -> None:
        """Update the category field on a prompt record in Analytics_Table.

        Args:
            pk: Partition key of the prompt (e.g. ``USER#{userId}``).
            sk: Sort key of the prompt (e.g. ``PROMPT#{timestamp}#{requestId}``).
            new_category: The corrected category value to set.
        """
        self._table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="SET category = :cat",
            ExpressionAttributeValues={":cat": new_category},
        )

    # ------------------------------------------------------------------
    # Category distribution decrement (UpdateItem ADD -1)
    # ------------------------------------------------------------------

    def decrement_category_count(
        self,
        user_id: str,
        normalized_category: str,
    ) -> None:
        """Decrement the counter for STATS#CATEGORY#{normalizedCategory} by 1.

        Uses ``ADD #count :neg_one`` so the counter is atomically
        decremented.  If the counter reaches zero the record is kept
        (not deleted) to preserve the category entry in the table.

        Args:
            user_id: Owner of the prompt whose category changed.
            normalized_category: Slug-normalised category value used in
                the sort key.
        """
        self._table.update_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"STATS#CATEGORY#{normalized_category}",
            },
            UpdateExpression="ADD #count :neg_one",
            ExpressionAttributeNames={
                "#count": "count",
            },
            ExpressionAttributeValues={
                ":neg_one": -1,
            },
        )

    # ------------------------------------------------------------------
    # Daily stats metadata (SET modelMessages, newUser)
    # ------------------------------------------------------------------

    def set_daily_stats_metadata(
        self,
        user_id: str,
        date: str,
        model_messages: dict[str, int] | None = None,
        new_user: bool = False,
    ) -> None:
        """SET modelMessages and/or newUser on a STATS#DAILY# item.

        Uses a separate UpdateItem from increment_daily_stats to avoid
        complicating the ADD expression. This is a SET-only operation.

        Args:
            user_id: User identifier.
            date: ISO date string (YYYY-MM-DD).
            model_messages: Dict mapping model name to message count.
            new_user: Whether this is a new user activation day.
        """
        set_clauses: list[str] = []
        expr_values: dict = {}

        if model_messages:
            set_clauses.append("modelMessages = :mm")
            expr_values[":mm"] = model_messages

        if new_user:
            # Only SET newUser when true — avoid overwriting true with false
            set_clauses.append("newUser = :nu")
            expr_values[":nu"] = True

        if not set_clauses:
            return

        self._table.update_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"STATS#DAILY#{date}",
            },
            UpdateExpression="SET " + ", ".join(set_clauses),
            ExpressionAttributeValues=expr_values,
        )

    # ------------------------------------------------------------------
    # Global daily stats (UpdateItem ADD)
    # ------------------------------------------------------------------

    def increment_global_daily_stats(
        self,
        date: str,
        credits: float | None,
        overage: float | None,
        messages: int | None,
        conversations: int | None,
        user_ids: set[str],
        *,
        interactions: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
    ) -> None:
        """Accumulate present metrics and unique users in the global daily item."""
        add_clauses, expr_values = _metric_add_parts({
            "totalCredits": credits,
            "overageCredits": overage,
            "totalMessages": messages,
            "totalConversations": conversations,
            "totalInteractions": interactions,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cacheReadTokens": cache_read_tokens,
            "cacheWriteTokens": cache_write_tokens,
            "estimatedCostUsd": estimated_cost_usd,
        })
        if user_ids:
            add_clauses.append("totalUsers :userIdSet")
            expr_values[":userIdSet"] = user_ids
        if not add_clauses:
            return

        self._table.update_item(
            Key={
                "PK": "GLOBAL",
                "SK": f"STATS#DAILY#{date}",
            },
            UpdateExpression="ADD " + ", ".join(add_clauses),
            ExpressionAttributeValues=expr_values,
        )

    # ------------------------------------------------------------------
    # Activity Summary (Upsert for frequency tracking)
    # ------------------------------------------------------------------

    def upsert_activity_summary(self, user_id: str, date: str) -> None:
        """Upsert Activity_Summary item for a user.

        Uses conditional expressions:
        - firstActiveDate: SET if_not_exists (first write wins)
        - lastActiveDate: SET if greater than current value (separate conditional update)
        - activeDays: ADD 1 (atomic counter)

        Args:
            user_id: The user identifier.
            date: ISO date string (YYYY-MM-DD) of the activity.
        """
        # First UpdateItem: set firstActiveDate (first-write-wins) + increment activeDays
        self._table.update_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": "ACTIVITY_SUMMARY",
            },
            UpdateExpression=(
                "SET firstActiveDate = if_not_exists(firstActiveDate, :date) "
                "ADD activeDays :one"
            ),
            ExpressionAttributeValues={
                ":date": date,
                ":one": 1,
            },
        )
        # Second UpdateItem (conditional): update lastActiveDate only if newer
        try:
            self._table.update_item(
                Key={
                    "PK": f"USER#{user_id}",
                    "SK": "ACTIVITY_SUMMARY",
                },
                UpdateExpression="SET lastActiveDate = :date",
                ConditionExpression=(
                    "lastActiveDate < :date OR attribute_not_exists(lastActiveDate)"
                ),
                ExpressionAttributeValues={":date": date},
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            pass  # Current lastActiveDate is already >= date

    # ------------------------------------------------------------------
    # Global breakdown by tier / client type (UpdateItem ADD)
    # ------------------------------------------------------------------

    def increment_global_tier_stats(
        self,
        date: str,
        tier: str,
        credits: float | None,
        overage: float | None,
        messages: int | None,
        conversations: int | None,
        *,
        interactions: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
    ) -> None:
        """Accumulate source-present metrics for a tier breakdown."""
        if not tier:
            return
        self._increment_global_breakdown(
            f"STATS#TIER#{tier}#{date}",
            credits,
            overage,
            messages,
            conversations,
            interactions=interactions,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )

    def increment_global_client_type_stats(
        self,
        date: str,
        client_type: str,
        credits: float | None,
        overage: float | None,
        messages: int | None,
        conversations: int | None,
        *,
        interactions: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
    ) -> None:
        """Accumulate source-present metrics for a client-type breakdown."""
        if not client_type:
            return
        self._increment_global_breakdown(
            f"STATS#CLIENT#{client_type}#{date}",
            credits,
            overage,
            messages,
            conversations,
            interactions=interactions,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )

    def _increment_global_breakdown(
        self,
        sort_key: str,
        credits: float | None,
        overage: float | None,
        messages: int | None,
        conversations: int | None,
        *,
        interactions: int | None,
        input_tokens: int | None,
        output_tokens: int | None,
        cache_read_tokens: int | None,
        cache_write_tokens: int | None,
        estimated_cost_usd: float | None,
    ) -> None:
        add_clauses, expr_values = _metric_add_parts({
            "totalCredits": credits,
            "overageCredits": overage,
            "totalMessages": messages,
            "totalConversations": conversations,
            "totalInteractions": interactions,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cacheReadTokens": cache_read_tokens,
            "cacheWriteTokens": cache_write_tokens,
            "estimatedCostUsd": estimated_cost_usd,
        })
        if not add_clauses:
            return
        self._table.update_item(
            Key={"PK": "GLOBAL", "SK": sort_key},
            UpdateExpression="ADD " + ", ".join(add_clauses),
            ExpressionAttributeValues=expr_values,
        )
