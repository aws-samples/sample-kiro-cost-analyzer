"""Handlers for GET /api/prompts and GET /api/prompts/{requestId}.

Provides paginated prompt metadata listing and full prompt detail retrieval,
with dual-gate access control (admin + feature enabled via SSM parameter).
"""

from __future__ import annotations

import json
import os
import time

import boto3

try:
    from repository.analytics_repository import AnalyticsRepository
except ImportError:
    from backend.repository.analytics_repository import AnalyticsRepository

from shared.categories import SYSTEM_CATEGORIES
from shared.structured_logger import StructuredLogger

logger = StructuredLogger("prompts-handler")

# Categories considered non-meaningful — excluded from default listing.
# Sourced from ``shared.categories`` so the writer, the categorizer, and
# this filter stay byte-identical. DynamoDB ``Attr.ne()`` is case-sensitive
# and a lowercase mismatch silently lets system items through.
_SYSTEM_CATEGORIES = SYSTEM_CATEGORIES


class _FeatureFlagCache:
    """In-memory cache for the prompt-history-enabled SSM parameter.

    Max staleness: 300 seconds. Fail-closed: returns False on SSM errors.
    """

    _value: bool = False
    _last_fetched: float = 0.0
    _ttl: int = 300  # seconds

    @classmethod
    def is_enabled(cls, ssm_client=None) -> bool:
        """Check if prompt history is enabled. Caches for 300s.

        Args:
            ssm_client: Optional pre-configured SSM client for testing.

        Returns:
            True if the feature is enabled, False otherwise (including on errors).
        """
        now = time.time()
        if now - cls._last_fetched < cls._ttl:
            return cls._value

        client = ssm_client or boto3.client("ssm")
        param_name = os.environ.get(
            "SSM_PROMPT_HISTORY_ENABLED",
            "/kiro-cost-analyzer/prompt-history-enabled",
        )

        try:
            resp = client.get_parameter(Name=param_name)
            cls._value = resp["Parameter"]["Value"].lower() == "true"
        except Exception:
            # Fail-closed: treat feature as disabled on any SSM error
            cls._value = False

        cls._last_fetched = now
        return cls._value

    @classmethod
    def reset(cls) -> None:
        """Reset cache state. Used in tests."""
        cls._value = False
        cls._last_fetched = 0.0


def _generate_prompt_preview(prompt_text: str | None) -> str:
    """Truncate prompt to 200 chars with '...' suffix when exceeded.

    Args:
        prompt_text: The raw prompt content string.

    Returns:
        A preview string of at most 203 characters (200 + '...') or the
        original text if it's 200 chars or fewer.
    """
    if not prompt_text:
        return ""
    if len(prompt_text) > 200:
        return prompt_text[:200] + "..."
    return prompt_text


def _clamp_limit(raw_limit: str | None) -> int:
    """Parse and clamp the limit query parameter to [1, 100], default 20.

    Args:
        raw_limit: The raw limit string from query parameters.

    Returns:
        An integer in the range [1, 100].
    """
    if raw_limit is None:
        return 20
    try:
        value = int(raw_limit)
    except (ValueError, TypeError):
        return 20
    return max(1, min(value, 100))


def handle_list_prompts(
    query_params: dict,
    dynamodb_resource=None,
    ssm_client=None,
) -> dict:
    """Handle GET /api/prompts — paginated prompt metadata list.

    Args:
        query_params: Dict of query string parameters. Required: userId.
            Optional: limit, nextToken, startDate, endDate, category.
        dynamodb_resource: Optional boto3 DynamoDB resource for testing.
        ssm_client: Optional boto3 SSM client for testing.

    Returns:
        Response dict with statusCode and body, or just the body dict for
        successful responses routed through the main handler.
    """
    start_time = time.time()

    # Validate userId is present
    user_id = query_params.get("userId")
    if not user_id:
        logger.info(
            "Missing userId parameter",
            httpMethod="GET",
            path="/api/prompts",
            statusCode=400,
        )
        return {
            "_status_code": 400,
            "error": "InvalidParameters",
            "message": "userId is required",
        }

    # Check feature enabled
    if not _FeatureFlagCache.is_enabled(ssm_client=ssm_client):
        logger.info(
            "Prompt history feature disabled",
            userId=user_id,
            httpMethod="GET",
            path="/api/prompts",
            statusCode=403,
        )
        return {
            "_status_code": 403,
            "error": "Forbidden",
            "message": "Prompt history is not enabled",
        }

    # Parse and clamp limit
    limit = _clamp_limit(query_params.get("limit"))

    # Parse other params
    next_token = query_params.get("nextToken")
    start_date = query_params.get("startDate")
    end_date = query_params.get("endDate")
    category = query_params.get("category")

    # Determine category exclusion
    # Exclude System_Categories by default unless a specific category is requested
    exclude_categories = None
    if not category:
        exclude_categories = list(_SYSTEM_CATEGORIES)
    elif category in _SYSTEM_CATEGORIES:
        # Explicit request for a system category — don't exclude anything
        exclude_categories = None

    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = AnalyticsRepository(table_name, dynamodb_resource=dynamodb_resource)

    result = repo.get_user_prompts(
        user_id=user_id,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
        next_token=next_token,
        category=category if category else None,
        exclude_categories=exclude_categories,
    )

    # Build response items with promptPreview
    items = []
    for item in result.get("items", []):
        prompt_preview = _generate_prompt_preview(item.get("prompt", ""))
        items.append({
            "requestId": item.get("requestId", ""),
            "timestamp": item.get("timestamp", ""),
            "category": item.get("category", ""),
            "promptPreview": prompt_preview,
            "modelId": item.get("modelId", ""),
            "triggerType": item.get("triggerType", ""),
            "promptLength": item.get("promptLength", 0),
            "responseLength": item.get("responseLength", 0),
        })

    latency_ms = int((time.time() - start_time) * 1000)
    logger.info(
        "Prompts listed",
        userId=user_id,
        httpMethod="GET",
        path="/api/prompts",
        statusCode=200,
        latencyMs=latency_ms,
    )

    return {
        "items": items,
        "nextToken": result.get("nextToken"),
    }


