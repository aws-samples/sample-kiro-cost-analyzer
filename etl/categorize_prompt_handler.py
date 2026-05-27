"""CategorizePrompt AWS Lambda handler — categorizes a single prompt via Amazon Bedrock.

Entry point for the CategorizePrompt Lambda invoked by the Map Standard state
in the Step Functions ETL pipeline. Receives a single uncategorized prompt item,
reads its content (inline or from S3), classifies it using Amazon Bedrock's
PromptCategorizer, and updates the DynamoDB item with the resulting category.
"""

from __future__ import annotations

import json
import os
import traceback

import boto3
from prompt_categorizer import PromptCategorizer
from shared.analytics_writer import AnalyticsWriter
from shared.structured_logger import StructuredLogger
from shared.sk_normalizer import normalize_sk_value


# Lazy-initialized singleton for the categorizer (reuse across invocations)
_categorizer: PromptCategorizer | None = None


def _get_categorizer() -> PromptCategorizer:
    """Return a singleton PromptCategorizer instance."""
    global _categorizer  # noqa: PLW0603 - Singleton pattern for Lambda warm-start optimization
    if _categorizer is None:
        model_id = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-micro-v1:0")
        region = os.environ.get("BEDROCK_REGION", "us-east-1")
        data_bucket = os.environ.get("DATA_BUCKET", "")
        guardrail_id = os.environ.get("GUARDRAIL_ID", "")
        guardrail_version = os.environ.get("GUARDRAIL_VERSION", "")
        _categorizer = PromptCategorizer(
            model_id=model_id,
            region=region,
            s3_client=boto3.client("s3"),
            data_bucket=data_bucket,
            guardrail_id=guardrail_id,
            guardrail_version=guardrail_version,
        )
    return _categorizer


def _read_prompt_from_s3(request_id: str, s3_client=None) -> str:
    """Read prompt content from S3 for items stored externally.

    The prompt content is stored at ``prompts-content/{requestId}.json``
    in the DATA_BUCKET. The JSON file has the structure::

        {"prompt": "...", "response": "..."}

    Returns the prompt text, or empty string if not found.
    """
    data_bucket = os.environ.get("DATA_BUCKET", "")
    s3_key = f"prompts-content/{request_id}.json"

    client = s3_client or boto3.client("s3")
    response = client.get_object(Bucket=data_bucket, Key=s3_key)
    body = json.loads(response["Body"].read().decode("utf-8"))
    return body.get("prompt", "")


def categorize_prompt_handler(event, context):  # noqa: ARG001 - Lambda handler contract requires context parameter
    """CategorizePrompt Lambda entry point.

    Event from Map Standard::

        {
            "PK": "USER#...",
            "SK": "PROMPT#...",
            "requestId": "...",
            "contentInS3": true,
            "prompt": "..."  (only if inline)
        }

    Returns a result dict with status, category, and requestId.
    Propagates exceptions so Step Functions can retry with backoff.
    """
    pk = event.get("PK", "")
    sk = event.get("SK", "")
    request_id = event.get("requestId", "")
    content_in_s3 = event.get("contentInS3", False)
    inline_prompt = event.get("prompt", "")

    logger = StructuredLogger("categorize-prompt-lambda", request_id)

    logger.info(
        "Starting prompt categorization",
        PK=pk,
        SK=sk,
        requestId=request_id,
        contentInS3=content_in_s3,
    )

    try:
        # 1. Read prompt content
        if content_in_s3:
            prompt_text = _read_prompt_from_s3(request_id)
        else:
            # Prompt not in event payload — read from DynamoDB
            table_name = os.environ.get("ANALYTICS_TABLE", "")
            dynamodb = boto3.resource("dynamodb")
            table = dynamodb.Table(table_name)
            item_resp = table.get_item(Key={"PK": pk, "SK": sk})
            item = item_resp.get("Item", {})
            prompt_text = item.get("prompt", "")

        # 2. Categorize
        categorizer = _get_categorizer()
        category = categorizer.categorize(prompt_text)

        logger.info(
            "Prompt categorized",
            requestId=request_id,
            category=category,
        )

        # 3. Update DynamoDB — SET category on the prompt item
        table_name = os.environ.get("ANALYTICS_TABLE", "")
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)

        table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="SET category = :cat",
            ExpressionAttributeValues={":cat": category},
        )

        # 4. Increment category counter via AnalyticsWriter
        data_bucket = os.environ.get("DATA_BUCKET", "")
        writer = AnalyticsWriter(table_name, data_bucket)

        # Extract user_id from PK (format: "USER#{userId}")
        user_id = pk.replace("USER#", "", 1) if pk.startswith("USER#") else pk

        writer.increment_category_count(
            user_id,
            normalize_sk_value(category),
            category,
        )

        logger.info(
            "DynamoDB updated",
            requestId=request_id,
            category=category,
            PK=pk,
            SK=sk,
        )

        return {
            "status": "ok",
            "category": category,
            "requestId": request_id,
        }

    except Exception as exc:
        logger.error(
            "Failed to categorize prompt",
            requestId=request_id,
            PK=pk,
            SK=sk,
            errorType=type(exc).__name__,
            errorMessage=str(exc),
            stackTrace=traceback.format_exc(),
        )
        # Propagate exception so Step Functions can retry with backoff
        raise
