"""AWS Lambda Backend entry point — Amazon API Gateway request router.

Routes incoming API Gateway requests to the appropriate handler based on
HTTP method and path. Extracts JWT claims for authentication and enforces
admin-only access on restricted endpoints.
"""

import json
import logging
import os
import re

import boto3
from botocore.exceptions import ClientError

from handlers import (
    account_usage_handler,
    agent_correlation_handler,
    config_handler,
    engagement_handler,
    etl_executions_handler,
    etl_trigger_handler,
    export_handler,
    git_mapping_handler,
    git_repo_handler,
    git_token_validation_handler,
    prompts_handler,
    recommendation_handler,
    usage_handler,
    user_details_handler,
    users_handler,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def _get_allowed_origin() -> str:
    """Return the allowed CORS origin from environment or default to restrictive."""
    return os.environ.get("ALLOWED_ORIGIN", "https://localhost:5173")


CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": _get_allowed_origin(),
}

ADMIN_GROUP = "Admins"

# Pattern to extract userId from DELETE /api/users/{userId}
_DELETE_USER_PATTERN = re.compile(r"^/api/users/(.+)$")
_USER_DETAILS_PATTERN = re.compile(r"^/api/usage/(.+)/details$")
_PRODUCTIVITY_CORRELATION_PATTERN = re.compile(r"^/api/productivity/([^/]+)/correlation$")

# Prompts endpoint patterns
_PROMPT_DETAIL_PATTERN = re.compile(r"^/api/prompts/([^/]+)$")

# Git endpoint patterns
_GIT_REPO_SYNC_PATTERN = re.compile(r"^/api/git/repos/([^/]+)/sync$")
_GIT_REPO_VALIDATE_TOKEN_PATTERN = re.compile(r"^/api/git/repos/([^/]+)/validate-token$")
_GIT_REPO_VALIDATE_TOKEN_PATH = "/api/git/repos/validate-token"
_GIT_REPO_DETAIL_PATTERN = re.compile(r"^/api/git/repos/([^/]+)$")
_GIT_MAPPING_DELETE_PATTERN = re.compile(r"^/api/git/mappings/([^/]+)/([^/]+)$")
_GIT_MAPPING_USER_PATTERN = re.compile(r"^/api/git/mappings/([^/]+)$")

_THROTTLE_ERROR_CODES = frozenset({
    "ProvisionedThroughputExceededException",
    "ThrottlingException",
})


def _build_response(status_code: int, body: dict | str, content_type: str = "application/json") -> dict:
    """Build an API Gateway proxy response."""
    headers = {**CORS_HEADERS, "Content-Type": content_type}
    if isinstance(body, str):
        return {"statusCode": status_code, "headers": headers, "body": body}
    return {"statusCode": status_code, "headers": headers, "body": json.dumps(body)}


def _extract_claims(event: dict) -> dict:
    """Extract JWT claims from the API Gateway event.

    Returns a dict with ``userId`` (Cognito sub), ``groups``, ``username``,
    ``email``, and ``kiroUserId`` (custom attribute from Cognito).
    """
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    )
    user_id = claims.get("sub") or claims.get("cognito:username", "")
    groups_raw = claims.get("cognito:groups", "")
    groups = [g.strip() for g in groups_raw.split(",") if g.strip()] if groups_raw else []
    return {
        "userId": user_id,
        "groups": groups,
        "username": claims.get("cognito:username", user_id),
        "email": claims.get("email", ""),
        "kiroUserId": claims.get("custom:kiro_user_id", ""),
    }


def _is_admin(claims: dict) -> bool:
    """Check whether the caller belongs to the Admins group."""
    return ADMIN_GROUP in claims.get("groups", [])


