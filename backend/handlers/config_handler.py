"""Handlers for GET /api/config, PUT /api/config/source-bucket-role-arn, and GET /api/config/schedule."""

import json
import logging
import os
import re

import boto3

try:
    from shared.structured_logger import StructuredLogger
except ImportError:
    from layers.shared.shared.structured_logger import StructuredLogger

logger = logging.getLogger(__name__)
structured_logger = StructuredLogger("config-handler")

_ARN_PATTERN = re.compile(r"^arn:aws:iam::\d{12}:role/.+$")


def _get_ssm_client(ssm_client=None):
    """Return the provided client or create a new SSM client."""
    return ssm_client or boto3.client("ssm")


def _get_parameter(ssm, name: str) -> str:
    """Read a single SSM parameter value, returning empty string on error."""
    try:
        resp = ssm.get_parameter(Name=name)
        return resp["Parameter"]["Value"]
    except Exception:
        return ""


def handle_get_config(ssm_client=None) -> dict:
    """Handle GET /api/config — return current configuration and ETL status.

    Reads bucket-name, source-prefix, etl-status, and prompt-history-enabled
    from Parameter Store.

    Returns:
        Dict with bucketName, sourcePrefix, etlStatus, promptHistoryEnabled,
        and other configuration fields.
    """
    ssm = _get_ssm_client(ssm_client)

    ssm_bucket = os.environ.get("SSM_BUCKET_NAME", "/kiro-cost-analyzer/bucket-name")
    ssm_prefix = os.environ.get("SSM_SOURCE_PREFIX", "/kiro-cost-analyzer/source-prefix")
    ssm_etl = os.environ.get("SSM_ETL_STATUS", "/kiro-cost-analyzer/etl-status")
    ssm_prompts_prefix = os.environ.get("SSM_PROMPTS_PREFIX", "/kiro-cost-analyzer/prompts-prefix")
    ssm_identity_store_id = os.environ.get("SSM_IDENTITY_STORE_ID", "/kiro-cost-analyzer/identity-store-id")
    ssm_source_bucket_role_arn = os.environ.get("SSM_SOURCE_BUCKET_ROLE_ARN", "/kiro-cost-analyzer/source-bucket-role-arn")
    ssm_identity_store_role_arn = os.environ.get("SSM_IDENTITY_STORE_ROLE_ARN", "/kiro-cost-analyzer/identity-store-role-arn")
    ssm_prompt_history_enabled = os.environ.get("SSM_PROMPT_HISTORY_ENABLED", "/kiro-cost-analyzer/prompt-history-enabled")

    bucket_name = _get_parameter(ssm, ssm_bucket)
    source_prefix = _get_parameter(ssm, ssm_prefix)
    etl_status_raw = _get_parameter(ssm, ssm_etl)
    prompts_prefix = _get_parameter(ssm, ssm_prompts_prefix)
    identity_store_id = _get_parameter(ssm, ssm_identity_store_id)
    source_bucket_role_arn = _get_parameter(ssm, ssm_source_bucket_role_arn)
    if source_bucket_role_arn == "NONE":
        source_bucket_role_arn = ""
    identity_store_role_arn = _get_parameter(ssm, ssm_identity_store_role_arn)
    if identity_store_role_arn == "NONE":
        identity_store_role_arn = ""
    prompt_history_enabled_raw = _get_parameter(ssm, ssm_prompt_history_enabled)
    prompt_history_enabled = prompt_history_enabled_raw == "true"

    # Parse etl-status JSON; fall back to raw string on parse failure
    try:
        etl_status = json.loads(etl_status_raw) if etl_status_raw else {}
    except (json.JSONDecodeError, TypeError):
        etl_status = {"raw": etl_status_raw}

    return {
        "bucketName": bucket_name,
        "sourcePrefix": source_prefix,
        "etlStatus": etl_status,
        "promptsPrefix": prompts_prefix,
        "identityStoreId": identity_store_id,
        "sourceBucketRoleArn": source_bucket_role_arn,
        "identityStoreRoleArn": identity_store_role_arn,
        "promptHistoryEnabled": prompt_history_enabled,
    }


