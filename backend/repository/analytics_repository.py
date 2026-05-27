"""Repository layer encapsulating all read access patterns to the Analytics_Table."""

from __future__ import annotations

import base64
import json
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr

try:
    from shared.structured_logger import StructuredLogger
except ImportError:  # pragma: no cover — fallback for non-Lambda execution paths
    from layers.shared.shared.structured_logger import StructuredLogger

logger = StructuredLogger("analytics-repository")


def _coerce_bilingual_insights(raw) -> dict:
    """Coerce ``insights`` to the bilingual map ``{en: [...], "pt-BR": [...]}``.

    Mirrors the defensive helper in ``backend/handlers/agent_correlation_handler``.
    Defined locally here to keep the repository and handler decoupled — neither
    module cross-imports the other. Per Requirement 8.10, a legacy
    ``List<String>`` (pt-BR insights persisted before bilingual support) becomes
    ``{"en": [], "pt-BR": <legacy list>}``. A modern dict is preserved
    structurally (lists are copied so callers can mutate without aliasing).
    Missing / ``None`` / unexpected types collapse to empty bilingual lists.

    Args:
        raw: Whatever is in ``item["insights"]`` — typically a dict, list, or
            missing / ``None``.

    Returns:
        Always a dict with both ``en`` and ``pt-BR`` keys mapping to lists.
    """
    if isinstance(raw, dict):
        return {
            "en": list(raw.get("en", []) or []),
            "pt-BR": list(raw.get("pt-BR", []) or []),
        }
    if isinstance(raw, list):
        return {"en": [], "pt-BR": list(raw)}
    return {"en": [], "pt-BR": []}


