"""Parse Lambda handler — reads an Amazon S3 file, parses, normalizes and resolves user names.

Entry point for the Parse Lambda invoked by the AWS Step Functions ETL pipeline.
Receives a single file reference from the Map state, processes it, and returns
normalized records ready for the Writer Lambda.
"""

from __future__ import annotations

import os
import re
import traceback

try:
    from processors.csv_processor import process_csv
    from processors.prompt_processor import process_prompts
    from s3_reader import read_csv_content
    from prompt_s3_reader import read_prompt_file
    from path_resolver import resolve_path_metadata
    from utils.name_resolver import resolve_names
    from config import get_config
    from sts_session import get_s3_client, get_identity_store_client
except ImportError:
    from etl.processors.csv_processor import process_csv
    from etl.processors.prompt_processor import process_prompts
    from etl.s3_reader import read_csv_content
    from etl.prompt_s3_reader import read_prompt_file
    from etl.path_resolver import resolve_path_metadata
    from etl.utils.name_resolver import resolve_names
    from etl.config import get_config
    from etl.sts_session import get_s3_client, get_identity_store_client

try:
    from shared.structured_logger import StructuredLogger
except ImportError:
    from utils.logging import StructuredLogger


def _extract_prompt_path_metadata(s3_key: str, prompts_prefix: str) -> dict:
    """Extract region and accountId from a prompt file S3 key.

    Path pattern:
        {prompts_prefix}GenerateAssistantResponse/{region}/{year}/{month}/{day}/{hour}/*.json.gz

    AccountId is extracted from the prompts_prefix
    (e.g. ``prompts/AWSLogs/{accountId}/KiroLogs/``).
    """
    metadata: dict = {"region": "", "accountId": ""}

    relative = s3_key.removeprefix(prompts_prefix)
    parts = relative.split("/")
    if len(parts) >= 2 and parts[0] == "GenerateAssistantResponse":
        metadata["region"] = parts[1]

    account_match = re.search(r"/(\d{12})/", prompts_prefix)
    if account_match:
        metadata["accountId"] = account_match.group(1)

    return metadata


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
    source_prefix = cfg.source_prefix
    prompts_prefix = cfg.prompts_prefix
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
        if file_type == "csv":
            records = _process_csv_file(bucket, key, source_prefix, logger, s3_client=cross_account_client)
        elif file_type == "prompt":
            records = _process_prompt_file(bucket, key, prompts_prefix, logger, s3_client=cross_account_client)
        else:
            raise ValueError(f"Unknown fileType: {file_type}")

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


def _process_csv_file(
    bucket: str, key: str, source_prefix: str, logger: StructuredLogger, s3_client=None
) -> list[dict]:
    """Read and process a CSV activity file."""
    metadata = resolve_path_metadata(key, source_prefix)
    if metadata is None:
        logger.warning("Unrecognised CSV path, returning empty", s3Key=key)
        return []

    try:
        csv_content = read_csv_content(bucket, key, s3_client=s3_client)
    except Exception as exc:
        if "AccessDenied" in type(exc).__name__ or "AccessDenied" in str(exc):
            # errorMessage/response deliberately omitted: a boto3
            # AccessDenied error can echo the assumed role ARN and other
            # cross-account request metadata. Only the error's class name
            # and the bucket/key already known to the caller are logged.
            logger.error(
                "Acesso negado ao ler arquivo CSV. Verifique as permissões da Role_Origem.",
                bucket=bucket,
                key=key,
                errorType=type(exc).__name__,
            )
        raise
    format_type = metadata["format_type"]
    return process_csv(csv_content, format_type, metadata)


def _process_prompt_file(
    bucket: str, key: str, prompts_prefix: str, logger: StructuredLogger, s3_client=None
) -> list[dict]:
    """Read and process a .json.gz prompt file."""
    path_metadata = _extract_prompt_path_metadata(key, prompts_prefix)
    try:
        gzipped_content = read_prompt_file(bucket, key, s3_client=s3_client)
    except Exception as exc:
        if "AccessDenied" in type(exc).__name__ or "AccessDenied" in str(exc):
            # errorMessage/response deliberately omitted — see the matching
            # comment in _process_csv_file above.
            logger.error(
                "Acesso negado ao ler arquivo de prompt. Verifique as permissões da Role_Origem.",
                bucket=bucket,
                key=key,
                errorType=type(exc).__name__,
            )
        raise
    # Pass empty name_cache — names are resolved after processing
    return process_prompts(gzipped_content, path_metadata, {})


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
