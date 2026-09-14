"""Parse Lambda handler — reads an Amazon S3 file, parses, normalizes and resolves user names.

Entry point for the Parse Lambda invoked by the AWS Step Functions ETL pipeline.
Receives a single file reference from the Map state, processes it, and returns
normalized records ready for the Writer Lambda.
"""

from __future__ import annotations

import json
import os
import traceback

import boto3

if __package__:
    from .config import get_config
    from .sources import resolve_adapter
    from .sources.kiro_prompt_log import extract_path_metadata
    from .sts_session import get_identity_store_client, get_s3_client
    from .utils.name_resolver import resolve_names
else:  # Lambda loads this module from CodeUri as a top-level handler.
    from config import get_config
    from sources import resolve_adapter
    from sources.kiro_prompt_log import extract_path_metadata
    from sts_session import get_identity_store_client, get_s3_client
    from utils.name_resolver import resolve_names

try:
    from shared.structured_logger import StructuredLogger
except ImportError:
    from utils.logging import StructuredLogger

# 4KB threshold for inline vs S3 storage of prompt content. Moved here from
# AnalyticsWriter.write_prompt: the decision must happen BEFORE the Step
# Functions Task output is constructed, or a long response can push
# ParseAndNormalize's output past the 256KB Step Functions payload limit
# (States.DataLimitExceeded) before Writer ever runs.
_INLINE_THRESHOLD_BYTES = 4096

# Lazy singleton, reused across warm Lambda invocations. This is a plain
# same-account client for the ETL stack's OWN data bucket — NOT the
# cross_account_client used to read the (possibly cross-account) source
# bucket, and NOT interchangeable with it.
_data_bucket_s3_client = None


def _get_data_bucket_s3_client():
    """Return a lazily-initialized same-account S3 client for the data bucket."""
    global _data_bucket_s3_client  # noqa: PLW0603 - Singleton pattern for Lambda warm-start optimization
    if _data_bucket_s3_client is None:
        _data_bucket_s3_client = boto3.client("s3")
    return _data_bucket_s3_client


def _resolve_content_placement(
    records: list[dict],
    data_bucket: str,
    s3_client,
    logger: "StructuredLogger",
) -> None:
    """Decide inline vs S3 storage for each prompt record's content, in place.

    For every record whose combined UTF-8 byte size of ``prompt`` + ``response``
    exceeds _INLINE_THRESHOLD_BYTES, the content is written to
    ``prompts-content/{requestId}.json`` in *data_bucket* (same key format and
    JSON shape Writer used to produce), ``contentInS3`` is set to True, and
    ``prompt``/``response`` are cleared to empty strings so they never cross
    the Step Functions Task output boundary. Records at or below the
    threshold are left untouched aside from setting ``contentInS3`` to False.

    Mutates *records* in place. Raises on any S3 failure — deliberately not
    swallowed, so Step Functions retries ParseAndNormalize via its existing
    Retry clause instead of silently dropping prompt content.
    """
    for record in records:
        prompt = record.get("prompt", "")
        response = record.get("response", "")
        combined_size = len(prompt.encode("utf-8")) + len(response.encode("utf-8"))
        content_in_s3 = combined_size > _INLINE_THRESHOLD_BYTES
        record["contentInS3"] = content_in_s3

        if content_in_s3:
            request_id = record["requestId"]
            s3_key = f"prompts-content/{request_id}.json"
            s3_client.put_object(
                Bucket=data_bucket,
                Key=s3_key,
                Body=json.dumps(
                    {"prompt": prompt, "response": response},
                    ensure_ascii=False,
                ).encode("utf-8"),
                ContentType="application/json",
            )
            record["prompt"] = ""
            record["response"] = ""
            logger.info(
                "Prompt content moved to S3",
                requestId=request_id,
                combinedSizeBytes=combined_size,
                s3Key=s3_key,
            )


def _extract_prompt_path_metadata(s3_key: str, prompts_prefix: str) -> dict:
    """Compatibility wrapper for callers predating the adapter seam."""
    return extract_path_metadata(s3_key, prompts_prefix).as_prompt_mapping()


def _collect_user_ids(records: list[dict]) -> set[str]:
    """Collect unique non-empty userId values from a list of record dicts."""
    return {r["userId"] for r in records if r.get("userId")}


