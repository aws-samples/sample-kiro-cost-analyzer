"""Handler for GET /api/etl/executions — recent ETL execution history.

Joins two sources, because neither holds the whole picture:

- Step Functions ``ListExecutions`` is authoritative for timing and outcome. The
  ETL state machine is a Standard type, so this history is available for 90 days
  and covers runs that crashed before reaching the RecordStatus step.
- DynamoDB items under ``PK=ETL_STATUS`` / ``SK=EXEC#{executionName}`` carry the
  per-run counters (files processed, records written) that Step Functions does
  not track.

Counters are ``None`` when no record exists for an execution, which distinguishes
"not known" from a run that genuinely processed zero files.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

ETL_STATUS_PK = "ETL_STATUS"
EXEC_SK_PREFIX = "EXEC#"

DEFAULT_DAYS = 5
MIN_DAYS = 1
MAX_DAYS = 30


def _get_sfn_client(sfn_client=None):
    """Return the provided client or create a new Step Functions client."""
    return sfn_client or boto3.client("stepfunctions")


def _get_dynamodb_resource(dynamodb_resource=None):
    """Return the provided resource or create a new DynamoDB resource."""
    return dynamodb_resource or boto3.resource("dynamodb")


def _parse_days(query_params: dict) -> int:
    """Parse and clamp the ``days`` query parameter.

    Total function: an absent, empty, or non-numeric value yields the default,
    and any numeric value is clamped into the supported range.

    Args:
        query_params: API Gateway query string parameters.

    Returns:
        An integer in the range MIN_DAYS..MAX_DAYS inclusive.
    """
    raw = (query_params or {}).get("days")

    try:
        days = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_DAYS

    return max(MIN_DAYS, min(MAX_DAYS, days))


def _to_iso(value) -> str | None:
    """Render a boto3 datetime as an ISO 8601 string, tolerating other shapes."""
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _elapsed_seconds(start, stop) -> int | None:
    """Compute whole seconds between two datetimes, or None when incomplete.

    Returns None when either bound is missing (a running execution has no stop
    time) or when the difference is negative, which should not happen but must
    not produce a nonsensical value if it does.
    """
    if not isinstance(start, datetime) or not isinstance(stop, datetime):
        return None
    seconds = int((stop - start).total_seconds())
    return seconds if seconds >= 0 else None


def _load_execution_records(table_name: str, dynamodb_resource=None) -> dict:
    """Load every persisted execution record, keyed by execution name.

    One query over a small partition is cheaper than a lookup per execution and
    stays correct regardless of the requested window.

    Args:
        table_name: Analytics table name.
        dynamodb_resource: Optional pre-configured DynamoDB resource for testing.

    Returns:
        Mapping of execution name to its record. Empty when the table is unset.
    """
    if not table_name:
        return {}

    table = _get_dynamodb_resource(dynamodb_resource).Table(table_name)
    records: dict = {}
    kwargs = {
        "KeyConditionExpression": Key("PK").eq(ETL_STATUS_PK)
        & Key("SK").begins_with(EXEC_SK_PREFIX)
    }

    while True:
        response = table.query(**kwargs)
        for item in response.get("Items", []):
            name = str(item.get("SK", ""))[len(EXEC_SK_PREFIX) :]
            if name:
                records[name] = item
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key

    return records


def _counter(record: dict | None, field: str) -> int | None:
    """Read an integer counter from a record, or None when unavailable."""
    if not record or field not in record:
        return None
    try:
        return int(record[field])
    except (TypeError, ValueError):
        return None


def handle_etl_executions(
    query_params: dict, sfn_client=None, dynamodb_resource=None
) -> dict:
    """Handle GET /api/etl/executions — list recent ETL executions.

    Args:
        query_params: API Gateway query string parameters. Supports ``days``.
        sfn_client: Optional pre-configured Step Functions client for testing.
        dynamodb_resource: Optional pre-configured DynamoDB resource for testing.

    Returns:
        Dict with the resolved window and the executions, most recent first.
    """
    days = _parse_days(query_params)
    state_machine_arn = os.environ.get("STATE_MACHINE_ARN", "")

    if not state_machine_arn:
        return {"days": days, "executions": []}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    client = _get_sfn_client(sfn_client)

    # Step Functions returns executions most recent first, so the first result
    # older than the cutoff ends the scan — the full 90-day history is never walked.
    raw_executions: list[dict] = []
    reached_cutoff = False
    paginator = client.get_paginator("list_executions")

    for page in paginator.paginate(stateMachineArn=state_machine_arn):
        for execution in page.get("executions", []):
            start = execution.get("startDate")
            if isinstance(start, datetime) and start < cutoff:
                reached_cutoff = True
                break
            raw_executions.append(execution)
        if reached_cutoff:
            break

    records = _load_execution_records(
        os.environ.get("ANALYTICS_TABLE", ""), dynamodb_resource
    )

    executions = []
    for execution in raw_executions:
        name = execution.get("name", "")
        record = records.get(name)
        start = execution.get("startDate")
        stop = execution.get("stopDate")

        executions.append(
            {
                "executionName": name,
                "startDate": _to_iso(start),
                "stopDate": _to_iso(stop),
                "elapsedSeconds": _elapsed_seconds(start, stop),
                "status": execution.get("status", "UNKNOWN"),
                "filesProcessed": _counter(record, "filesProcessed"),
                "recordsWritten": _counter(record, "recordsWritten"),
            }
        )

    return {"days": days, "executions": executions}
