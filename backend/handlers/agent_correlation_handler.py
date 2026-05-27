"""Handler for GET /api/productivity/{userId}/correlation — Agent-based analysis.

Checks DynamoDB cache first. If no valid cache exists, dispatches an async
worker Lambda to perform the AgentCore invocation and returns immediately
with a "processing" status. The frontend polls until the result is ready.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Literal

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from repository.analytics_repository import AnalyticsRepository
from repository.git_repository import GitRepository
from shared.structured_logger import StructuredLogger

logger = StructuredLogger("agent-correlation-handler")

PENDING_TTL_SECONDS = 300  # 5 minutes safety net

# Stable English status slugs surfaced on non-success branches of the
# correlation API. The frontend maps each slug to a translation key under
# `productivity.correlation.status.<slug>`. Mirrors `CorrelationStatusSlug`
# in design.md / frontend types. Wiring of these slugs into the inline
# non-success response dicts is owned by task 12.2.
CorrelationStatusSlug = Literal[
    "GIT_MAPPING_MISSING",
    "GITHUB_TOKEN_MISSING",
    "GITHUB_AUTH_FAILED",
    "GITHUB_RATE_LIMIT",
    "INSUFFICIENT_DATA",
    "AGENT_TIMEOUT",
    "AGENT_ERROR",
]

CORRELATION_STATUS_SLUGS: frozenset[str] = frozenset(
    {
        "GIT_MAPPING_MISSING",
        "GITHUB_TOKEN_MISSING",
        "GITHUB_AUTH_FAILED",
        "GITHUB_RATE_LIMIT",
        "INSUFFICIENT_DATA",
        "AGENT_TIMEOUT",
        "AGENT_ERROR",
    }
)


def _coerce_bilingual_insights(raw) -> dict:
    """Coerce ``insights`` to the bilingual map ``{en: [...], "pt-BR": [...]}``.

    Defensive read-side coercion that keeps `_format_response` total even when
    the agent (or a legacy cache row) produces a single list. Per Requirement
    8.10, a legacy ``List<String>`` becomes ``{"en": [], "pt-BR": <legacy list>}``.

    Args:
        raw: Whatever is in ``analysis["insights"]`` — typically a dict, list,
            or missing/None.

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


