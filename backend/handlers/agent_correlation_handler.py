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

try:
    from git_shared.git_repository import GitRepository
except ImportError:
    from layers.shared.git_shared.git_repository import GitRepository
try:
    from git_shared.git_providers import (
        PROVIDER_ORDER,
        SSM_TOKEN_PATH_PREFIX,
        SUPPORTED_PROVIDERS,
        TOKEN_MISSING_SLUG,
    )
except ImportError:
    from layers.shared.git_shared.git_providers import (
        PROVIDER_ORDER,
        SSM_TOKEN_PATH_PREFIX,
        SUPPORTED_PROVIDERS,
        TOKEN_MISSING_SLUG,
    )
try:
    from git_shared.git_url_parser import parse_repo_url
except ImportError:
    from layers.shared.git_shared.git_url_parser import parse_repo_url
try:
    from git_shared.git_mapping_selection import select_mapping
except ImportError:
    from layers.shared.git_shared.git_mapping_selection import select_mapping
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
    "GITLAB_TOKEN_MISSING",
    "GITLAB_AUTH_FAILED",
    "GITLAB_RATE_LIMIT",
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
        "GITLAB_TOKEN_MISSING",
        "GITLAB_AUTH_FAILED",
        "GITLAB_RATE_LIMIT",
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


def resolve_usernames_by_provider(mappings: list[dict]) -> dict[str, str]:
    """Map each provider to the single gitUsername the user holds for it.

    Under the DD-6 key shape a user holds at most one mapping per provider
    (Requirement 2.6), so in steady state this is a plain projection. The
    ``select_mapping`` call only has more than one candidate to choose from
    when reading data written before the migration ran, where two legacy
    items for one provider can still coexist. It keeps the read
    deterministic during that window (Requirement 7.9).

    Args:
        mappings: List of user-to-Git mapping dicts, each with at least
            ``provider`` and ``gitUsername``.

    Returns:
        Dict mapping each provider present in ``mappings`` to the resolved
        ``gitUsername`` for that provider.
    """
    by_provider: dict[str, list[dict]] = {}
    for mapping in mappings:
        provider = mapping.get("provider")
        if provider and mapping.get("gitUsername"):
            by_provider.setdefault(provider, []).append(mapping)
    return {
        provider: select_mapping(candidates)["gitUsername"]
        for provider, candidates in by_provider.items()
    }


