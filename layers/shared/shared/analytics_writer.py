"""Analytics Writer — write operations for the Analytics_Table (DynamoDB STD)."""

from __future__ import annotations

import json
from decimal import Decimal

import boto3

try:
    from shared.sk_normalizer import normalize_sk_value
except ImportError:
    from utils.sk_normalizer import normalize_sk_value

# 4KB threshold for inline vs S3 storage of prompt content.
_INLINE_THRESHOLD_BYTES = 4096


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
        category: str = "",
    ) -> None:
        """PutItem for prompt metadata.

        Decides inline vs S3 based on the combined UTF-8 byte size of
        *prompt_content* and *response_content*.
        """
        request_id = prompt_record["requestId"]
        timestamp = prompt_record["timestamp"]

        combined_size = len(prompt_content.encode("utf-8")) + len(
            response_content.encode("utf-8")
        )
        content_in_s3 = combined_size > _INLINE_THRESHOLD_BYTES

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

        if content_in_s3:
            # Write content to S3
            s3_key = f"prompts-content/{request_id}.json"
            self._s3.put_object(
                Bucket=self._data_bucket,
                Key=s3_key,
                Body=json.dumps(
                    {"prompt": prompt_content, "response": response_content},
                    ensure_ascii=False,
                ).encode("utf-8"),
                ContentType="application/json",
            )
        else:
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
        credits: float,
        overage: float,
        messages: int,
        conversations: int,
        interactions: int,
        subscription_tier: str = "",
        client_type: str = "",
    ) -> None:
        """UpdateItem ADD for STATS#DAILY#{date}.

        Also persists ``subscriptionTier`` and ``clientType`` via
        unconditional ``SET`` so that tier/client upgrades are always
        reflected.  Previous versions used ``if_not_exists`` which
        prevented updates when a user changed tiers.
        """
        update_parts = [
            "ADD totalCredits :credits, "
            "overageCredits :overage, "
            "totalMessages :messages, "
            "totalConversations :conversations, "
            "totalInteractions :interactions",
        ]
        expr_values: dict = {
            ":credits": Decimal(str(credits)),
            ":overage": Decimal(str(overage)),
            ":messages": messages,
            ":conversations": conversations,
            ":interactions": interactions,
        }

        set_clauses: list[str] = []
        if subscription_tier:
            set_clauses.append("subscriptionTier = :tier")
            expr_values[":tier"] = subscription_tier
        if client_type:
            set_clauses.append("clientType = :ctype")
            expr_values[":ctype"] = client_type

        if set_clauses:
            update_parts.insert(0, "SET " + ", ".join(set_clauses))

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
        credits: float,
        overage: float,
        messages: int,
        conversations: int,
        user_ids: set[str],
    ) -> None:
        """UpdateItem ADD for GLOBAL / STATS#DAILY#{date}.

        Uses ADD with a DynamoDB String Set for totalUsers so that
        unique user IDs accumulate across concurrent invocations.
        """
        self._table.update_item(
            Key={
                "PK": "GLOBAL",
                "SK": f"STATS#DAILY#{date}",
            },
            UpdateExpression=(
                "ADD totalCredits :credits, "
                "overageCredits :overage, "
                "totalMessages :messages, "
                "totalConversations :conversations, "
                "totalUsers :userIdSet"
            ),
            ExpressionAttributeValues={
                ":credits": Decimal(str(credits)),
                ":overage": Decimal(str(overage)),
                ":messages": messages,
                ":conversations": conversations,
                ":userIdSet": user_ids,
            },
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
        credits: float,
        overage: float,
        messages: int,
        conversations: int,
    ) -> None:
        """UpdateItem ADD for GLOBAL / STATS#TIER#{tier}#{date}."""
        if not tier:
            return
        self._table.update_item(
            Key={
                "PK": "GLOBAL",
                "SK": f"STATS#TIER#{tier}#{date}",
            },
            UpdateExpression=(
                "ADD totalCredits :credits, "
                "overageCredits :overage, "
                "totalMessages :messages, "
                "totalConversations :conversations"
            ),
            ExpressionAttributeValues={
                ":credits": Decimal(str(credits)),
                ":overage": Decimal(str(overage)),
                ":messages": messages,
                ":conversations": conversations,
            },
        )

    def increment_global_client_type_stats(
        self,
        date: str,
        client_type: str,
        credits: float,
        overage: float,
        messages: int,
        conversations: int,
    ) -> None:
        """UpdateItem ADD for GLOBAL / STATS#CLIENT#{clientType}#{date}."""
        if not client_type:
            return
        self._table.update_item(
            Key={
                "PK": "GLOBAL",
                "SK": f"STATS#CLIENT#{client_type}#{date}",
            },
            UpdateExpression=(
                "ADD totalCredits :credits, "
                "overageCredits :overage, "
                "totalMessages :messages, "
                "totalConversations :conversations"
            ),
            ExpressionAttributeValues={
                ":credits": Decimal(str(credits)),
                ":overage": Decimal(str(overage)),
                ":messages": messages,
                ":conversations": conversations,
            },
        )