def _resolve_self_kiro_user_id(query_params: dict | None, claims: dict) -> dict:
    """Translate a self-lookup ``userId`` from Cognito sub to Kiro userId.

    PROMPT# items in DynamoDB are keyed by the Kiro userId (Identity Center
    UUID), but the frontend routes use the Cognito sub in the URL path
    (``/user/{sub}``) when an admin opens their own profile. Without
    translation, ``GET /api/prompts?userId={cognito-sub}`` returns an empty
    list because no PROMPT# items exist under that PK.

    When the requested ``userId`` equals the caller's Cognito sub and the
    caller has a ``custom:kiro_user_id`` claim, this helper returns a copy
    of *query_params* with ``userId`` swapped to the Kiro userId. All other
    cases (different userId, missing kiro id, missing query params) return
    the input unchanged.

    The substitution is safe because the new value is read from the JWT
    claims, which are signed by Cognito and validated by the API Gateway
    authorizer. A caller cannot forge another user's mapping.

    Args:
        query_params: The original query string parameters dict (or None).
        claims: The JWT claims dict from ``_extract_claims``.

    Returns:
        The query_params dict, possibly with ``userId`` rewritten.
    """
    if not query_params:
        return query_params or {}
    requested = query_params.get("userId")
    caller_sub = claims.get("userId")
    kiro_self = claims.get("kiroUserId")
    if requested and caller_sub and kiro_self and requested == caller_sub:
        return {**query_params, "userId": kiro_self}
    return query_params


def _resolve_kiro_user_id(claims: dict) -> str | None:
    """Resolve the Kiro userId (IAM Identity Center) for a non-admin caller.

    Reads the ``custom:kiro_user_id`` attribute from the JWT claims, which
    is set by an admin when linking the Cognito user to their Kiro identity.

    Returns the Kiro userId if set, or None.
    """
    return claims.get("kiroUserId") or None


