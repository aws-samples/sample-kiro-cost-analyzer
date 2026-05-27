"""Handler for Git user mapping CRUD operations.

Provides functions for creating, listing and deleting user-to-Git
mappings. Each mapping associates a Kiro userId with a Git provider
username, enabling the sync pipeline to attribute Git activities to
the correct Kiro user.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from repository.git_repository import GitRepository
from shared.structured_logger import StructuredLogger

SUPPORTED_PROVIDERS = frozenset({"github"})


logger = StructuredLogger("git-mapping-handler")


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _user_exists(user_id: str, dynamodb_resource=None) -> bool:
    """Check whether a Kiro user exists by querying for any USER# items.

    Looks for STATS#DAILY# records which are the most common user items.
    Falls back to checking any SK starting with STATS# or PROMPT#.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    resource = dynamodb_resource or boto3.resource("dynamodb")
    table = resource.Table(table_name)

    # Quick check: look for any item under this user's partition
    response = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}"),
        Limit=1,
        Select="COUNT",
    )
    return response.get("Count", 0) > 0


# ------------------------------------------------------------------
# Public handler functions
# ------------------------------------------------------------------


def handle_create_mapping(
    body: dict,
    claims: dict,
    dynamodb_resource=None,
) -> dict:
    """Handle POST /api/git/mappings — create a new user-Git mapping.

    Validates that the userId exists in the system, then persists the
    mapping in DynamoDB.

    Args:
        body: Parsed JSON request body with userId, provider, gitUsername.
        claims: JWT claims dict with userId and groups.
        dynamodb_resource: Optional boto3 DynamoDB resource (for testing).

    Returns:
        Response dict with the created mapping data, or an error dict
        with ``_status_code`` set.
    """
    user_id = (body.get("userId") or "").strip()
    provider = (body.get("provider") or "").strip().lower()
    git_username = (body.get("gitUsername") or "").strip()

    # --- Field validation ---
    missing = []
    if not user_id:
        missing.append("userId")
    if not provider:
        missing.append("provider")
    if not git_username:
        missing.append("gitUsername")
    if missing:
        return {
            "error": "ValidationError",
            "message": f"Missing required fields: {', '.join(missing)}",
            "_status_code": 400,
        }

    if provider not in SUPPORTED_PROVIDERS:
        return {
            "error": "ValidationError",
            "message": f"Unsupported provider: {provider}. Valid providers: {', '.join(sorted(SUPPORTED_PROVIDERS))}",
            "_status_code": 400,
        }

    # --- Validate that the userId exists in the system ---
    if not _user_exists(user_id, dynamodb_resource=dynamodb_resource):
        logger.warning(
            "Mapping creation failed — user not found",
            userId=user_id,
            provider=provider,
            gitUsername=git_username,
        )
        return {
            "error": "NotFound",
            "message": f"Kiro user not found: {user_id}",
            "_status_code": 404,
        }

    # --- Persist mapping in DynamoDB ---
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = GitRepository(table_name, dynamodb_resource=dynamodb_resource)

    created_at = _now_iso()
    created_by = claims.get("userId", "")

    mapping = {
        "provider": provider,
        "gitUsername": git_username,
        "createdAt": created_at,
        "createdBy": created_by,
    }

    repo.put_user_mapping(user_id, mapping)

    logger.info(
        "Git user mapping created",
        userId=user_id,
        provider=provider,
        gitUsername=git_username,
        createdBy=created_by,
    )

    return {
        "userId": user_id,
        "provider": provider,
        "gitUsername": git_username,
        "createdAt": created_at,
        "_status_code": 201,
    }


def handle_list_mappings(
    user_id: str,
    dynamodb_resource=None,
) -> dict:
    """Handle GET /api/git/mappings/{userId} — list mappings for a user.

    Args:
        user_id: Kiro user identifier.
        dynamodb_resource: Optional boto3 DynamoDB resource (for testing).

    Returns:
        Dict with ``mappings`` list.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = GitRepository(table_name, dynamodb_resource=dynamodb_resource)

    items = repo.list_user_mappings(user_id)

    mappings = []
    for item in items:
        mappings.append({
            "userId": user_id,
            "provider": item.get("provider", ""),
            "gitUsername": item.get("gitUsername", ""),
            "createdAt": item.get("createdAt", ""),
        })

    logger.info(
        "Listed Git user mappings",
        userId=user_id,
        count=len(mappings),
    )

    return {"mappings": mappings}


def handle_delete_mapping(
    user_id: str,
    provider: str,
    git_username: str,
    dynamodb_resource=None,
) -> dict:
    """Handle DELETE /api/git/mappings/{userId}/{provider}/{gitUsername}.

    Args:
        user_id: Kiro user identifier.
        provider: Git provider name.
        git_username: Git username to unmap.
        dynamodb_resource: Optional boto3 DynamoDB resource (for testing).

    Returns:
        Success dict, or error dict with ``_status_code``.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = GitRepository(table_name, dynamodb_resource=dynamodb_resource)

    # Delete the mapping (DynamoDB delete is idempotent)
    repo.delete_user_mapping(user_id, provider, git_username)

    logger.info(
        "Git user mapping deleted",
        userId=user_id,
        provider=provider,
        gitUsername=git_username,
    )

    return {
        "message": f"Mapping {provider}/{git_username} removed for user {user_id}",
    }
