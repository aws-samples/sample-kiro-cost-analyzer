"""User name resolver — resolves userIds to display names via IAM Identity Center with DynamoDB cache."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import boto3

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS = 7


@dataclass
class UserNameEntry:
    """Cached mapping of userId to display name and user name."""

    userId: str
    displayName: str
    userName: str
    resolvedAt: str  # ISO 8601


def resolve_user_names(
    user_ids: set[str],
    identity_store_id: str,
    table_name: str,
    dynamodb=None,
    identity_client=None,
) -> dict[str, tuple[str, str]]:
    """Resolve a batch of userIds to (displayName, userName).

    1. Query DynamoDB cache for each userId
    2. If cache entry exists and resolvedAt < 7 days old, use cached value
    3. If cache expired or absent, call identitystore:DescribeUser
    4. Save result to DynamoDB cache with resolvedAt = now
    5. If API call fails for a userId, log warning and return ("", "") for that userId

    Cross-account contract for ``identity_client``:
        * When ``identity_client is None`` (default), a single-account
          ``boto3.client("identitystore")`` is built internally using the
          Lambda's own IAM role credentials. This preserves the historical
          single-account behavior (Requirement 4.4 — single-account fallback).
        * When ``identity_client is not None``, the provided client is used
          verbatim for every ``identitystore:DescribeUser`` call — no
          transformation, no re-wrapping, and no fallback to ``boto3.client``.
          This is the cross-account injection seam used by the Parse Lambda
          after building a client via
          :func:`etl.sts_session.get_identity_store_client` from the assumed
          ``IdentityStoreRoleArn`` role (Requirement 4.2 — cross-account
          resolver uses the injected client).
        * The DynamoDB cache in ``UserNamesTable`` uses ``userId`` as the sole
          partition key in both modes — no account identifier or role ARN is
          embedded in the key — so cache entries are reusable across a mode
          toggle without rebuild (Requirement 5.1 — cache key stability).

    Resolution failures (including ``AccessDenied`` from the Identity Store
    client) are logged and swallowed per userId with a tolerant return of
    ``("", "")`` so ETL processing continues (Requirement 7.5).

    Args:
        user_ids: Set of IAM Identity Center userIds to resolve.
        identity_store_id: Identity Store instance ID (e.g. ``d-1234567890``).
        table_name: Name of the ``UserNamesTable`` DynamoDB table.
        dynamodb: Optional boto3 DynamoDB resource for dependency injection.
        identity_client: Optional ``identitystore`` boto3 client. See the
            cross-account contract above.

    Returns:
        dict mapping userId to (displayName, userName). Unresolvable userIds
        map to ``("", "")``.
    """
    if dynamodb is None:
        dynamodb = boto3.resource("dynamodb")
    if identity_client is None:
        identity_client = boto3.client("identitystore")

    table = dynamodb.Table(table_name)
    result: dict[str, tuple[str, str]] = {}
    now = datetime.now(timezone.utc)
    ttl_threshold = now - timedelta(days=CACHE_TTL_DAYS)

    for user_id in user_ids:
        # Check cache
        cached = _get_cached_entry(table, user_id)
        if cached is not None and _is_cache_valid(cached, ttl_threshold):
            result[user_id] = (cached.displayName, cached.userName)
            continue

        # Cache miss or expired — call Identity Center
        try:
            response = identity_client.describe_user(
                IdentityStoreId=identity_store_id,
                UserId=user_id,
            )
            display_name = response.get("DisplayName", "")
            user_name = response.get("UserName", "")

            # Save to cache
            _save_to_cache(table, user_id, display_name, user_name, now)
            result[user_id] = (display_name, user_name)
        except Exception as exc:
            error_type = type(exc).__name__
            if "AccessDenied" in error_type or "AccessDenied" in str(exc):
                # Cross-account-aware hint: when IDC is in a different AWS
                # account, AccessDenied almost always means the assumed
                # Identity_Store_Role is missing identitystore:DescribeUser
                # (Requirement 8.2).
                # exc_info intentionally False: the traceback can expose
                # Identity Store API response details beyond errorType.
                logger.warning(
                    "Access denied resolving user name via Identity Store "
                    "for userId=%s (errorType=%s). "
                    "Check the Identity_Store_Role permissions "
                    "(identitystore:DescribeUser) in the IDC account.",
                    user_id,
                    error_type,
                    exc_info=False,
                )
            else:
                logger.warning(
                    "Failed to resolve user name for userId=%s", user_id, exc_info=False
                )
            # Tolerant fallback — Requirement 7.5.
            result[user_id] = ("", "")

    return result


def _get_cached_entry(table, user_id: str) -> UserNameEntry | None:
    """Retrieve a cached entry from DynamoDB, or None if not found."""
    try:
        response = table.get_item(Key={"userId": user_id})
        item = response.get("Item")
        if item is None:
            return None
        return UserNameEntry(
            userId=item["userId"],
            displayName=item.get("displayName", ""),
            userName=item.get("userName", ""),
            resolvedAt=item.get("resolvedAt", ""),
        )
    except Exception:
        # exc_info intentionally False: the traceback can echo DynamoDB
        # table ARNs or other request/infrastructure details.
        logger.warning("Failed to read cache for userId=%s", user_id, exc_info=False)
        return None


def _is_cache_valid(entry: UserNameEntry, ttl_threshold: datetime) -> bool:
    """Check whether a cache entry is still within the TTL window."""
    if not entry.resolvedAt:
        return False
    try:
        resolved_at = datetime.fromisoformat(entry.resolvedAt)
        return resolved_at > ttl_threshold
    except (ValueError, TypeError):
        return False


def _save_to_cache(
    table, user_id: str, display_name: str, user_name: str, now: datetime
) -> None:
    """Write a resolved entry to the DynamoDB cache."""
    try:
        table.put_item(
            Item={
                "userId": user_id,
                "displayName": display_name,
                "userName": user_name,
                "resolvedAt": now.isoformat(),
            }
        )
    except Exception:
        # exc_info intentionally False: the traceback can echo DynamoDB
        # table ARNs or other request/infrastructure details.
        logger.warning("Failed to write cache for userId=%s", user_id, exc_info=False)