def _list_kiro_users() -> dict:
    """List all Kiro users from the UserNames table.

    Returns a list of {userId, displayName, userName} for the autocomplete
    in the admin user creation flow.
    """
    table_name = os.environ.get("USER_NAMES_TABLE", "")
    if not table_name:
        return {"users": []}

    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        response = table.scan(
            ProjectionExpression="userId, displayName, userName",
        )
        items = response.get("Items", [])
        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = table.scan(
                ProjectionExpression="userId, displayName, userName",
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        users = [
            {
                "userId": item.get("userId", ""),
                "displayName": item.get("displayName", ""),
                "userName": item.get("userName", ""),
            }
            for item in items
        ]
        users.sort(key=lambda u: u.get("displayName", "").lower())
        return {"users": users}
    except Exception:
        return {"users": []}


def lambda_handler(event: dict, context) -> dict:
    """Main Lambda entry point for the Backend API.

    Parses the API Gateway proxy event, routes to the correct handler,
    and returns a well-formed proxy response.
    """
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")
    query_params = event.get("queryStringParameters") or {}
    body_raw = event.get("body")

    body = {}
    if body_raw:
        try:
            body = json.loads(body_raw)
        except (json.JSONDecodeError, TypeError):
            return _build_response(400, {"error": "InvalidBody", "message": "Request body is not valid JSON"})

    claims = _extract_claims(event)

    try:
        return _route(http_method, path, query_params, body, claims)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in _THROTTLE_ERROR_CODES:
            logger.error("DynamoDB throttling error: %s", exc)
            return _build_response(503, {
                "error": "ServiceUnavailable",
                "message": "Service temporarily unavailable. Please try again in a few moments.",
            })
        logger.exception("AWS ClientError: %s", exc)
        return _build_response(500, {
            "error": "InternalError",
            "message": "Internal server error.",
        })
    except Exception as exc:
        logger.exception("Unhandled error: %s", exc)
        return _build_response(500, {
            "error": "InternalError",
            "message": "Internal server error.",
        })


def _route(http_method: str, path: str, query_params: dict, body: dict, claims: dict) -> dict:
    """Route the request to the appropriate handler."""

    caller_user_id = claims.get("userId", "")

    # For non-admins, resolve the Kiro userId (Identity Center) from email.
    # This bridges the gap between Cognito sub and the userId used in DynamoDB.
    kiro_user_id = None
    if not _is_admin(claims):
        kiro_user_id = _resolve_kiro_user_id(claims)

    # GET /api/me — returns the caller's resolved Kiro userId
    if http_method == "GET" and path == "/api/me":
        return _build_response(200, {
            "cognitoSub": caller_user_id,
            "kiroUserId": kiro_user_id,
            "email": claims.get("email", ""),
            "isAdmin": _is_admin(claims),
        })

    # GET /api/kiro-users — list Kiro users from UserNames table (admin-only)
    if http_method == "GET" and path == "/api/kiro-users":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = _list_kiro_users()
        return _build_response(200, result)

    # --- Public endpoints (any authenticated user, with user-scoping for non-admins) ---

    if http_method == "GET" and path == "/api/usage":
        # Non-admins can only see their own usage summary
        if not _is_admin(claims):
            if not kiro_user_id:
                return _build_response(200, {
                    "summary": {"totalUsers": 0, "totalCredits": 0, "totalOverageCredits": 0, "averageCreditsPerUser": 0},
                    "users": [],
                    "period": {},
                })
            query_params = {**query_params, "userId": kiro_user_id}
        result = usage_handler.handle_usage(query_params)
        return _build_response(200, result)

    if http_method == "GET" and path == "/api/usage/engagement":
        # Engagement is aggregate data — restrict to admins
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = engagement_handler.handle_engagement(query_params)
        return _build_response(200, result)

    if http_method == "GET" and path == "/api/usage/account":
        # Account-level usage is aggregate — restrict to admins
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = account_usage_handler.handle_account_usage(query_params)
        return _build_response(200, result)

    if http_method == "GET" and path == "/api/usage/export":
        # Export is aggregate — restrict to admins
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = export_handler.handle_export(query_params)
        content_type = result.get("contentType", "application/json")
        return _build_response(result.get("statusCode", 200), result["body"], content_type)

    if http_method == "GET":
        match = _USER_DETAILS_PATTERN.match(path)
        if match:
            user_id = match.group(1)
            # User-scoping: non-admins can only view their own details
            # Allow access if the path userId matches either Cognito sub or Kiro userId
            if not _is_admin(claims) and user_id != caller_user_id and user_id != kiro_user_id:
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "You can only view your own usage details",
                })
            result = user_details_handler.handle_user_details(user_id, query_params)
            status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
            return _build_response(status_code, result)

    if http_method == "GET" and path == "/api/config":
        result = config_handler.handle_get_config()
        return _build_response(200, result)

    if http_method == "GET" and path == "/api/config/schedule":
        result = config_handler.handle_get_schedule()
        return _build_response(200, result)

    if http_method == "GET" and path == "/api/config/engagement-thresholds":
        result = engagement_handler.handle_get_thresholds()
        return _build_response(200, result)

    # GET /api/productivity/{userId}/correlation — agent-based analysis
    if http_method == "GET":
        match = _PRODUCTIVITY_CORRELATION_PATTERN.match(path)
        if match:
            user_id = match.group(1)
            # User-scoping: non-admins can only view their own correlation
            # Allow if path userId matches either Cognito sub or Kiro userId
            if not _is_admin(claims) and user_id != caller_user_id and user_id != kiro_user_id:
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "You can only view your own productivity data",
                })
            result = agent_correlation_handler.handle_agent_correlation(
                user_id, query_params, claims,
            )
            status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
            return _build_response(status_code, result)

    # --- Admin-only endpoints ---

    if http_method == "PUT" and path == "/api/config/identity-store-id":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = config_handler.handle_put_config_identity_store_id(body)
        return _build_response(200, result)

    if http_method == "PUT" and path == "/api/config/source-bucket-role-arn":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = config_handler.handle_put_config_source_bucket_role_arn(body)
        return _build_response(200, result)

    if http_method == "PUT" and path == "/api/config/identity-store-role-arn":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Admin access required",
            })
        result = config_handler.handle_put_config_identity_store_role_arn(body)
        return _build_response(200, result)

    if http_method == "PUT" and path == "/api/config/engagement-thresholds":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = engagement_handler.handle_put_thresholds(body)
        return _build_response(200, result)

    # GET /api/recommendations/tier-optimization — admin only
    if http_method == "GET" and path == "/api/recommendations/tier-optimization":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = recommendation_handler.handle_get_recommendations(query_params)
        status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
        return _build_response(status_code, result)

    # GET /api/config/tier-pricing — admin only
    if http_method == "GET" and path == "/api/config/tier-pricing":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = recommendation_handler.handle_get_tier_pricing()
        status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
        return _build_response(status_code, result)

    # PUT /api/config/tier-pricing — admin only
    if http_method == "PUT" and path == "/api/config/tier-pricing":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = recommendation_handler.handle_put_tier_pricing(body)
        status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
        return _build_response(status_code, result)

    # PUT /api/config/prompt-history-enabled — admin only
    if http_method == "PUT" and path == "/api/config/prompt-history-enabled":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = config_handler.handle_put_config_prompt_history_enabled(body)
        return _build_response(200, result)

    # GET /api/prompts — admin only, paginated prompt metadata list.
    # Self-lookup translation: PROMPT# items in DynamoDB are keyed by the
    # Kiro userId (Identity Center). When an admin asks for their own
    # prompts the URL carries their Cognito sub (the path param in
    # /user/{id}). If the requested userId equals the caller's Cognito sub
    # and the caller has a custom:kiro_user_id claim, swap to that value
    # before delegating. Substitution is driven entirely by the JWT, which
    # is signed by Cognito and cannot be forged. No new authorization
    # surface — the route stays admin-only and admins can already query
    # any userId directly.
    if http_method == "GET" and path == "/api/prompts":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        query_params = _resolve_self_kiro_user_id(query_params, claims)
        result = prompts_handler.handle_list_prompts(query_params)
        return _build_response(200, result)

    # GET /api/prompts/{requestId} — admin only, full prompt detail.
    # Same self-lookup translation as /api/prompts above.
    if http_method == "GET":
        match = _PROMPT_DETAIL_PATTERN.match(path)
        if match:
            if not _is_admin(claims):
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "Access restricted to administrators",
                })
            request_id = match.group(1)
            query_params = _resolve_self_kiro_user_id(query_params, claims)
            result = prompts_handler.handle_get_prompt_detail(request_id, query_params)
            return _build_response(200, result)

    if http_method == "POST" and path == "/api/etl/trigger":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = etl_trigger_handler.handle_etl_trigger()
        return _build_response(200, result)

    if http_method == "GET" and path == "/api/etl/executions":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = etl_executions_handler.handle_etl_executions(query_params)
        return _build_response(200, result)

    if http_method == "GET" and path == "/api/users":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = users_handler.handle_list_users()
        return _build_response(200, result)

    if http_method == "POST" and path == "/api/users":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = users_handler.handle_create_user(body)
        return _build_response(200, result)

    # DELETE /api/users/{userId}
    if http_method == "DELETE":
        match = _DELETE_USER_PATTERN.match(path)
        if match:
            if not _is_admin(claims):
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "Access restricted to administrators",
                })
            target_user_id = match.group(1)
            caller_username = claims.get("username", claims.get("userId", ""))
            result = users_handler.handle_delete_user(target_user_id, caller_username)
            return _build_response(200, result)

    # PUT /api/users/{userId} — toggle admin role
    if http_method == "PUT":
        match = _DELETE_USER_PATTERN.match(path)
        if match:
            if not _is_admin(claims):
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "Access restricted to administrators",
                })
            target_user_id = match.group(1)
            caller_username = claims.get("username", claims.get("userId", ""))
            result = users_handler.handle_toggle_role(target_user_id, body, caller_username)
            return _build_response(200, result)

    # --- Git endpoints: repos and mappings (Admin-only) ---

    # POST /api/git/repos — create repository
    if http_method == "POST" and path == "/api/git/repos":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = git_repo_handler.handle_create_repo(body, claims)
        status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
        return _build_response(status_code, result)

    # GET /api/git/repos — list repositories
    if http_method == "GET" and path == "/api/git/repos":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = git_repo_handler.handle_list_repos()
        return _build_response(200, result)

    # POST /api/git/repos/validate-token — validate a token before it is saved.
    # Must be matched before the {repoId} patterns below so "validate-token" is
    # never parsed as a repository id.
    if http_method == "POST" and path == _GIT_REPO_VALIDATE_TOKEN_PATH:
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = git_token_validation_handler.handle_validate_token(body)
        status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
        return _build_response(status_code, result)

    # POST /api/git/repos/{repoId}/validate-token — validate the stored token
    if http_method == "POST":
        match = _GIT_REPO_VALIDATE_TOKEN_PATTERN.match(path)
        if match:
            if not _is_admin(claims):
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "Access restricted to administrators",
                })
            repo_id = match.group(1)
            result = git_token_validation_handler.handle_validate_stored_token(repo_id)
            status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
            return _build_response(status_code, result)

    # POST /api/git/repos/{repoId}/sync — manual sync (must match before DELETE)
    if http_method == "POST":
        match = _GIT_REPO_SYNC_PATTERN.match(path)
        if match:
            if not _is_admin(claims):
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "Access restricted to administrators",
                })
            repo_id = match.group(1)
            result = git_repo_handler.handle_manual_sync(repo_id)
            status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
            return _build_response(status_code, result)

    # DELETE /api/git/repos/{repoId} — delete repository
    if http_method == "DELETE":
        match = _GIT_REPO_DETAIL_PATTERN.match(path)
        if match:
            if not _is_admin(claims):
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "Access restricted to administrators",
                })
            repo_id = match.group(1)
            result = git_repo_handler.handle_delete_repo(repo_id)
            status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
            return _build_response(status_code, result)

    # PATCH /api/git/repos/{repoId} — partial update / token rotation
    if http_method == "PATCH":
        match = _GIT_REPO_DETAIL_PATTERN.match(path)
        if match:
            if not _is_admin(claims):
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "Access restricted to administrators",
                })
            repo_id = match.group(1)
            result = git_repo_handler.handle_update_repo(repo_id, body, claims)
            status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
            return _build_response(status_code, result)

    # POST /api/git/mappings — create mapping
    if http_method == "POST" and path == "/api/git/mappings":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = git_mapping_handler.handle_create_mapping(body, claims)
        status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
        return _build_response(status_code, result)

    # GET /api/git/mappings — list all mappings (paginated)
    if http_method == "GET" and path == "/api/git/mappings":
        if not _is_admin(claims):
            return _build_response(403, {
                "error": "Forbidden",
                "message": "Access restricted to administrators",
            })
        result = git_mapping_handler.handle_list_all_mappings(query_params)
        status_code = result.pop("_status_code", 200) if isinstance(result, dict) else 200
        return _build_response(status_code, result)

    # GET /api/git/mappings/{userId} — list mappings for user
    if http_method == "GET":
        match = _GIT_MAPPING_USER_PATTERN.match(path)
        if match:
            if not _is_admin(claims):
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "Access restricted to administrators",
                })
            user_id = match.group(1)
            result = git_mapping_handler.handle_list_mappings(user_id)
            return _build_response(200, result)

    # DELETE /api/git/mappings/{userId}/{provider}
    if http_method == "DELETE":
        match = _GIT_MAPPING_DELETE_PATTERN.match(path)
        if match:
            if not _is_admin(claims):
                return _build_response(403, {
                    "error": "Forbidden",
                    "message": "Access restricted to administrators",
                })
            user_id = match.group(1)
            provider = match.group(2)
            result = git_mapping_handler.handle_delete_mapping(user_id, provider)
            return _build_response(200, result)

    # --- Unknown route ---
    return _build_response(404, {
        "error": "NotFound",
        "message": f"Route not found: {http_method} {path}",
    })