class AnalyticsRepository:
    """Encapsulates all DynamoDB read operations for the Analytics_Table.

    Uses the boto3 DynamoDB *resource* (Table) API with dependency injection
    for testability.
    """

    def __init__(self, table_name: str, dynamodb_resource=None):
        resource = dynamodb_resource or boto3.resource("dynamodb")
        self._resource = resource
        self._table_name = table_name
        self._table = resource.Table(table_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_decimals(obj):
        """Recursively convert Decimal values to int or float."""
        if isinstance(obj, list):
            return [AnalyticsRepository._convert_decimals(i) for i in obj]
        if isinstance(obj, dict):
            return {k: AnalyticsRepository._convert_decimals(v) for k, v in obj.items()}
        if isinstance(obj, Decimal):
            if obj == int(obj):
                return int(obj)
            return float(obj)
        return obj

    @staticmethod
    def _encode_next_token(last_evaluated_key: dict | None) -> str | None:
        if not last_evaluated_key:
            return None
        return base64.b64encode(json.dumps(last_evaluated_key).encode()).decode()

    @staticmethod
    def _decode_next_token(token: str | None) -> dict | None:
        if not token:
            return None
        return json.loads(base64.b64decode(token.encode()).decode())

    # ------------------------------------------------------------------
    # 1. User daily stats
    # ------------------------------------------------------------------

    def get_user_daily_stats(
        self, user_id: str, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        """Query STATS#DAILY# items for a user, with optional date range filter.

        Uses ``begins_with`` when no date range is given, or ``between`` when
        both *start_date* and *end_date* are provided.
        """
        pk = f"USER#{user_id}"

        if start_date and end_date:
            key_condition = Key("PK").eq(pk) & Key("SK").between(
                f"STATS#DAILY#{start_date}", f"STATS#DAILY#{end_date}"
            )
        else:
            key_condition = Key("PK").eq(pk) & Key("SK").begins_with("STATS#DAILY#")

        response = self._table.query(KeyConditionExpression=key_condition)
        items = response.get("Items", [])

        # Handle pagination transparently — daily stats are bounded per user
        while "LastEvaluatedKey" in response:
            response = self._table.query(
                KeyConditionExpression=key_condition,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return self._convert_decimals(items)

    # ------------------------------------------------------------------
    # 2. User model distribution
    # ------------------------------------------------------------------

    def get_user_model_distribution(self, user_id: str) -> list[dict]:
        """Query STATS#MODEL# items for a user."""
        pk = f"USER#{user_id}"
        key_condition = Key("PK").eq(pk) & Key("SK").begins_with("STATS#MODEL#")

        response = self._table.query(KeyConditionExpression=key_condition)
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = self._table.query(
                KeyConditionExpression=key_condition,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return self._convert_decimals(items)

    # ------------------------------------------------------------------
    # 3. User trigger distribution
    # ------------------------------------------------------------------

    def get_user_trigger_distribution(self, user_id: str) -> list[dict]:
        """Query STATS#TRIGGER# items for a user."""
        pk = f"USER#{user_id}"
        key_condition = Key("PK").eq(pk) & Key("SK").begins_with("STATS#TRIGGER#")

        response = self._table.query(KeyConditionExpression=key_condition)
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = self._table.query(
                KeyConditionExpression=key_condition,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return self._convert_decimals(items)

    # ------------------------------------------------------------------
    # 3b. User category distribution
    # ------------------------------------------------------------------

    def get_user_category_distribution(self, user_id: str) -> list[dict]:
        """Query STATS#CATEGORY# items for a user."""
        pk = f"USER#{user_id}"
        key_condition = Key("PK").eq(pk) & Key("SK").begins_with("STATS#CATEGORY#")

        response = self._table.query(KeyConditionExpression=key_condition)
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = self._table.query(
                KeyConditionExpression=key_condition,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return self._convert_decimals(items)

    # ------------------------------------------------------------------
    # 4. User prompts (paginated)
    # ------------------------------------------------------------------

    def get_user_prompts(
        self,
        user_id: str,
        limit: int = 20,
        start_date: str | None = None,
        end_date: str | None = None,
        scan_forward: bool = False,
        next_token: str | None = None,
        category: str | None = None,
        exclude_categories: list[str] | None = None,
    ) -> dict:
        """Query PROMPT# items for a user with pagination and optional filters.

        When *category* or *exclude_categories* is provided, DynamoDB
        FilterExpression is used.  Because DynamoDB applies Limit before
        filtering, we paginate internally to collect enough items.

        Returns a dict with ``items`` and ``nextToken``.
        """
        pk = f"USER#{user_id}"

        if start_date and end_date:
            # Tilde (~) sorts after all timestamps on a given date
            key_condition = Key("PK").eq(pk) & Key("SK").between(
                f"PROMPT#{start_date}", f"PROMPT#{end_date}~"
            )
        else:
            key_condition = Key("PK").eq(pk) & Key("SK").begins_with("PROMPT#")

        # Build optional FilterExpression
        filter_expr = None
        if category and exclude_categories:
            filter_expr = (
                Attr("category").eq(category)
                & Attr("category").is_in(
                    [c for c in [category] if c not in exclude_categories]
                )
            )
        elif category:
            filter_expr = Attr("category").eq(category)
        elif exclude_categories:
            # DynamoDB doesn't have a NOT IN, so chain ne() conditions
            filter_expr = None
            for exc in exclude_categories:
                cond = Attr("category").ne(exc)
                filter_expr = cond if filter_expr is None else (filter_expr & cond)

        has_filter = filter_expr is not None

        kwargs: dict = {
            "KeyConditionExpression": key_condition,
            "ScanIndexForward": scan_forward,
        }
        if filter_expr:
            kwargs["FilterExpression"] = filter_expr

        exclusive_start_key = self._decode_next_token(next_token)
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key

        if has_filter:
            # With filters, DynamoDB may return fewer items than Limit.
            # Paginate internally to collect enough items.
            collected: list[dict] = []
            last_key = exclusive_start_key

            while len(collected) < limit:
                page_kwargs = {**kwargs, "Limit": limit * 3}
                if last_key:
                    page_kwargs["ExclusiveStartKey"] = last_key

                response = self._table.query(**page_kwargs)
                page_items = self._convert_decimals(response.get("Items", []))
                collected.extend(page_items)
                last_key = response.get("LastEvaluatedKey")

                if not last_key:
                    break

            items = collected[:limit]
            # If we have more collected or there are more pages, build nextToken
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
            response = self._table.query(**kwargs)
            items = self._convert_decimals(response.get("Items", []))
            result_next_token = self._encode_next_token(response.get("LastEvaluatedKey"))

        # Extract timestamp from SK if not stored as a separate attribute
        for item in items:
            if "timestamp" not in item and "SK" in item:
                sk = item["SK"]
                # SK format: PROMPT#{timestamp}#{requestId}
                if sk.startswith("PROMPT#"):
                    parts = sk.split("#", 2)
                    if len(parts) >= 2:
                        item["timestamp"] = parts[1]

        return {"items": items, "nextToken": result_next_token}

    # ------------------------------------------------------------------
    # 5. Global daily stats
    # ------------------------------------------------------------------

    def get_global_daily_stats(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        """Query GLOBAL / STATS#DAILY# items with optional date range filter."""
        pk = "GLOBAL"

        if start_date and end_date:
            key_condition = Key("PK").eq(pk) & Key("SK").between(
                f"STATS#DAILY#{start_date}", f"STATS#DAILY#{end_date}"
            )
        else:
            key_condition = Key("PK").eq(pk) & Key("SK").begins_with("STATS#DAILY#")

        response = self._table.query(KeyConditionExpression=key_condition)
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = self._table.query(
                KeyConditionExpression=key_condition,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return self._convert_decimals(items)

    # ------------------------------------------------------------------
    # 5b. Global tier breakdown
    # ------------------------------------------------------------------

    def get_global_tier_breakdown(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        """Query GLOBAL / STATS#TIER# items with optional date range filter."""
        pk = "GLOBAL"

        if start_date and end_date:
            key_condition = Key("PK").eq(pk) & Key("SK").between(
                f"STATS#TIER#", f"STATS#TIER#~"
            )
        else:
            key_condition = Key("PK").eq(pk) & Key("SK").begins_with("STATS#TIER#")

        response = self._table.query(KeyConditionExpression=key_condition)
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = self._table.query(
                KeyConditionExpression=key_condition,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return self._convert_decimals(items)

    # ------------------------------------------------------------------
    # 5c. Global client type breakdown
    # ------------------------------------------------------------------

    def get_global_client_type_breakdown(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        """Query GLOBAL / STATS#CLIENT# items with optional date range filter."""
        pk = "GLOBAL"

        if start_date and end_date:
            key_condition = Key("PK").eq(pk) & Key("SK").between(
                f"STATS#CLIENT#", f"STATS#CLIENT#~"
            )
        else:
            key_condition = Key("PK").eq(pk) & Key("SK").begins_with("STATS#CLIENT#")

        response = self._table.query(KeyConditionExpression=key_condition)
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = self._table.query(
                KeyConditionExpression=key_condition,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return self._convert_decimals(items)

    # ------------------------------------------------------------------
    # 6. Prompt by requestId (GSI)
    # ------------------------------------------------------------------

    def get_prompt_by_request_id(self, request_id: str) -> dict | None:
        """Query the ``requestId-index`` GSI to find a prompt by requestId."""
        response = self._table.query(
            IndexName="requestId-index",
            KeyConditionExpression=Key("requestId").eq(request_id),
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            return None
        return self._convert_decimals(items[0])

    # ------------------------------------------------------------------
    # 7. Scan user stats (aggregated)
    # ------------------------------------------------------------------

    def scan_user_stats(
        self,
        limit: int = 50,
        next_token: str | None = None,
        subscription_tier: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Scan for STATS#DAILY# items, aggregate by user (PK).

        Scans the **entire** table so that every user is aggregated before
        applying sorting and pagination.  The previous implementation stopped
        scanning as soon as ``limit`` unique users were found, which caused
        users whose partition keys were hashed into later scan segments to
        be silently omitted from the results.

        Args:
            limit: Maximum number of users to return per page.
            next_token: Cursor for pagination.
            subscription_tier: Optional filter by subscription tier.
            start_date: Optional start date (YYYY-MM-DD) for filtering daily stats.
            end_date: Optional end date (YYYY-MM-DD) for filtering daily stats.

        Returns a dict with ``users`` (list of aggregated user dicts),
        ``nextToken`` for cursor-based pagination, and ``scannedCount``.
        """
        # Build filter expression with optional date range
        filter_expr = Attr("SK").begins_with("STATS#DAILY#")
        if start_date:
            filter_expr = filter_expr & Attr("SK").gte(f"STATS#DAILY#{start_date}")
        if end_date:
            filter_expr = filter_expr & Attr("SK").lte(f"STATS#DAILY#{end_date}")

        kwargs: dict = {
            "FilterExpression": filter_expr,
        }

        # Full-table aggregation — scan every page.
        user_map: dict[str, dict] = {}
        scanned_count = 0

        while True:
            response = self._table.scan(**kwargs)
            items = response.get("Items", [])
            scanned_count += response.get("ScannedCount", 0)

            for item in items:
                pk = item.get("PK", "")
                # Skip GLOBAL items
                if pk == "GLOBAL":
                    continue

                user_id = pk.replace("USER#", "", 1) if pk.startswith("USER#") else pk

                if user_id not in user_map:
                    user_map[user_id] = {
                        "userId": user_id,
                        "totalCredits": 0,
                        "overageCredits": 0,
                        "totalMessages": 0,
                        "totalConversations": 0,
                        "totalInteractions": 0,
                        "daysActive": 0,
                        "subscriptionTier": "",
                        "displayName": "",
                        "userName": "",
                    }

                entry = user_map[user_id]
                entry["totalCredits"] += float(item.get("totalCredits", 0))
                entry["overageCredits"] += float(item.get("overageCredits", 0))
                entry["totalMessages"] += int(item.get("totalMessages", 0))
                entry["totalConversations"] += int(item.get("totalConversations", 0))
                entry["totalInteractions"] += int(item.get("totalInteractions", 0))
                entry["daysActive"] += 1

                # Always update subscriptionTier to the value from the most
                # recent daily stat so that tier upgrades are reflected.
                if item.get("subscriptionTier"):
                    item_date = item.get("SK", "").replace("STATS#DAILY#", "")
                    prev_date = entry.get("_latestTierDate", "")
                    if item_date >= prev_date:
                        entry["subscriptionTier"] = item["subscriptionTier"]
                        entry["_latestTierDate"] = item_date

            last_evaluated_key = response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break

            kwargs["ExclusiveStartKey"] = last_evaluated_key

        users = list(user_map.values())

        # Remove internal helper field used for tier date tracking
        for u in users:
            u.pop("_latestTierDate", None)

        # Apply subscription_tier filter if provided
        if subscription_tier:
            users = [u for u in users if u.get("subscriptionTier") == subscription_tier]

        # Sort by totalCredits descending for consistent ordering
        users.sort(key=lambda u: u["totalCredits"], reverse=True)

        # Cursor-based pagination over the fully-aggregated list
        start_index = 0
        if next_token:
            decoded = self._decode_next_token(next_token)
            if decoded and "startIndex" in decoded:
                start_index = int(decoded["startIndex"])

        page = users[start_index : start_index + limit]
        has_more = (start_index + limit) < len(users)

        result_next_token = None
        if has_more:
            result_next_token = self._encode_next_token(
                {"startIndex": start_index + limit}
            )

        return {
            "users": self._convert_decimals(page),
            "nextToken": result_next_token,
            "scannedCount": scanned_count,
        }

    # ------------------------------------------------------------------
    # 8. Analysis cache (ANALYSIS#{date}#{id})
    # ------------------------------------------------------------------

    _ANALYSIS_TTL_DAYS = 7

    def put_analysis(self, user_id: str, analysis_data: dict) -> dict:
        """Persist an agent correlation analysis result.

        Creates an item with PK=USER#{userId}, SK=ANALYSIS#{date}#{id}.
        Sets a TTL of 7 days from now.

        Args:
            user_id: Kiro user identifier.
            analysis_data: Dict with impactScore, impactLevel, correlations,
                insights, period, model, tokensUsed, analyzedAt.

        Returns:
            The stored item.
        """
        now = analysis_data.get("analyzedAt", "")
        date_part = now[:10] if now else time.strftime("%Y-%m-%d")
        time_part = now[11:19].replace(":", "") if len(now) > 19 else time.strftime("%H%M%S")
        analysis_id = str(uuid.uuid4())[:8]

        ttl = int(time.time()) + (self._ANALYSIS_TTL_DAYS * 86400)

        item = {
            "PK": f"USER#{user_id}",
            "SK": f"ANALYSIS#{date_part}#{time_part}#{analysis_id}",
            "TTL": ttl,
            **analysis_data,
        }

        self._table.put_item(Item=json.loads(json.dumps(item), parse_float=Decimal))
        return self._convert_decimals(item)

    def get_latest_analysis(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        max_age_hours: int = 24,
    ) -> dict | None:
        """Retrieve the most recent cached analysis for a user.

        Returns the latest ANALYSIS# item that is less than max_age_hours old.
        If start_date/end_date are provided, also checks that the cached period
        matches.

        Returns:
            The cached analysis dict, or None if no valid cache found.
        """
        pk = f"USER#{user_id}"
        key_condition = Key("PK").eq(pk) & Key("SK").begins_with("ANALYSIS#")

        response = self._table.query(
            KeyConditionExpression=key_condition,
            ScanIndexForward=False,
            Limit=5,
        )
        items = response.get("Items", [])
        if not items:
            return None

        cutoff = time.time() - (max_age_hours * 3600)

        for item in items:
            analyzed_at = item.get("analyzedAt", "")
            if not analyzed_at:
                continue

            ttl_val = int(item.get("TTL", 0))
            if ttl_val and ttl_val < time.time():
                continue

            from datetime import datetime, timezone
            try:
                ts = datetime.fromisoformat(analyzed_at.replace("Z", "+00:00"))
                item_epoch = ts.timestamp()
            except (ValueError, TypeError):
                continue

            if item_epoch < cutoff:
                continue

            if start_date and end_date:
                period = item.get("period", {})
                if period.get("startDate") != start_date or period.get("endDate") != end_date:
                    continue

            # Read-side coercion: legacy items persisted before bilingual
            # insights support stored ``insights`` as a flat ``List<String>``
            # (pt-BR-only). Coerce on read to the bilingual map shape so the
            # response contract stays total. The underlying DynamoDB item is
            # NOT mutated — we only operate on the in-memory copy returned
            # to the caller. Legacy items expire naturally via the existing
            # 7-day TTL (Requirement 8.10).
            converted = self._convert_decimals(item)
            raw_insights = converted.get("insights")
            if isinstance(raw_insights, list):
                logger.info(
                    "Coerced legacy insights shape on read",
                    legacyInsightsCoerced=True,
                    sk=converted.get("SK", ""),
                )
            converted["insights"] = _coerce_bilingual_insights(raw_insights)
            return converted

        return None

    def list_analyses(self, user_id: str, limit: int = 10) -> list[dict]:
        """List recent analyses for a user (most recent first).

        Args:
            user_id: Kiro user identifier.
            limit: Maximum items to return.

        Returns:
            List of analysis dicts.
        """
        pk = f"USER#{user_id}"
        key_condition = Key("PK").eq(pk) & Key("SK").begins_with("ANALYSIS#")

        response = self._table.query(
            KeyConditionExpression=key_condition,
            ScanIndexForward=False,
            Limit=limit,
        )
        items = response.get("Items", [])
        return self._convert_decimals(items)

    # ------------------------------------------------------------------
    # 9. Activity Summary
    # ------------------------------------------------------------------

    def get_activity_summary(self, user_id: str) -> dict | None:
        """Get Activity_Summary item for a single user.

        Args:
            user_id: Kiro user identifier.

        Returns:
            The Activity_Summary item dict (with Decimals converted) or None
            if no summary exists for the user.
        """
        response = self._table.get_item(
            Key={"PK": f"USER#{user_id}", "SK": "ACTIVITY_SUMMARY"}
        )
        item = response.get("Item")
        return self._convert_decimals(item) if item else None

    def batch_get_activity_summaries(self, user_ids: list[str]) -> dict[str, dict]:
        """Batch-retrieve Activity_Summary items for multiple users.

        Uses BatchGetItem with chunks of 100 keys (DynamoDB limit).
        Handles UnprocessedKeys with a retry loop.

        Args:
            user_ids: List of user identifiers to fetch summaries for.

        Returns:
            Dict mapping userId -> summary dict. Users without an
            Activity_Summary item are absent from the result.
        """
        results: dict[str, dict] = {}
        if not user_ids:
            return results

        # Process in chunks of 100
        for i in range(0, len(user_ids), 100):
            chunk = user_ids[i : i + 100]
            keys = [{"PK": f"USER#{uid}", "SK": "ACTIVITY_SUMMARY"} for uid in chunk]
            response = self._resource.batch_get_item(
                RequestItems={self._table_name: {"Keys": keys}}
            )
            for item in response.get("Responses", {}).get(self._table_name, []):
                uid = item["PK"].replace("USER#", "", 1)
                results[uid] = self._convert_decimals(item)

            # Handle unprocessed keys (retry)
            unprocessed = response.get("UnprocessedKeys", {}).get(self._table_name)
            while unprocessed:
                response = self._resource.batch_get_item(
                    RequestItems={self._table_name: unprocessed}
                )
                for item in response.get("Responses", {}).get(self._table_name, []):
                    uid = item["PK"].replace("USER#", "", 1)
                    results[uid] = self._convert_decimals(item)
                unprocessed = response.get("UnprocessedKeys", {}).get(self._table_name)

        return results

    def scan_activity_summaries(self) -> dict[str, dict]:
        """Scan all ACTIVITY_SUMMARY items from the table.

        Returns a dict mapping userId -> summary dict for every user
        that has a pre-computed Activity_Summary.
        """
        results: dict[str, dict] = {}
        kwargs: dict = {
            "FilterExpression": Attr("SK").eq("ACTIVITY_SUMMARY"),
            "ProjectionExpression": "PK, SK, firstActiveDate, lastActiveDate, activeDays",
        }

        while True:
            response = self._table.scan(**kwargs)
            for item in response.get("Items", []):
                pk = item.get("PK", "")
                if pk.startswith("USER#"):
                    uid = pk.replace("USER#", "", 1)
                    results[uid] = self._convert_decimals(item)

            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        return results
