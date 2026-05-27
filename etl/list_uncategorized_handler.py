"""ListUncategorized Lambda handler — lists prompts pending categorization.

Entry point for the ListUncategorized Lambda invoked by the Step Functions
ETL pipeline after RecordStatus. Scans the Analytics_Table for prompt items
with category="NOT_CATEGORIZED", writes the list to S3 (to avoid the 256KB
Step Functions payload limit), and returns the S3 location for the
Distributed Map ItemReader.
"""

from __future__ import annotations

import json
import os
import traceback

import boto3

try:
    from shared.categories import CATEGORY_NOT_CATEGORIZED
    from shared.structured_logger import StructuredLogger
except ImportError:
    from shared.categories import CATEGORY_NOT_CATEGORIZED
    from utils.logging import StructuredLogger


def list_uncategorized_handler(event, context):  # noqa: ARG001 - Lambda handler contract requires context parameter
    """ListUncategorized Lambda entry point.

    Scans DynamoDB for prompt items with ``category = "NOT_CATEGORIZED"``,
    writes the list as JSON Lines to S3, and returns the S3 location.

    Returns::

        {
            "bucket": "data-bucket",
            "key": "categorization-pending/items.jsonl",
            "count": 42
        }
    """
    logger = StructuredLogger("list-uncategorized-lambda")

    table_name = os.environ.get("ANALYTICS_TABLE", "")
    data_bucket = os.environ.get("DATA_BUCKET", "")

    logger.info("Starting scan for uncategorized prompts", tableName=table_name)

    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        s3 = boto3.client("s3")

        uncategorized: list[dict] = []
        scan_kwargs: dict = {
            "FilterExpression": (
                boto3.dynamodb.conditions.Attr("SK").begins_with("PROMPT#")
                & boto3.dynamodb.conditions.Attr("category").eq(CATEGORY_NOT_CATEGORIZED)
            ),
            "ProjectionExpression": "PK, SK, requestId, contentInS3",
        }

        # Full pagination — scan all pages
        while True:
            response = table.scan(**scan_kwargs)

            for item in response.get("Items", []):
                uncategorized.append({
                    "PK": item["PK"],
                    "SK": item["SK"],
                    "requestId": item.get("requestId", ""),
                    "contentInS3": bool(item.get("contentInS3", False)),
                })

            if "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            else:
                break

        count = len(uncategorized)
        logger.info("Scan complete", uncategorizedCount=count)

        # Write to S3 as JSON array
        s3_key = "categorization-pending/items.json"
        s3.put_object(
            Bucket=data_bucket,
            Key=s3_key,
            Body=json.dumps(uncategorized).encode("utf-8"),
            ContentType="application/json",
        )

        logger.info("Written to S3", bucket=data_bucket, key=s3_key)

        return {
            "bucket": data_bucket,
            "key": s3_key,
            "count": count,
        }

    except Exception as exc:
        logger.error(
            "Failed to list uncategorized prompts",
            errorType=type(exc).__name__,
            errorMessage=str(exc),
            stackTrace=traceback.format_exc(),
        )
        raise
