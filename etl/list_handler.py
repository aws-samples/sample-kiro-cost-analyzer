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

if __package__:
    from .config import get_config
    from .processing_tracker import filter_new_files, get_processed_keys
    from .sources import discover_files
    from .sts_session import get_s3_client
else:  # Lambda loads this module from CodeUri as a top-level handler.
    from config import get_config
    from processing_tracker import filter_new_files, get_processed_keys
    from sources import discover_files
    from sts_session import get_s3_client

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

        discovery = discover_files(
            cfg.bucket_name,
            cfg,
            s3_client=cross_account_client,
        )
        for count_key, count in discovery.counts.items():
            logger.info("Source files found", sourceCountKey=count_key, sourceFileCount=count)
        for key in discovery.unclaimed_keys:
            logger.warning("Unclaimed source key skipped", s3Key=key)

        # Get already-processed keys
        processed_keys = get_processed_keys(processed_table)
        logger.info("Processed keys loaded", processedCount=len(processed_keys))

        # Preserve registry discovery order while filtering processed objects.
        all_keys = [item.key for item in discovery.files]
        adapter_by_key = {item.key: item.adapter for item in discovery.files}
        new_keys = filter_new_files(all_keys, processed_keys)

        total_new = len(new_keys)

        # Cap at MAX_BATCH_SIZE to stay under payload limit
        batch_keys = new_keys[:MAX_BATCH_SIZE]
        has_more = total_new > MAX_BATCH_SIZE

        # Existing Kiro adapters deliberately emit their historical wire types
        # (csv/prompt). Canonical names are accepted by Parse/Writer but are not
        # emitted here, avoiding new-List/old-Parse rolling-deploy hazards.
        new_files = [
            {
                "key": key,
                "fileType": adapter_by_key[key].wire_type,
            }
            for key in batch_keys
        ]

        total_csv = discovery.counts.get("totalCsvFiles", 0)
        total_prompt = discovery.counts.get("totalPromptFiles", 0)
        result = {
            "bucket": cfg.bucket_name,
            "newFiles": new_files,
            "newFilesCount": len(new_files),
            "totalNewFiles": total_new,
            "hasMore": has_more,
            "totalCsvFiles": total_csv,
            "totalPromptFiles": total_prompt,
            "processedCount": len(processed_keys),
        }

        logger.info(
            "File listing complete",
            newFilesCount=len(new_files),
            totalNewFiles=total_new,
            hasMore=has_more,
            totalCsvFiles=total_csv,
            totalPromptFiles=total_prompt,
            processedCount=len(processed_keys),
        )

        return result

    except Exception as exc:
        # Deliberately generic: `errorMessage`/`stackTrace` from an arbitrary
        # exception can echo back sensitive data (S3 keys, ARNs, credential
        # fragments surfaced by a boto3 ClientError message, etc). Only the
        # exception's class name is logged. Step Functions still receives
        # the full traceback via its own execution history for debugging.
        logger.error(
            "File listing failed",
            errorType=type(exc).__name__,
        )
        raise