def handle_get_prompt_detail(
    request_id: str,
    query_params: dict,
    dynamodb_resource=None,
    s3_client=None,
    ssm_client=None,
) -> dict:
    """Handle GET /api/prompts/{requestId} — full prompt + response content.

    Args:
        request_id: The unique prompt request identifier from the URL path.
        query_params: Dict of query string parameters. Required: userId.
        dynamodb_resource: Optional boto3 DynamoDB resource for testing.
        s3_client: Optional boto3 S3 client for testing.
        ssm_client: Optional boto3 SSM client for testing.

    Returns:
        Response dict with full prompt and response content, or an error
        dict with _status_code for error responses.
    """
    start_time = time.time()

    # Validate userId is present
    user_id = query_params.get("userId")
    if not user_id:
        logger.info(
            "Missing userId parameter",
            httpMethod="GET",
            path=f"/api/prompts/{request_id}",
            statusCode=400,
        )
        return {
            "_status_code": 400,
            "error": "InvalidParameters",
            "message": "userId is required",
        }

    # Check feature enabled
    if not _FeatureFlagCache.is_enabled(ssm_client=ssm_client):
        logger.info(
            "Prompt history feature disabled",
            userId=user_id,
            httpMethod="GET",
            path=f"/api/prompts/{request_id}",
            statusCode=403,
        )
        return {
            "_status_code": 403,
            "error": "Forbidden",
            "message": "Prompt history is not enabled",
        }

    # Query DynamoDB by requestId (GSI)
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = AnalyticsRepository(table_name, dynamodb_resource=dynamodb_resource)

    item = repo.get_prompt_by_request_id(request_id)

    if not item:
        logger.info(
            "Prompt not found",
            requestId=request_id,
            httpMethod="GET",
            path=f"/api/prompts/{request_id}",
            statusCode=404,
        )
        return {
            "_status_code": 404,
            "error": "NotFound",
            "message": "Prompt not found",
        }

    # Extract content — either inline or from S3
    prompt_content = item.get("prompt", "")
    response_content = item.get("response", "")

    if item.get("contentInS3") is True:
        bucket_name = os.environ.get("DATA_BUCKET", "kiro-cost-analyzer-data")
        s3_key = f"prompts-content/{request_id}.json"

        client = s3_client or boto3.client("s3")
        try:
            s3_response = client.get_object(Bucket=bucket_name, Key=s3_key)
            s3_body = s3_response["Body"].read().decode("utf-8")
            s3_data = json.loads(s3_body)
            prompt_content = s3_data.get("prompt", "")
            response_content = s3_data.get("response", "")
        except Exception as exc:
            logger.error(
                "Content retrieval failed",
                requestId=request_id,
                errorType=type(exc).__name__,
                httpMethod="GET",
                path=f"/api/prompts/{request_id}",
                statusCode=500,
            )
            return {
                "_status_code": 500,
                "error": "ContentRetrievalFailed",
                "message": "Failed to retrieve prompt content",
            }

    latency_ms = int((time.time() - start_time) * 1000)
    logger.info(
        "Prompt detail retrieved",
        requestId=request_id,
        userId=user_id,
        httpMethod="GET",
        path=f"/api/prompts/{request_id}",
        statusCode=200,
        latencyMs=latency_ms,
    )

    return {
        "requestId": request_id,
        "timestamp": item.get("timestamp", ""),
        "category": item.get("category", ""),
        "modelId": item.get("modelId", ""),
        "prompt": prompt_content,
        "response": response_content,
        "promptLength": item.get("promptLength", 0),
        "responseLength": item.get("responseLength", 0),
        "contentInS3": item.get("contentInS3", False),
    }