def parse_handler(event, context):  # noqa: ARG001 - Lambda handler contract requires context parameter
    """Parse Lambda entry point.

    Event from Step Functions::

        {
            "bucket": "source-bucket",
            "key": "activities/AWSLogs/.../file.csv",
            "fileType": "csv" | "prompt",
            "correlationId": "arn:aws:states:..."
        }

    Returns normalised records ready for the Writer Lambda.
    """
    bucket = event.get("bucket", "")
    key = event["key"]
    file_type = event["fileType"]
    correlation_id = event.get("correlationId", "")

    logger = StructuredLogger("parse-lambda", correlation_id)

    # Resolve config from SSM. Do NOT swallow failures here: a throttled SSM
    # read used to fall through to empty config, which made the cross-account
    # S3 client silently become the Lambda's own role and produced intermittent
    # cross-account AccessDenied at GetObject time. Let it raise so Step
    # Functions retries the task with backoff.
    cfg = get_config()
    identity_store_id = cfg.identity_store_id

    # Obtain cross-account S3 client. get_s3_client returns None ONLY when no
    # role ARN is configured (genuine single-account mode). An AssumeRole error
    # propagates so Step Functions retries — we must never fall back to the
    # Lambda's own role when a cross-account role IS configured, or we get a
    # misleading cross-account AccessDenied on the source bucket.
    cross_account_client = get_s3_client(
        cfg.source_bucket_role_arn,
        correlation_id=correlation_id,
    )

    # Obtain cross-account Identity Store client if configured (Req 4.1, 4.2, 4.3)
    # Fall back to None on any construction error so cache-only resolution still
    # completes (Req 8.5).
    try:
        identity_client = get_identity_store_client(
            cfg.identity_store_role_arn,
            correlation_id=correlation_id,
        )
    except Exception:
        identity_client = None

    user_names_table = os.environ.get("USER_NAMES_TABLE", "")

    # Resolve bucket from config if not in event
    if not bucket:
        bucket = cfg.bucket_name

    logger.info(
        "Starting parse",
        s3Key=key,
        fileType=file_type,
        bucket=bucket,
    )

    try:
        adapter = resolve_adapter(file_type)
        if not adapter.claim(key, cfg):
            logger.warning(
                "Unclaimed source key, returning empty",
                s3Key=key,
                sourceType=adapter.source_type,
            )
            records = []
        else:
            try:
                content = adapter.read(bucket, key, s3_client=cross_account_client)
            except Exception as exc:
                if "AccessDenied" in type(exc).__name__ or "AccessDenied" in str(exc):
                    logger.error(
                        adapter.access_denied_message,
                        bucket=bucket,
                        key=key,
                        errorType=type(exc).__name__,
                    )
                raise

            parsed = adapter.parse(content, key, cfg)
            records = adapter.normalize(parsed)

        # Resolve user names
        user_ids = _collect_user_ids(records)
        if user_ids:
            name_cache = resolve_names(
                user_ids=user_ids,
                identity_store_id=identity_store_id,
                table_name=user_names_table,
                identity_client=identity_client,
            )
            _enrich_records_with_names(records, name_cache)

        # Resolve inline-vs-S3 placement for prompt content BEFORE returning.
        # Must happen here, not in Writer, so an oversized prompt/response
        # never crosses the 256KB Step Functions Task payload limit between
        # Parse and Writer (see .kiro/specs/etl-parse-payload-size/).
        if adapter.requires_content_placement and records:
            data_bucket = os.environ.get("DATA_BUCKET", "")
            _resolve_content_placement(records, data_bucket, _get_data_bucket_s3_client(), logger)

        logger.info(
            "Parse complete",
            s3Key=key,
            fileType=file_type,
            recordCount=len(records),
        )

        return {
            "records": records,
            "key": key,
            "fileType": file_type,
            "recordCount": len(records),
        }

    except Exception as exc:
        logger.error(
            "Parse failed",
            s3Key=key,
            fileType=file_type,
            errorType=type(exc).__name__,
            errorMessage=str(exc),
            stackTrace=traceback.format_exc(),
        )
        raise



def _enrich_records_with_names(
    records: list[dict], name_cache: dict[str, tuple[str, str]]
) -> None:
    """Enrich records in-place with displayName and userName from the name cache."""
    for rec in records:
        user_id = rec.get("userId", "")
        if user_id and user_id in name_cache:
            display_name, user_name = name_cache[user_id]
            rec["displayName"] = display_name
            rec["userName"] = user_name