def handle_put_config_identity_store_id(body: dict, ssm_client=None) -> dict:
    """Handle PUT /api/config/identity-store-id — save identity store ID to Parameter Store.

    Args:
        body: Request body with ``identityStoreId``.
        ssm_client: Optional pre-configured SSM client for testing.

    Returns:
        Dict with identityStoreId, status, and message.
    """
    identity_store_id = body.get("identityStoreId", "").strip()

    ssm = _get_ssm_client(ssm_client)
    ssm_param = os.environ.get("SSM_IDENTITY_STORE_ID", "/kiro-cost-analyzer/identity-store-id")

    ssm.put_parameter(Name=ssm_param, Value=identity_store_id, Type="String", Overwrite=True)

    return {
        "identityStoreId": identity_store_id,
        "status": "valid",
        "message": "Identity Store ID saved successfully",
    }


def handle_put_config_source_bucket_role_arn(body: dict, ssm_client=None) -> dict:
    """Handle PUT /api/config/source-bucket-role-arn — validate and save role ARN.

    Validates the ARN format when non-empty. An empty value disables
    cross-account access (single-account mode).

    Args:
        body: Request body with ``sourceBucketRoleArn``.
        ssm_client: Optional pre-configured SSM client for testing.

    Returns:
        Dict with sourceBucketRoleArn, status, and message.
    """
    role_arn = body.get("sourceBucketRoleArn", "").strip()

    # Allow empty value (disables cross-account); reject invalid non-empty ARN
    if role_arn and not _ARN_PATTERN.match(role_arn):
        return {
            "sourceBucketRoleArn": role_arn,
            "status": "error",
            "message": "Invalid ARN format. Expected: arn:aws:iam::<account-id>:role/<role-name>",
        }

    ssm = _get_ssm_client(ssm_client)
    ssm_param = os.environ.get(
        "SSM_SOURCE_BUCKET_ROLE_ARN", "/kiro-cost-analyzer/source-bucket-role-arn"
    )
    ssm.put_parameter(Name=ssm_param, Value=role_arn or "NONE", Type="String", Overwrite=True)

    return {
        "sourceBucketRoleArn": role_arn,
        "status": "valid",
        "message": "Source bucket role ARN saved successfully"
        if role_arn
        else "Cross-account mode disabled",
    }


def handle_put_config_identity_store_role_arn(body: dict, ssm_client=None) -> dict:
    """Handle PUT /api/config/identity-store-role-arn — validate and save role ARN.

    Validates the ARN format when non-empty. An empty value disables
    cross-account name resolution (single-account mode).

    Args:
        body: Request body with ``identityStoreRoleArn``.
        ssm_client: Optional pre-configured SSM client for testing.

    Returns:
        Dict with identityStoreRoleArn, status, and message.
    """
    role_arn = body.get("identityStoreRoleArn", "").strip()

    # Allow empty value (disables cross-account); reject invalid non-empty ARN
    if role_arn and not _ARN_PATTERN.match(role_arn):
        return {
            "identityStoreRoleArn": role_arn,
            "status": "error",
            "message": "Invalid ARN format. Expected: arn:aws:iam::<account-id>:role/<role-name>",
        }

    ssm = _get_ssm_client(ssm_client)
    ssm_param = os.environ.get(
        "SSM_IDENTITY_STORE_ROLE_ARN", "/kiro-cost-analyzer/identity-store-role-arn"
    )
    ssm.put_parameter(Name=ssm_param, Value=role_arn or "NONE", Type="String", Overwrite=True)

    return {
        "identityStoreRoleArn": role_arn,
        "status": "valid",
        "message": "Identity Store role ARN saved successfully"
        if role_arn
        else "Cross-account Identity Store mode disabled",
    }


