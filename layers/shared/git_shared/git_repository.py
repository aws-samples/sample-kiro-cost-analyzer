"""Repository layer for Git integration data in the Analytics_Table.

Encapsulates all DynamoDB operations for Git repositories, user mappings,
Git activities (commits, PRs, reviews) and sync stats. Follows the same
Single-Table Design patterns used by AnalyticsRepository.
"""

from __future__ import annotations

import base64
import json
import logging
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key

try:
    from git_shared.git_providers import mapping_sort_key
except ImportError:
    from layers.shared.git_shared.git_providers import mapping_sort_key

logger = logging.getLogger(__name__)


class GitRepository:
    """DynamoDB operations for Git integration entities.

    Uses the boto3 DynamoDB *resource* (Table) API with dependency injection
    for testability.
    """

    def __init__(self, table_name: str, dynamodb_resource=None):
        resource = dynamodb_resource or boto3.resource("dynamodb")
        self._table = resource.Table(table_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_decimals(obj):
        """Recursively convert Decimal values to int or float."""
        if isinstance(obj, list):
            return [GitRepository._convert_decimals(i) for i in obj]
        if isinstance(obj, dict):
            return {k: GitRepository._convert_decimals(v) for k, v in obj.items()}
        if isinstance(obj, Decimal):
            if obj == int(obj):
                return int(obj)
            return float(obj)
        return obj

    @staticmethod
    def _encode_next_token(last_evaluated_key: dict | None) -> str | None:
        """Encode a DynamoDB LastEvaluatedKey as a base64 pagination token."""
        if not last_evaluated_key:
            return None
        return base64.b64encode(json.dumps(last_evaluated_key).encode()).decode()

    @staticmethod
    def _decode_next_token(token: str | None) -> dict | None:
        """Decode a base64 pagination token back to a DynamoDB ExclusiveStartKey."""
        if not token:
            return None
        return json.loads(base64.b64decode(token.encode()).decode())

    # ------------------------------------------------------------------
    # 1. Repository configs  (PK=GITREPO#{repoId}, SK=CONFIG)
    # ------------------------------------------------------------------

    def put_repo_config(self, repo_id: str, config: dict) -> dict:
        """Create or update a Git repository configuration.

        Args:
            repo_id: Unique repository identifier.
            config: Dict with name, url, provider, ssmTokenPath, status,
                    createdAt, createdBy and optional lastSyncAt.

        Returns:
            The stored item (with PK/SK included).
        """
        item = {
            "PK": f"GITREPO#{repo_id}",
            "SK": "CONFIG",
            **config,
        }
        self._table.put_item(Item=item)
        return self._convert_decimals(item)

    def get_repo_config(self, repo_id: str) -> dict | None:
        """Retrieve a single repository configuration by repoId.

        Returns:
            The item dict or None if not found.
        """
        response = self._table.get_item(
            Key={"PK": f"GITREPO#{repo_id}", "SK": "CONFIG"}
        )
        item = response.get("Item")
        if not item:
            return None
        return self._convert_decimals(item)

    def list_repo_configs(self) -> list[dict]:
        """List all Git repository configurations.

        Scans for items with SK=CONFIG and PK starting with GITREPO#.

        Note:
            Uses a full-table scan with filter. Acceptable while repo count is
            small (< ~100). If the footprint grows, introduce a GSI keyed on
            ``entityType`` to convert this into a Query.

        Returns:
            List of repository config dicts.
        """
        items: list[dict] = []
        kwargs: dict = {
            "FilterExpression": Key("SK").eq("CONFIG") & Key("PK").begins_with("GITREPO#"),
        }

        while True:
            response = self._table.scan(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key

        return self._convert_decimals(items)

    def delete_repo_config(self, repo_id: str) -> None:
        """Delete a repository configuration.

        Args:
            repo_id: The repository identifier to remove.
        """
        self._table.delete_item(
            Key={"PK": f"GITREPO#{repo_id}", "SK": "CONFIG"}
        )

    def update_repo_last_manual_sync(self, repo_id: str, timestamp: str) -> None:
        """Record the timestamp of the last manual sync trigger.

        Args:
            repo_id: Repository identifier.
            timestamp: ISO timestamp of the manual sync request.
        """
        self._table.update_item(
            Key={"PK": f"GITREPO#{repo_id}", "SK": "CONFIG"},
            UpdateExpression="SET lastManualSyncAt = :lms",
            ExpressionAttributeValues={":lms": timestamp},
        )

    def update_repo_sync_status(
        self, repo_id: str, status: str, last_sync_at: str | None = None
    ) -> None:
        """Update the sync status (and optionally lastSyncAt) of a repository.

        Args:
            repo_id: Repository identifier.
            status: New status value (e.g. SYNC_OK, SYNC_ERROR, SYNCING).
            last_sync_at: ISO timestamp of the last successful sync.
        """
        update_expr = "SET #st = :status"
        attr_names = {"#st": "status"}
        attr_values: dict = {":status": status}

        if last_sync_at:
            update_expr += ", lastSyncAt = :lsa"
            attr_values[":lsa"] = last_sync_at

        self._table.update_item(
            Key={"PK": f"GITREPO#{repo_id}", "SK": "CONFIG"},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )

    # ------------------------------------------------------------------
    # 2. User-Git mappings  (PK=USER#{userId}, SK=GITMAP#{provider})
    # ------------------------------------------------------------------

    def put_user_mapping(self, user_id: str, mapping: dict) -> tuple[dict, dict | None]:
        """Create or replace the user's mapping for a provider.

        The Mapping_Sort_Key is shaped as ``GITMAP#{provider}`` (one mapping
        per user per provider), so writing a new mapping for a provider the
        user is already mapped on replaces the prior mapping rather than
        creating a second item.

        Args:
            user_id: Kiro user identifier.
            mapping: Dict with provider, gitUsername, and optional gitEmail,
                     createdAt, createdBy.

        Returns:
            A ``(stored_item, previous_item)`` tuple. ``previous_item`` is
            None when there was no prior mapping for this user/provider,
            otherwise the decimal-converted item that was overwritten.
        """
        provider = mapping["provider"]
        item = {
            "PK": f"USER#{user_id}",
            "SK": mapping_sort_key(provider),
            **mapping,
        }
        response = self._table.put_item(Item=item, ReturnValues="ALL_OLD")
        previous_attributes = response.get("Attributes")
        previous_item = (
            self._convert_decimals(previous_attributes) if previous_attributes else None
        )
        return self._convert_decimals(item), previous_item

    def list_user_mappings(self, user_id: str) -> list[dict]:
        """List all Git mappings for a given Kiro user.

        Args:
            user_id: Kiro user identifier.

        Returns:
            List of mapping dicts.
        """
        key_condition = Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("GITMAP#")

        response = self._table.query(KeyConditionExpression=key_condition)
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = self._table.query(
                KeyConditionExpression=key_condition,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return self._convert_decimals(items)

    def delete_user_mapping(self, user_id: str, provider: str) -> None:
        """Delete the user's mapping for a provider.

        Args:
            user_id: Kiro user identifier.
            provider: Git provider name. The Mapping_Sort_Key is shaped as
                      ``GITMAP#{provider}``.
        """
        self._table.delete_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": mapping_sort_key(provider),
            }
        )

    def get_all_mappings_for_provider(self, provider: str) -> list[dict]:
        """Retrieve all user-Git mappings for a given provider.

        Scans the table for GITMAP# items matching the provider. Used by
        the sync pipeline to resolve Git authors to Kiro userIds.

        Note:
            Uses a full-table scan with filter. The sync pipeline calls this
            once per repo sync run, so cost scales with ``repos * users``.
            For large tenants, introduce a GSI on ``provider`` + ``gitUsername``
            to convert this into a Query.

        Args:
            provider: Git provider name (e.g. github, gitlab).

        Returns:
            List of mapping dicts.
        """
        items: list[dict] = []
        kwargs: dict = {
            "FilterExpression": (
                Attr("SK").eq(mapping_sort_key(provider))
                & Attr("provider").eq(provider)
            ),
        }

        while True:
            response = self._table.scan(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key

        return self._convert_decimals(items)

    # ------------------------------------------------------------------
    # 3. Git activities  (commits, PRs, reviews)
    # ------------------------------------------------------------------

    def batch_put_commits(self, user_id: str, commits: list[dict]) -> int:
        """Batch-write Git commit items for a user.

        Each commit dict must contain: date, commitHash, repoId, repository,
        message, filesChanged, linesAdded, linesRemoved, authorDate.

        Args:
            user_id: Kiro user identifier.
            commits: List of commit dicts.

        Returns:
            Number of items written.
        """
        pk = f"USER#{user_id}"
        with self._table.batch_writer() as batch:
            for commit in commits:
                item = {
                    "PK": pk,
                    "SK": f"GITCOMMIT#{commit['date']}#{commit['commitHash']}",
                    "repoId": commit["repoId"],
                    "repository": commit["repository"],
                    "message": commit.get("message", ""),
                    "filesChanged": commit.get("filesChanged", 0),
                    "linesAdded": commit.get("linesAdded", 0),
                    "linesRemoved": commit.get("linesRemoved", 0),
                    "authorDate": commit.get("authorDate", ""),
                }
                batch.put_item(Item=item)
        return len(commits)

    def batch_put_pull_requests(self, user_id: str, pull_requests: list[dict]) -> int:
        """Batch-write Git pull request items for a user.

        Each PR dict must contain: date, prId, repoId, repository, title,
        state, createdAt, and optional mergedAt, commitsCount, reviewsCount.

        Args:
            user_id: Kiro user identifier.
            pull_requests: List of PR dicts.

        Returns:
            Number of items written.
        """
        pk = f"USER#{user_id}"
        with self._table.batch_writer() as batch:
            for pr in pull_requests:
                item = {
                    "PK": pk,
                    "SK": f"GITPR#{pr['date']}#{pr['prId']}",
                    "prId": pr["prId"],
                    "repoId": pr["repoId"],
                    "repository": pr["repository"],
                    "title": pr.get("title", ""),
                    "state": pr.get("state", "open"),
                    "createdAt": pr.get("createdAt", ""),
                    "mergedAt": pr.get("mergedAt"),
                    "commitsCount": pr.get("commitsCount", 0),
                    "reviewsCount": pr.get("reviewsCount", 0),
                }
                batch.put_item(Item=item)
        return len(pull_requests)

    def batch_put_reviews(self, user_id: str, reviews: list[dict]) -> int:
        """Batch-write Git review items for a user.

        Each review dict must contain: date, reviewId, repoId, repository,
        prId, reviewType, createdAt.

        Args:
            user_id: Kiro user identifier.
            reviews: List of review dicts.

        Returns:
            Number of items written.
        """
        pk = f"USER#{user_id}"
        with self._table.batch_writer() as batch:
            for review in reviews:
                item = {
                    "PK": pk,
                    "SK": f"GITREVIEW#{review['date']}#{review['reviewId']}",
                    "repoId": review["repoId"],
                    "repository": review["repository"],
                    "prId": review.get("prId", ""),
                    "reviewType": review.get("reviewType", ""),
                    "createdAt": review.get("createdAt", ""),
                }
                batch.put_item(Item=item)
        return len(reviews)

    def query_commits(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        next_token: str | None = None,
    ) -> dict:
        """Query Git commits for a user with optional date range and pagination.

        Args:
            user_id: Kiro user identifier.
            start_date: Optional start date (inclusive) in YYYY-MM-DD format.
            end_date: Optional end date (inclusive) in YYYY-MM-DD format.
            limit: Maximum items per page.
            next_token: Pagination token from a previous call.

        Returns:
            Dict with ``items`` and ``nextToken``.
        """
        pk = f"USER#{user_id}"

        if start_date and end_date:
            key_condition = Key("PK").eq(pk) & Key("SK").between(
                f"GITCOMMIT#{start_date}", f"GITCOMMIT#{end_date}~"
            )
        else:
            key_condition = Key("PK").eq(pk) & Key("SK").begins_with("GITCOMMIT#")

        kwargs: dict = {
            "KeyConditionExpression": key_condition,
            "Limit": limit,
            "ScanIndexForward": False,
        }

        exclusive_start_key = self._decode_next_token(next_token)
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key

        response = self._table.query(**kwargs)
        items = self._convert_decimals(response.get("Items", []))
        result_next_token = self._encode_next_token(response.get("LastEvaluatedKey"))

        return {"items": items, "nextToken": result_next_token}

    def query_pull_requests(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        next_token: str | None = None,
    ) -> dict:
        """Query Git pull requests for a user with optional date range and pagination.

        Args:
            user_id: Kiro user identifier.
            start_date: Optional start date (inclusive) in YYYY-MM-DD format.
            end_date: Optional end date (inclusive) in YYYY-MM-DD format.
            limit: Maximum items per page.
            next_token: Pagination token from a previous call.

        Returns:
            Dict with ``items`` and ``nextToken``.
        """
        pk = f"USER#{user_id}"

        if start_date and end_date:
            key_condition = Key("PK").eq(pk) & Key("SK").between(
                f"GITPR#{start_date}", f"GITPR#{end_date}~"
            )
        else:
            key_condition = Key("PK").eq(pk) & Key("SK").begins_with("GITPR#")

        kwargs: dict = {
            "KeyConditionExpression": key_condition,
            "Limit": limit,
            "ScanIndexForward": False,
        }

        exclusive_start_key = self._decode_next_token(next_token)
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key

        response = self._table.query(**kwargs)
        items = self._convert_decimals(response.get("Items", []))
        result_next_token = self._encode_next_token(response.get("LastEvaluatedKey"))

        return {"items": items, "nextToken": result_next_token}

    def query_reviews(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        next_token: str | None = None,
    ) -> dict:
        """Query Git reviews for a user with optional date range and pagination.

        Args:
            user_id: Kiro user identifier.
            start_date: Optional start date (inclusive) in YYYY-MM-DD format.
            end_date: Optional end date (inclusive) in YYYY-MM-DD format.
            limit: Maximum items per page.
            next_token: Pagination token from a previous call.

        Returns:
            Dict with ``items`` and ``nextToken``.
        """
        pk = f"USER#{user_id}"

        if start_date and end_date:
            key_condition = Key("PK").eq(pk) & Key("SK").between(
                f"GITREVIEW#{start_date}", f"GITREVIEW#{end_date}~"
            )
        else:
            key_condition = Key("PK").eq(pk) & Key("SK").begins_with("GITREVIEW#")

        kwargs: dict = {
            "KeyConditionExpression": key_condition,
            "Limit": limit,
            "ScanIndexForward": False,
        }

        exclusive_start_key = self._decode_next_token(next_token)
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key

        response = self._table.query(**kwargs)
        items = self._convert_decimals(response.get("Items", []))
        result_next_token = self._encode_next_token(response.get("LastEvaluatedKey"))

        return {"items": items, "nextToken": result_next_token}

    # ------------------------------------------------------------------
    # 4. Sync stats  (PK=GITREPO#{repoId}, SK=SYNC#{date})
    # ------------------------------------------------------------------

    def put_sync_stats(self, repo_id: str, date: str, stats: dict) -> dict:
        """Record sync statistics for a repository run.

        Args:
            repo_id: Repository identifier.
            date: ISO date string for the sync run.
            stats: Dict with commitsCount, prsCount, reviewsCount,
                   duration, status.

        Returns:
            The stored item.
        """
        item = {
            "PK": f"GITREPO#{repo_id}",
            "SK": f"SYNC#{date}",
            **stats,
        }
        self._table.put_item(Item=item)
        return self._convert_decimals(item)
