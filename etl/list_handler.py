"""ListFiles Lambda handler — lists new S3 files not yet processed.

Entry point for the ListFiles Lambda invoked as the first step of the
Step Functions ETL pipeline. Lists CSV and prompt files from S3, checks
the ProcessedFilesTable, and returns only new (unprocessed) files with
metadata for the Map state.

To stay within the Step Functions 256 KB payload limit, the bucket name
is returned once at the top level (not per file) and results are capped
at MAX_BATCH_SIZE files per invocation.  The state machine should loop
when ``hasMore`` is ``true``.
"""

from __future__ import annotations

import os
import traceback

try:
    from config import get_config
    from processing_tracker import filter_new_files, get_processed_keys
    from prompt_s3_reader import list_prompt_files
    from s3_reader import list_csv_files
    from sts_session import get_s3_client
except ImportError:
    from etl.config import get_config
    from etl.processing_tracker import filter_new_files, get_processed_keys
    from etl.prompt_s3_reader import list_prompt_files
    from etl.s3_reader import list_csv_files
    from etl.sts_session import get_s3_client

try:
    from shared.structured_logger import StructuredLogger
except ImportError:
    from utils.logging import StructuredLogger

# Max files per batch to stay within the Step Functions 256 KB payload limit.
# Each file entry is ~80 bytes (key + fileType), so 500 files ≈ 40 KB.
# The state machine loops via hasMore when there are more files to process.
MAX_BATCH_SIZE = 500


def list_handler(event, context):  # noqa: ARG001 - Lambda handler contract requires context parameter
    """ListFiles Lambda entry point.

    Returns a dict consumed by the state machine::

        {
            "bucket": "source-bucket",
            "newFiles": [
                {"key": "...", "fileType": "csv"},
                {"key": "...", "fileType": "prompt"},
            ],
            "newFilesCount": 42,
            "totalNewFiles": 1200,
            "hasMore": true,
            "totalCsvFiles": 100,
            "totalPromptFiles": 200,
            "processedCount": 258,
        }
    """
    correlation_id = ""
    if isinstance(event, dict):
        correlation_id = event.get("correlationId", "")

    logger = StructuredLogger("list-files-lambda", correlation_id)

    processed_table = os.environ.get("PROCESSED_FILES_TABLE", "")

    logger.info("Starting file listing")

    try:
        cfg = get_config()

        # Obtain cross-account S3 client if configured
        cross_account_client = get_s3_client(
            cfg.source_bucket_role_arn,
            correlation_id=correlation_id,
        )

        # List CSV files
        csv_keys = list_csv_files(cfg.bucket_name, cfg.source_prefix, s3_client=cross_account_client)
        logger.info("CSV files found", totalCsvFiles=len(csv_keys))

        # List prompt files
        prompt_keys: list[str] = []
        if cfg.prompts_prefix:
            prompt_keys = list_prompt_files(cfg.bucket_name, cfg.prompts_prefix, s3_client=cross_account_client)
            logger.info("Prompt files found", totalPromptFiles=len(prompt_keys))

        # Get already-processed keys
        processed_keys = get_processed_keys(processed_table)
        logger.info("Processed keys loaded", processedCount=len(processed_keys))

        # Combine all keys and filter new ones
        all_keys = csv_keys + prompt_keys
        new_keys = filter_new_files(all_keys, processed_keys)

        total_new = len(new_keys)

        # Cap at MAX_BATCH_SIZE to stay under payload limit
        batch_keys = new_keys[:MAX_BATCH_SIZE]
        has_more = total_new > MAX_BATCH_SIZE

        # Build result list with full field names for Step Functions Map ItemSelector
        csv_keys_set = set(csv_keys)
        new_files = []
        for key in batch_keys:
            file_type = "csv" if key in csv_keys_set else "prompt"
            new_files.append({
                "key": key,
                "fileType": file_type,
            })

        result = {
            "bucket": cfg.bucket_name,
            "newFiles": new_files,
            "newFilesCount": len(new_files),
            "totalNewFiles": total_new,
            "hasMore": has_more,
            "totalCsvFiles": len(csv_keys),
            "totalPromptFiles": len(prompt_keys),
            "processedCount": len(processed_keys),
        }

        logger.info(
            "File listing complete",
            newFilesCount=len(new_files),
            totalNewFiles=total_new,
            hasMore=has_more,
            totalCsvFiles=len(csv_keys),
            totalPromptFiles=len(prompt_keys),
            processedCount=len(processed_keys),
        )

        return result

    except Exception as exc:
        logger.error(
            "File listing failed",
            errorType=type(exc).__name__,
            errorMessage=str(exc),
            stackTrace=traceback.format_exc(),
        )
        raise