def handle_put_config_prompt_history_enabled(body: dict, ssm_client=None) -> dict:
    """Handle PUT /api/config/prompt-history-enabled — persist toggle state.

    Validates that the request body contains an ``enabled`` field with a boolean
    value, then writes "true" or "false" to the SSM parameter.

    Args:
        body: Request body with ``enabled`` (bool).
        ssm_client: Optional pre-configured SSM client for testing.

    Returns:
        Dict with status, message, and enabled fields on success.
        Dict with error and message fields (plus _status_code=400) on validation failure.
    """
    enabled = body.get("enabled")

    if not isinstance(enabled, bool):
        structured_logger.info(
            "Invalid body for prompt history toggle",
            path="/api/config/prompt-history-enabled",
            statusCode=400,
        )
        return {
            "error": "InvalidBody",
            "message": "enabled field must be a boolean",
            "_status_code": 400,
        }

    ssm = _get_ssm_client(ssm_client)
    ssm_param = os.environ.get(
        "SSM_PROMPT_HISTORY_ENABLED",
        "/kiro-cost-analyzer/prompt-history-enabled",
    )

    ssm.put_parameter(
        Name=ssm_param,
        Value="true" if enabled else "false",
        Type="String",
        Overwrite=True,
    )

    structured_logger.info(
        "Prompt history visibility updated",
        path="/api/config/prompt-history-enabled",
        statusCode=200,
    )

    return {
        "status": "valid",
        "message": "Prompt history visibility updated",
        "enabled": enabled,
    }


# --- Schedule helpers ---

_RATE_PATTERN = re.compile(r"^rate\((\d+)\s+(minute|minutes|hour|hours|day|days)\)$")
_CRON_DAILY_PATTERN = re.compile(r"^cron\((\d+)\s+(\d+)\s+\*\s+\*\s+\?\s+\*\)$")


def _humanize_schedule(expression: str) -> str:
    """Convert an EventBridge schedule expression to human-readable English text.

    Supported patterns:
    - rate(1 day)         → "Every day"
    - rate(N days)        → "Every N days"
    - rate(1 hour)        → "Every hour"
    - rate(N hours)       → "Every N hours"
    - rate(1 minute)      → "Every minute"
    - rate(N minutes)     → "Every N minutes"
    - cron(M H * * ? *)   → "Every day at HH:MM"
    - Fallback            → raw expression
    """
    if not expression:
        return expression

    # rate(...) expressions
    match = _RATE_PATTERN.match(expression)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit in ("day", "days"):
            if amount == 1:
                return "Every day"
            return f"Every {amount} days"
        if unit in ("hour", "hours"):
            if amount == 1:
                return "Every hour"
            return f"Every {amount} hours"
        if unit in ("minute", "minutes"):
            if amount == 1:
                return "Every minute"
            return f"Every {amount} minutes"

    # cron(M H * * ? *) — daily at fixed time
    match = _CRON_DAILY_PATTERN.match(expression)
    if match:
        minute = int(match.group(1))
        hour = int(match.group(2))
        return f"Every day at {hour:02d}:{minute:02d}"

    # Fallback: return raw expression
    return expression


def handle_get_schedule(scheduler_client=None) -> dict:
    """Handle GET /api/config/schedule — return ETL schedule from EventBridge Scheduler.

    Queries the EventBridge Scheduler for the ETL schedule rule and returns
    the expression, enabled state, and a human-readable description in English.

    Args:
        scheduler_client: Optional pre-configured Scheduler client for testing.

    Returns:
        Dict with expression, enabled, and humanReadable fields.
        On failure, returns expression=None, enabled=False, error=True.
    """
    client = scheduler_client or boto3.client("scheduler")
    schedule_name = os.environ.get("ETL_SCHEDULE_NAME", "")

    try:
        response = client.get_schedule(Name=schedule_name)
        expression = response.get("ScheduleExpression", "")
        enabled = response.get("State", "ENABLED") == "ENABLED"

        return {
            "expression": expression,
            "enabled": enabled,
            "humanReadable": _humanize_schedule(expression),
        }
    except Exception as exc:
        logger.error("Failed to get schedule '%s': %s", schedule_name, exc)
        return {
            "expression": None,
            "enabled": False,
            "humanReadable": "Schedule unavailable",
            "error": True,
        }