def handle_agent_correlation(
    user_id: str,
    query_params: dict,
    claims: dict,
    dynamodb_resource=None,
) -> dict:
    """Handle GET /api/productivity/{userId}/correlation.

    Flow:
        1. Validate authorization (admin or self)
        2. Check cache (unless forceRefresh)
        3. If no cache, check if analysis is already pending
        4. If not pending, dispatch async worker Lambda
        5. Return { status: "processing" } immediately
        6. On subsequent polls, return cached result when ready

    Args:
        user_id: Target user identifier.
        query_params: Dict with optional startDate, endDate, forceRefresh.
        claims: JWT claims of the caller.
        dynamodb_resource: Optional DynamoDB resource for testing.

    Returns:
        Response dict matching the CorrelationAnalysis contract.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    resource = dynamodb_resource or boto3.resource("dynamodb")
    analytics_repo = AnalyticsRepository(table_name, dynamodb_resource=resource)
    git_repo = GitRepository(table_name, dynamodb_resource=resource)
    table = resource.Table(table_name)

    start_date = query_params.get("startDate")
    end_date = query_params.get("endDate")
    force_refresh = query_params.get("forceRefresh", "").lower() == "true"

    if not start_date or not end_date:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        from datetime import timedelta
        end_date = end_date or today
        start_dt = datetime.now(timezone.utc) - timedelta(days=7)
        start_date = start_date or start_dt.strftime("%Y-%m-%d")

    # Empty period payload reused by every non-success / in-progress branch
    # below. `_format_response` reads `impactScore`, `impactLevel`,
    # `correlations`, `insights`, `analyzedAt`, and `period` from this dict
    # via `.get()` with safe defaults — the only field worth carrying
    # explicitly is `period`, which the frontend uses to label the card.
    #
    # Status slug ownership (design.md §"Backend-Level Errors"):
    #   - Owned by THIS handler: GIT_MAPPING_MISSING, GITHUB_TOKEN_MISSING.
    #     Both are returned with HTTP 200 — the user can act on them
    #     (configure mapping / token).
    #   - Owned by the worker Lambda + AgentCore invocation path (NOT here):
    #     GITHUB_AUTH_FAILED, GITHUB_RATE_LIMIT (surfaced from the agent's
    #     github_tool); INSUFFICIENT_DATA (agent returned impactScore=null
    #     with reason); AGENT_TIMEOUT, AGENT_ERROR (HTTP 503, raised when
    #     the worker invocation times out or fails). Those slugs are wired
    #     by the worker handler — this handler only dispatches the worker.
    #   - "processing" is NOT a CorrelationStatusSlug — it is a transient
    #     in-progress signal. `_format_response` accepts any string for
    #     `status`, so we pass it through here. The slug Literal is
    #     reserved for terminal non-success conditions per design.md.
    empty_period_analysis = {"period": {"startDate": start_date, "endDate": end_date}}

    mappings = git_repo.list_user_mappings(user_id)
    if not mappings:
        return _format_response(
            user_id,
            empty_period_analysis,
            cached=False,
            status="GIT_MAPPING_MISSING",
            message="No Git mapping found for this user. Please configure on the settings page.",
        )

    # Check if analysis is already pending (takes priority over cache)
    if _is_pending(table, user_id, start_date, end_date):
        logger.info("Analysis already pending", userId=user_id)
        return _format_response(
            user_id,
            empty_period_analysis,
            cached=False,
            status="processing",
            message="Analysis in progress. Results will be available shortly.",
        )

    # Check cache (unless force refresh)
    if not force_refresh:
        cached = analytics_repo.get_latest_analysis(
            user_id, start_date=start_date, end_date=end_date
        )
        if cached:
            logger.info("Returning cached analysis", userId=user_id)
            return _format_response(user_id, cached, cached=True)

    # Fetch GitHub token from SSM
    token = _fetch_github_token(user_id)
    if token is None:
        return _format_response(
            user_id,
            empty_period_analysis,
            cached=False,
            status="GITHUB_TOKEN_MISSING",
            message="GitHub token not configured. Please add your token on the settings page.",
        )

    # Resolve git username and repos
    git_username = None
    for m in mappings:
        if m.get("provider") == "github":
            git_username = m.get("gitUsername")
    if not git_username:
        git_username = mappings[0].get("gitUsername", "")

    repos = []
    repo_configs = git_repo.list_repo_configs()
    for config in repo_configs:
        url = config.get("url", "")
        if "github.com" in url:
            parts = url.rstrip("/").split("/")
            if len(parts) >= 2:
                repos.append({"owner": parts[-2], "repo": parts[-1]})

    # Atomically set pending flag (prevents race condition)
    flag_set = _set_pending_flag(table, user_id, start_date, end_date)

    if not flag_set:
        # Another request won the race — just return processing
        logger.info("Lost pending flag race, returning processing", userId=user_id)
        return _format_response(
            user_id,
            empty_period_analysis,
            cached=False,
            status="processing",
            message="Analysis in progress. Results will be available shortly.",
        )

    # Dispatch async worker
    _dispatch_worker(user_id, start_date, end_date, git_username, repos, token)

    logger.info("Dispatched async worker", userId=user_id)
    return _format_response(
        user_id,
        empty_period_analysis,
        cached=False,
        status="processing",
        message="Analysis started. Results will be available shortly.",
    )


def _is_pending(table, user_id: str, start_date: str, end_date: str) -> bool:
    """Check if there's already a pending analysis for this user.

    Args:
        table: boto3 DynamoDB Table resource.
        user_id: Kiro user identifier.
        start_date: Requested start date.
        end_date: Requested end date.

    Returns:
        True if a valid (non-expired) pending flag exists.
    """
    try:
        response = table.get_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": "ANALYSIS_PENDING",
            }
        )
        item = response.get("Item")
        if not item:
            return False

        # Check TTL — if expired, treat as not pending
        ttl = int(item.get("TTL", 0))
        if ttl and ttl < int(time.time()):
            return False

        return True
    except ClientError:
        return False


def _set_pending_flag(table, user_id: str, start_date: str, end_date: str) -> bool:
    """Atomically write the ANALYSIS_PENDING item to DynamoDB.

    Uses a conditional write to prevent race conditions — if two requests
    arrive simultaneously, only one succeeds in creating the flag.

    Args:
        table: boto3 DynamoDB Table resource.
        user_id: Kiro user identifier.
        start_date: Analysis start date.
        end_date: Analysis end date.

    Returns:
        True if the flag was set (this request should dispatch the worker).
        False if the flag already existed (another request won the race).
    """
    ttl = int(time.time()) + PENDING_TTL_SECONDS
    try:
        table.put_item(
            Item={
                "PK": f"USER#{user_id}",
                "SK": "ANALYSIS_PENDING",
                "TTL": ttl,
                "startDate": start_date,
                "endDate": end_date,
                "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
            ConditionExpression="attribute_not_exists(PK) OR #ttl < :now",
            ExpressionAttributeNames={"#ttl": "TTL"},
            ExpressionAttributeValues={":now": int(time.time())},
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def _dispatch_worker(
    user_id: str,
    start_date: str,
    end_date: str,
    git_username: str,
    repos: list[dict],
    token: str,
) -> None:
    """Invoke the correlation worker Lambda asynchronously (fire-and-forget).

    Args:
        user_id: Kiro user identifier.
        start_date: Analysis start date.
        end_date: Analysis end date.
        git_username: GitHub username.
        repos: List of dicts with owner/repo.
        token: GitHub access token (unused — worker fetches from SSM).
    """
    worker_arn = os.environ.get("CORRELATION_WORKER_ARN", "")
    if not worker_arn:
        logger.error("CORRELATION_WORKER_ARN not configured")
        return

    lambda_client = boto3.client("lambda", region_name="sa-east-1")

    payload = {
        "userId": user_id,
        "startDate": start_date,
        "endDate": end_date,
        "gitUsername": git_username,
        "repos": repos,
    }

    lambda_client.invoke(
        FunctionName=worker_arn,
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def _fetch_github_token(user_id: str) -> str | None:
    """Fetch the GitHub token from SSM Parameter Store.

    Scans /kiro-cost-analyzer/git-tokens/ for configured tokens and returns
    the most recently modified one (which is likely the valid/current token).

    Args:
        user_id: Kiro user identifier (unused — token is org-wide).

    Returns:
        The token string, or None if not found.
    """
    ssm_client = boto3.client("ssm", region_name="sa-east-1")

    try:
        response = ssm_client.get_parameters_by_path(
            Path="/kiro-cost-analyzer/git-tokens/",
            WithDecryption=True,
            MaxResults=10,
        )
        params = response.get("Parameters", [])
        if not params:
            logger.warning("No git tokens found in SSM at /kiro-cost-analyzer/git-tokens/")
            return None
        # Return the most recently modified token
        params.sort(key=lambda p: p.get("LastModifiedDate", ""), reverse=True)
        return params[0]["Value"]
    except ClientError as exc:
        logger.error("Failed to fetch git token from SSM", errorMessage=str(exc))
        return None


def _format_response(
    user_id: str,
    analysis: dict,
    cached: bool,
    *,
    status: str | None = None,
    message: str | None = None,
) -> dict:
    """Format the analysis into the API response contract.

    Always emits ``insights`` as the bilingual map shape required by
    Requirement 8.2 — both ``en`` and ``pt-BR`` keys are present (possibly
    as empty lists). Legacy list-shaped ``insights`` are coerced to
    ``{"en": [], "pt-BR": <legacy list>}`` so this function stays total
    even before the read-side coercion in ``AnalyticsRepository`` lands
    (task 12.3).

    Per Requirements 3.8/3.9 and 8.8, no human-readable ``message`` prose is
    echoed back to clients — the only machine-stable signal on non-success
    branches is the English ``status`` slug from
    ``CorrelationStatusSlug``. A ``message`` argument may still be passed in
    for operator context; it is logged and dropped from the response body.

    Args:
        user_id: Kiro user identifier.
        analysis: Cached or freshly computed analysis dict.
        cached: Whether the analysis was served from cache.
        status: Optional non-success status slug. ``None`` (default) means
            the response represents a successful, ready analysis and the
            response status will be ``"ready"``.
        message: Optional operator-context message. Logged via
            ``StructuredLogger`` and intentionally NOT included in the
            response body.

    Returns:
        Response dict matching the ``CorrelationAnalysis`` API contract.
    """
    if message:
        # Keep operator context in structured logs only — never echoed back.
        logger.info(
            "format_response operator message",
            userId=user_id,
            status=status,
            cached=cached,
            operatorMessage=message,
        )

    response = {
        "userId": user_id,
        "status": status if status is not None else "ready",
        "impactScore": analysis.get("impactScore"),
        "impactLevel": analysis.get("impactLevel"),
        "correlations": analysis.get("correlations", []),
        "insights": _coerce_bilingual_insights(analysis.get("insights")),
        "period": analysis.get("period", {}),
        "analyzedAt": analysis.get("analyzedAt"),
        "cached": cached,
    }
    return response
