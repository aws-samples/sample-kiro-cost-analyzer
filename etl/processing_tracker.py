"""Processing tracker — controls which Amazon S3 files have already been processed via Amazon DynamoDB."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Set

import boto3


def get_processed_keys(table_name: str, dynamodb=None) -> Set[str]:
    """Return the set of S3 keys already processed.

    Scans the DynamoDB *ProcessedFilesTable* and collects every ``fileKey``
    value into a set.
    """
    if dynamodb is None:
        dynamodb = boto3.resource("dynamodb")

    table = dynamodb.Table(table_name)
    processed: Set[str] = set()

    response = table.scan(ProjectionExpression="fileKey")
    processed.update(item["fileKey"] for item in response.get("Items", []))

    while response.get("LastEvaluatedKey"):
        response = table.scan(
            ProjectionExpression="fileKey",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        processed.update(item["fileKey"] for item in response.get("Items", []))

    return processed


def mark_as_processed(
    table_name: str,
    key: str,
    record_count: int,
    status: str,
    error_message: str = "",
    dynamodb=None,
) -> None:
    """Record a processed file in DynamoDB.

    Writes an item with ``fileKey``, ``processedAt`` (ISO 8601),
    ``recordCount``, ``status`` (SUCCESS / ERROR), and ``errorMessage``.
    """
    if dynamodb is None:
        dynamodb = boto3.resource("dynamodb")

    table = dynamodb.Table(table_name)
    table.put_item(
        Item={
            "fileKey": key,
            "processedAt": datetime.now(timezone.utc).isoformat(),
            "recordCount": record_count,
            "status": status,
            "errorMessage": error_message,
        }
    )


def filter_new_files(all_keys: List[str], processed_keys: Set[str]) -> List[str]:
    """Return only the keys that have not been processed yet."""
    return [k for k in all_keys if k not in processed_keys]