def build_repo_descriptors(
    repo_configs: list[dict],
    mappings: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Build per-repository descriptors for the agent invocation payload.

    Replaces the previous GitHub-only, provider-blind block that matched on
    ``"github.com" in url``. Every entry in ``repo_configs`` lands in
    exactly one of the two returned lists. Per DD-3, a descriptor carries
    ``repoId`` and never a token value or an SSM parameter path.

    Exclusion reasons (also emitted as a structured warning per exclusion):
        UNSUPPORTED_PROVIDER — provider not in SUPPORTED_PROVIDERS
        UNPARSEABLE_URL      — parse_repo_url returned None (Requirement 4.5)
        NO_USER_MAPPING      — no mapping for this repo's provider (Requirement 7.3)

    Args:
        repo_configs: List of stored repository configuration dicts, each
            carrying at least ``PK``, ``url``, and ``provider``.
        mappings: List of the user's Git mapping dicts.

    Returns:
        A tuple ``(descriptors, excluded)``. Each descriptor carries
        ``repoId``, ``provider``, ``gitUsername``, and the provider-specific
        location fields returned by ``parse_repo_url`` (``owner``/``repo``
        for github; ``baseUrl``/``projectPath`` for gitlab). Each excluded
        entry carries ``repoId``, ``provider``, and ``reason``.
    """
    usernames_by_provider = resolve_usernames_by_provider(mappings)

    descriptors: list[dict] = []
    excluded: list[dict] = []

    for config in repo_configs:
        pk = config.get("PK", "")
        repo_id = pk.replace("GITREPO#", "") if pk.startswith("GITREPO#") else ""
        provider = config.get("provider", "")
        url = config.get("url", "")

        if provider not in SUPPORTED_PROVIDERS:
            reason = "UNSUPPORTED_PROVIDER"
            excluded.append({"repoId": repo_id, "provider": provider, "reason": reason})
            logger.warning(
                "Excluding repository from correlation analysis",
                repoId=repo_id,
                provider=provider,
                reason=reason,
            )
            continue

        location = parse_repo_url(provider, url)
        if location is None:
            reason = "UNPARSEABLE_URL"
            excluded.append({"repoId": repo_id, "provider": provider, "reason": reason})
            logger.warning(
                "Excluding repository from correlation analysis",
                repoId=repo_id,
                provider=provider,
                reason=reason,
            )
            continue

        git_username = usernames_by_provider.get(provider)
        if not git_username:
            reason = "NO_USER_MAPPING"
            excluded.append({"repoId": repo_id, "provider": provider, "reason": reason})
            logger.warning(
                "Excluding repository from correlation analysis",
                repoId=repo_id,
                provider=provider,
                reason=reason,
            )
            continue

        descriptor = {
            "repoId": repo_id,
            "provider": provider,
            "gitUsername": git_username,
            **location,
        }
        descriptors.append(descriptor)

    return descriptors, excluded


def resolve_token_availability(
    descriptors: list[dict],
    ssm_client=None,
) -> tuple[list[dict], list[dict]]:
    """Partition descriptors into (available, missing) by SSM token presence.

    Replaces the provider-blind, repo-blind ``_fetch_github_token`` heuristic
    (Requirement 3.1, 3.2). For each descriptor, calls
    ``ssm.get_parameter(Name=f"{SSM_TOKEN_PATH_PREFIX}/{repoId}",
    WithDecryption=False)``. The value is never read — only existence
    matters at this layer, so the secret is not decrypted into this Lambda.
    A ``ParameterNotFound`` error means the token is missing for that
    descriptor and does not propagate.

    Args:
        descriptors: List of repository descriptor dicts, each carrying at
            least ``repoId`` (per ``build_repo_descriptors``).
        ssm_client: Optional boto3 SSM client, injected for testability. A
            new client is created via ``boto3.client("ssm")`` when omitted.

    Returns:
        A tuple ``(available, missing)`` — a partition of ``descriptors``.
        Every input descriptor lands in exactly one of the two lists.
    """
    client = ssm_client or boto3.client("ssm")

    available: list[dict] = []
    missing: list[dict] = []

    for descriptor in descriptors:
        repo_id = descriptor.get("repoId", "")
        parameter_name = f"{SSM_TOKEN_PATH_PREFIX}/{repo_id}"
        try:
            client.get_parameter(Name=parameter_name, WithDecryption=False)
            available.append(descriptor)
        except client.exceptions.ParameterNotFound:
            missing.append(descriptor)
        except ClientError as exc:
            logger.error(
                "Failed to check token presence in SSM",
                repoId=repo_id,
                provider=descriptor.get("provider"),
                errorMessage=str(exc),
            )
            missing.append(descriptor)

    return available, missing


def select_token_missing_slug(missing: list[dict]) -> str:
    """Pick the token-missing slug to surface when NO repository has a token.

    Deterministic rule (Requirement 3.3): the provider with the most
    affected repositories wins; ties break by ``PROVIDER_ORDER``
    (``"github"`` before ``"gitlab"``). When ``missing`` is empty, defaults
    to the first provider in ``PROVIDER_ORDER`` so this function stays
    total.

    Args:
        missing: List of descriptors that have no resolvable token.

    Returns:
        The token-missing status slug for the affected provider.
    """
    counts: dict[str, int] = {}
    for descriptor in missing:
        provider = descriptor.get("provider", "")
        counts[provider] = counts.get(provider, 0) + 1

    if not counts:
        return TOKEN_MISSING_SLUG[PROVIDER_ORDER[0]]

    winner = max(
        PROVIDER_ORDER,
        key=lambda provider: counts.get(provider, 0),
    )
    return TOKEN_MISSING_SLUG[winner]


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
    #   - Owned by THIS handler: GIT_MAPPING_MISSING, GITHUB_TOKEN_MISSING,
    #     GITLAB_TOKEN_MISSING. All are returned with HTTP 200 — the user
    #     can act on them (configure mapping / token).
    #   - Owned by the worker Lambda + AgentCore invocation path (NOT here):
    #     GITHUB_AUTH_FAILED, GITHUB_RATE_LIMIT, GITLAB_AUTH_FAILED,
    #     GITLAB_RATE_LIMIT (surfaced from the agent's provider tools);
    #     INSUFFICIENT_DATA (agent returned impactScore=null with reason);
    #     AGENT_TIMEOUT, AGENT_ERROR (HTTP 503, raised when the worker
    #     invocation times out or fails). Those slugs are wired by the
    #     worker handler — this handler only dispatches the worker.
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

    # Build provider-aware repository descriptors (Requirements 7.1-7.4, 7.8, 7.9).
    repo_configs = git_repo.list_repo_configs()
    descriptors, excluded = build_repo_descriptors(repo_configs, mappings)

    # Repository-scoped token presence check (Requirements 3.1, 3.2, 3.3).
    # Replaces the provider-blind `_fetch_github_token`. A partial analysis
    # with some providers working is more useful than a hard failure, so we
    # only abort when NO descriptor anywhere has a token.
    available, missing = resolve_token_availability(descriptors)

    for descriptor in missing:
        logger.warning(
            "Repository excluded from correlation analysis: token missing",
            repoId=descriptor.get("repoId"),
            provider=descriptor.get("provider"),
        )

    if not available:
        return _format_response(
            user_id,
            empty_period_analysis,
            cached=False,
            status=select_token_missing_slug(missing),
            message="Git token not configured for the affected provider. Please add it on the settings page.",
        )

    # Top-level `gitUsername` is retained for backward compatibility with
    # `_dispatch_worker`'s payload (DD-5): populated from the GitHub mapping,
    # falling back to the first mapping.
    git_username = None
    for m in mappings:
        if m.get("provider") == "github":
            git_username = m.get("gitUsername")
    if not git_username:
        git_username = mappings[0].get("gitUsername", "")

    repos = available

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
    _dispatch_worker(user_id, start_date, end_date, git_username, repos)

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
) -> None:
    """Invoke the correlation worker Lambda asynchronously (fire-and-forget).

    Args:
        user_id: Kiro user identifier.
        start_date: Analysis start date.
        end_date: Analysis end date.
        git_username: GitHub username.
        repos: List of provider-tagged repository descriptors with a
            resolvable token (per DD-3, never carrying a token value or SSM
            parameter path — the worker fetches the token itself).
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
