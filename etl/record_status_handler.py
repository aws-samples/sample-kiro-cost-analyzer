"""RecordStatus Lambda handler — records ETL execution summary to SSM.

Entry point for the RecordStatus Lambda invoked as the final step of the
Step Functions ETL pipeline. Reads child execution results from S3
(written by the Distributed Map ResultWriter), computes a summary, and
writes the execution status to SSM Parameter Store.
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone

import boto3

try:
    from shared.structured_logger import StructuredLogger
except ImportError:
    from utils.logging import StructuredLogger


def _read_map_results_from_s3(
    bucket: str, key: str, logger: StructuredLogger | None = None
) -> tuple[list[dict], int]:
    """Read the Distributed Map ResultWriter manifest from S3 and collect child results.

    Raises on manifest fetch/parse failure so the state machine fails loudly instead
    of reporting a false-positive success. Individual child-result read failures are
    logged and counted as failed files, but do not stop the function.

    Returns:
        Tuple of (results, read_failures). ``read_failures`` is the count of child
        result files that could not be fetched or parsed; callers should add it to
        ``filesFailed``.
    """
    s3 = boto3.client("s3")

    # Manifest fetch failure propagates — do not mask it as success.
    resp = s3.get_object(Bucket=bucket, Key=key)
    manifest = json.loads(resp["Body"].read().decode("utf-8"))

    results: list[dict] = []
    read_failures = 0

    for group in ("SUCCEEDED", "FAILED"):
        for item in manifest.get("ResultFiles", {}).get(group, []):
            result_key = item.get("Key", "")
            try:
                resp = s3.get_object(Bucket=bucket, Key=result_key)
                child_results = json.loads(resp["Body"].read().decode("utf-8"))
            except Exception as exc:
                if logger is not None:
                    logger.error(
                        "Failed to read child result file",
                        resultKey=result_key,
                        resultGroup=group,
                        errorType=type(exc).__name__,
                        errorMessage=str(exc),
                    )
                read_failures += 1
                continue

            items = child_results if isinstance(child_results, list) else [child_results]
            if group == "FAILED":
                items = [_normalize_failed_item(r) for r in items if isinstance(r, dict)]
            results.extend(items)

    return results, read_failures


def _normalize_failed_item(item: dict) -> dict:
    """Normalize a Distributed Map FAILED result into the shape _compute_summary expects.

    AWS writes FAILED entries with top-level ``Cause``, ``Error``, and ``Input`` (JSON
    string). We convert to ``{status, key, error: {Cause, Error}}`` so downstream code
    can extract the file key and format a readable error message.
    """
    normalized: dict = {"status": "ERROR"}
    try:
        parsed_input = json.loads(item.get("Input", "{}"))
        normalized["key"] = parsed_input.get("key", "unknown")
    except (json.JSONDecodeError, TypeError):
        normalized["key"] = "unknown"
    normalized["error"] = {
        "Cause": item.get("Cause", ""),
        "Error": item.get("Error", ""),
    }
    return normalized


def _compute_summary(map_results: list[dict]) -> dict:
    """Parse mapResults to compute execution summary.

    Each item in mapResults is either:
    - A success result with markResult (file processed OK)
    - An error result:  {"status": "ERROR", "key": "...", "error": {...}}

    Returns a dict with success/failure counts, totals, and error details.
    """
    files_success = 0
    files_failed = 0
    total_records = 0
    total_items_written = 0
    errors: list[str] = []

    for result in map_results:
        if not isinstance(result, dict) or result.get("status") == "ERROR" or "error" in result:
            files_failed += 1
            key = (result or {}).get("key", "unknown") if isinstance(result, dict) else "unknown"
            error_info = (result or {}).get("error", {}) if isinstance(result, dict) else {}
            errors.append(_format_error(key, error_info))
        else:
            files_success += 1
            write_result = result.get("writeResult", {})
            total_records += int(write_result.get("recordCount", 0))
            total_items_written += int(write_result.get("itemsWritten", 0))

    return {
        "filesSuccess": files_success,
        "filesFailed": files_failed,
        "totalRecords": total_records,
        "totalItemsWritten": total_items_written,
        "errors": errors,
    }


def _format_error(key: str, error_info: dict) -> str:
    """Format an error entry into a human-readable string."""
    if isinstance(error_info, dict):
        cause = error_info.get("Cause", error_info.get("cause", ""))
        error_type = error_info.get("Error", error_info.get("error", ""))
        # Lambda-level Cause is a JSON-encoded dict with errorMessage/errorType/stackTrace.
        # Extract just the human-readable bits to keep the SSM payload compact.
        if cause:
            try:
                cause_obj = json.loads(cause)
            except (json.JSONDecodeError, TypeError):
                cause_obj = None
            if isinstance(cause_obj, dict):
                msg = cause_obj.get("errorMessage", "")
                etype = cause_obj.get("errorType", "")
                if msg or etype:
                    cause = f"{etype}: {msg}" if etype and msg else (msg or etype)
            return f"Error processing {key}: {cause}"[:200]
        if error_type:
            return f"Error processing {key}: {error_type}"[:200]
    return f"Error processing {key}: {error_info}"[:200]


def record_status_handler(event, context):  # noqa: ARG001 - Lambda handler contract requires context parameter
    """RecordStatus Lambda entry point.

    Event from Step Functions (Distributed Map)::

        {
            "executionId": "arn:aws:states:...",
            "listResult": { ... },
            "mapResultsBucket": "data-bucket",
            "mapResultsKey": "etl-results/.../manifest.json"
        }
    """
    execution_id = event.get("executionId", "")
    list_result = event.get("listResult", {})
    results_bucket = event.get("mapResultsBucket", "")
    results_key = event.get("mapResultsKey", "")

    logger = StructuredLogger("record-status-lambda", execution_id)
    ssm_param = os.environ.get("SSM_ETL_STATUS", "")

    logger.info(
        "Computing execution summary",
        newFilesCount=list_result.get("newFilesCount", 0),
        resultsBucket=results_bucket,
        resultsKey=results_key,
    )

    try:
        # Read child execution results from S3. Manifest read failures propagate —
        # we must not convert them into a false-positive success.
        map_results: list[dict] = []
        read_failures = 0
        if results_bucket and results_key:
            map_results, read_failures = _read_map_results_from_s3(
                results_bucket, results_key, logger
            )

        logger.info(
            "Map results loaded",
            mapResultsCount=len(map_results),
            readFailures=read_failures,
        )

        summary = _compute_summary(map_results)
        summary["filesFailed"] += read_failures

        status = "ERROR" if summary["filesFailed"] > 0 else "SUCCESS"

        # Truncate errors to fit SSM Standard tier 4096 char limit
        truncated_errors = [e[:200] for e in summary["errors"][:10]]

        payload = {
            "lastExecution": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "filesProcessed": summary["filesSuccess"],
            "recordsWritten": summary["totalItemsWritten"],
            "errors": truncated_errors,
        }

        value = json.dumps(payload)
        if len(value) > 4000:
            payload["errors"] = [f"{len(summary['errors'])} errors (truncated)"]
            value = json.dumps(payload)

        ssm = boto3.client("ssm")
        ssm.put_parameter(
            Name=ssm_param,
            Value=value,
            Type="String",
            Overwrite=True,
        )

        if summary["filesFailed"] > 0:
            logger.error(
                "ETL execution had failed files",
                filesFailed=summary["filesFailed"],
                filesSuccess=summary["filesSuccess"],
                errorSample=truncated_errors[0] if truncated_errors else "",
            )

        logger.info(
            "Execution status recorded",
            status=status,
            filesProcessed=summary["filesSuccess"],
            filesFailed=summary["filesFailed"],
            totalRecords=summary["totalRecords"],
            totalItemsWritten=summary["totalItemsWritten"],
            errorCount=len(summary["errors"]),
        )

        return {
            "status": status,
            "filesProcessed": summary["filesSuccess"],
            "filesFailed": summary["filesFailed"],
            "recordsWritten": summary["totalItemsWritten"],
            "errors": truncated_errors,
        }

    except Exception as exc:
        logger.error(
            "Failed to record execution status",
            errorType=type(exc).__name__,
            errorMessage=str(exc),
            stackTrace=traceback.format_exc(),
        )
        raise
