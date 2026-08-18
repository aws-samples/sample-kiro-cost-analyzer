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

try:
    from git_shared.git_repository import GitRepository
except ImportError:
    from layers.shared.git_shared.git_repository import GitRepository
try:
    from git_shared.git_providers import SUPPORTED_PROVIDERS
except ImportError:
    from layers.shared.git_shared.git_providers import SUPPORTED_PROVIDERS
from shared.structured_logger import StructuredLogger


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

    stored, previous = repo.put_user_mapping(user_id, mapping)
    replaced = previous is not None
    previous_git_username = previous.get("gitUsername") if previous else None

    logger.info(
        "Git user mapping created",
        userId=user_id,
        provider=provider,
        gitUsername=git_username,
        createdBy=created_by,
        replaced=replaced,
        previousGitUsername=previous_git_username,
    )

    return {
        "userId": user_id,
        "provider": provider,
        "gitUsername": git_username,
        "createdAt": created_at,
        "replaced": replaced,
        "previousGitUsername": previous_git_username,
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
    dynamodb_resource=None,
) -> dict:
    """Handle DELETE /api/git/mappings/{userId}/{provider}.

    Args:
        user_id: Kiro user identifier.
        provider: Git provider name.
        dynamodb_resource: Optional boto3 DynamoDB resource (for testing).

    Returns:
        Success dict. Always reports ``deleted: True`` — a delete of an
        absent mapping succeeds the same as a delete of an existing one,
        which is what makes repeated deletion idempotent.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = GitRepository(table_name, dynamodb_resource=dynamodb_resource)

    # Delete the mapping (DynamoDB delete is idempotent)
    repo.delete_user_mapping(user_id, provider)

    logger.info(
        "Git user mapping deleted",
        userId=user_id,
        provider=provider,
    )

    return {
        "userId": user_id,
        "provider": provider,
        "deleted": True,
    }


def handle_list_all_mappings(
    query_params: dict,
    dynamodb_resource=None,
) -> dict:
    """Handle GET /api/git/mappings — paginated cross-user mapping listing.

    Args:
        query_params: Query string parameters. Supports ``limit`` (default
            50, clamped to [1, 100]) and ``lastKey`` (opaque base64 token
            from a prior response).
        dynamodb_resource: Optional boto3 DynamoDB resource (for testing).

    Returns:
        Dict with ``mappings`` list and, when more results exist, an opaque
        ``lastKey`` pagination token. Malformed tokens return a 400 error
        dict.
    """
    import base64
    import json as _json

    params = query_params or {}

    try:
        limit = int(params.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 100))

    last_key = None
    token = params.get("lastKey")
    if token:
        try:
            last_key = _json.loads(base64.b64decode(token).decode("utf-8"))
            if not isinstance(last_key, dict) or "PK" not in last_key or "SK" not in last_key:
                raise ValueError("token missing key fields")
        except Exception:
            return {
                "error": "ValidationError",
                "message": "Invalid lastKey pagination token.",
                "_status_code": 400,
            }

    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = GitRepository(table_name, dynamodb_resource=dynamodb_resource)

    items, next_key = repo.list_all_mappings(limit=limit, last_key=last_key)

    mappings = []
    for item in items:
        pk = item.get("PK", "")
        mappings.append({
            "userId": pk.replace("USER#", "") if pk.startswith("USER#") else "",
            "provider": item.get("provider", ""),
            "gitUsername": item.get("gitUsername", ""),
            "createdAt": item.get("createdAt", ""),
        })

    result: dict = {"mappings": mappings}
    if next_key:
        result["lastKey"] = base64.b64encode(
            _json.dumps({"PK": next_key["PK"], "SK": next_key["SK"]}).encode("utf-8")
        ).decode("ascii")

    logger.info("Listed all git mappings", count=len(mappings), hasMore=bool(next_key))
    return result
