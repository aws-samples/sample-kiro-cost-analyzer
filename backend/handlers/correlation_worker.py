"""Worker Lambda for async correlation analysis.

Invoked asynchronously by the main backend handler when no cached analysis
exists. Performs the AgentCore invocation (which can take 15-60s), persists
the result to DynamoDB, and clears the pending flag.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from repository.analytics_repository import AnalyticsRepository
from repository.git_repository import GitRepository
from shared.structured_logger import StructuredLogger

logger = StructuredLogger("correlation-worker")

AGENT_TIMEOUT_SECONDS = 300


def _coerce_bilingual_insights(raw) -> dict:
    """Coerce ``insights`` to the bilingual map ``{en: [...], "pt-BR": [...]}``.

    Mirrors the helpers in ``backend/handlers/agent_correlation_handler`` and
    ``backend/repository/analytics_repository``. Defined locally here so the
    write path produces the canonical bilingual shape directly — no longer
    relying on read-side coercion to fix up legacy items. A modern dict is
    preserved structurally; a bare list is treated as legacy pt-BR; missing /
    ``None`` / unexpected types collapse to empty bilingual lists.
    """
    if isinstance(raw, dict):
        return {
            "en": list(raw.get("en", []) or []),
            "pt-BR": list(raw.get("pt-BR", []) or []),
        }
    if isinstance(raw, list):
        return {"en": [], "pt-BR": list(raw)}
    return {"en": [], "pt-BR": []}


def lambda_handler(event: dict, context) -> dict:
    """Entry point for the correlation worker Lambda.

    Receives a payload with userId, startDate, endDate, gitUsername, repos,
    and token. Invokes AgentCore, persists the result, and clears the
    pending flag in DynamoDB.

    Args:
        event: Dict with userId, startDate, endDate, gitUsername, repos, token.
        context: Lambda context (unused).

    Returns:
        Dict with status and optional error message.
    """
    user_id = event.get("userId", "")
    start_date = event.get("startDate", "")
    end_date = event.get("endDate", "")
    git_username = event.get("gitUsername", "")
    repos = event.get("repos", [])

    logger.info(
        "Worker invoked",
        userId=user_id,
        startDate=start_date,
        endDate=end_date,
    )

    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    dynamodb_resource = boto3.resource("dynamodb")
    analytics_repo = AnalyticsRepository(table_name, dynamodb_resource=dynamodb_resource)
    table = dynamodb_resource.Table(table_name)

    try:
        analysis = _invoke_agent(user_id, start_date, end_date, git_username, repos)

        analyzed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        analysis_record = {
            "impactScore": analysis.get("impactScore"),
            "impactLevel": analysis.get("impactLevel", "low"),
            "correlations": analysis.get("correlations", []),
            "insights": _coerce_bilingual_insights(analysis.get("insights")),
            "period": {"startDate": start_date, "endDate": end_date},
            "analyzedAt": analyzed_at,
            "model": "global.anthropic.claude-sonnet-4-6",
            "tokensUsed": analysis.get("tokensUsed", 0),
        }

        analytics_repo.put_analysis(user_id, analysis_record)
        logger.info("Persisted analysis result", userId=user_id)

    except Exception as exc:
        logger.error(
            "Worker failed",
            userId=user_id,
            error=str(exc),
            errorType=type(exc).__name__,
        )
    finally:
        _clear_pending_flag(table, user_id)

    return {"status": "completed", "userId": user_id}


def _invoke_agent(
    user_id: str,
    start_date: str,
    end_date: str,
    git_username: str,
    repos: list[dict],
) -> dict:
    """Invoke the AgentCore runtime for correlation analysis.

    Args:
        user_id: Kiro user identifier.
        start_date: Analysis start date (YYYY-MM-DD).
        end_date: Analysis end date (YYYY-MM-DD).
        git_username: GitHub username.
        repos: List of dicts with owner/repo.

    Returns:
        Parsed analysis result dict.
    """
    agent_runtime_arn = os.environ.get("CORRELATION_AGENT_RUNTIME_ARN", "")

    # The ARN is "NONE" (the template default) until `make deploy-agentcore`
    # resolves the runtime by name and writes it into the stack. Fail fast with
    # a clear signal instead of calling InvokeAgentRuntime with an unusable ARN,
    # which would surface as an opaque ValidationException/ResourceNotFound.
    if not agent_runtime_arn or agent_runtime_arn == "NONE":
        raise RuntimeError(
            "CORRELATION_AGENT_RUNTIME_ARN is not configured (agent not deployed). "
            "Run 'make deploy-agentcore' to provision the runtime and wire its ARN."
        )

    payload = {
        "userId": user_id,
        "startDate": start_date,
        "endDate": end_date,
        "gitUsername": git_username,
        "repos": repos,
    }

    client = boto3.client(
        "bedrock-agentcore",
        region_name="sa-east-1",
        config=Config(read_timeout=AGENT_TIMEOUT_SECONDS + 10),
    )

    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_runtime_arn,
        contentType="application/json",
        accept="application/json",
        payload=json.dumps(payload).encode("utf-8"),
    )

    result_text = response["response"].read().decode("utf-8")
    logger.info("Agent raw response", response_text=result_text[:500])
    result = json.loads(result_text)
    if isinstance(result, str):
        result = json.loads(result)
    return result


def _clear_pending_flag(table, user_id: str) -> None:
    """Remove the ANALYSIS_PENDING item from DynamoDB.

    Args:
        table: boto3 DynamoDB Table resource.
        user_id: Kiro user identifier.
    """
    try:
        table.delete_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": "ANALYSIS_PENDING",
            }
        )
        logger.info("Cleared pending flag", userId=user_id)
    except ClientError as exc:
        logger.error(
            "Failed to clear pending flag",
            userId=user_id,
            error=str(exc),
        )
