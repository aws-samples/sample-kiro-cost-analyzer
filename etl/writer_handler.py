"""Writer Lambda handler — persists parsed records to DynamoDB and S3.

Entry point for the Writer Lambda invoked by the Step Functions ETL pipeline.
Receives normalized records from the Parse Lambda and writes them to the
Analytics_Table via AnalyticsWriter.
"""

from __future__ import annotations

import os
import time

from shared.analytics_writer import AnalyticsWriter

if __package__:
    from .sources import resolve_adapter
else:  # Lambda loads this module from CodeUri as a top-level handler.
    from sources import resolve_adapter
from shared.categories import CATEGORY_NOT_CATEGORIZED
from shared.structured_logger import StructuredLogger
from shared.sk_normalizer import normalize_sk_value


def writer_handler(event, context):  # noqa: ARG001 - Lambda handler contract requires context parameter
    """Writer Lambda entry point.

    Event from Step Functions::

        {
            "records": [...],
            "fileType": "csv" | "prompt",
            "key": "...",
            "correlationId": "arn:aws:states:..."
        }

    Returns a result dict with recordCount, itemsWritten, and durationMs.
    """
    records = event.get("records", [])
    file_type = event["fileType"]
    key = event.get("key", "")
    correlation_id = event.get("correlationId", "")

    logger = StructuredLogger("writer-lambda", correlation_id)

    table_name = os.environ.get("ANALYTICS_TABLE", "")
    data_bucket = os.environ.get("DATA_BUCKET", "")

    writer = AnalyticsWriter(table_name, data_bucket)

    logger.info(
        "Starting write",
        s3Key=key,
        fileType=file_type,
        recordCount=len(records),
    )

    start = time.time()
    items_written = 0

    try:
        adapter = resolve_adapter(file_type)
        for record in records:
            if adapter.record_kind == "activity":
                items_written += _write_activity_record(writer, record, logger)
            elif adapter.record_kind == "prompt":
                items_written += _write_prompt_record(writer, record, logger)
            else:
                raise ValueError(
                    f"Unsupported record kind for {adapter.source_type}: "
                    f"{adapter.record_kind}"
                )

        duration_ms = int((time.time() - start) * 1000)

        logger.info(
            "Write complete",
            s3Key=key,
            fileType=file_type,
            recordCount=len(records),
            itemsWritten=items_written,
            durationMs=duration_ms,
        )

        return {
            "recordCount": len(records),
            "itemsWritten": items_written,
            "durationMs": duration_ms,
        }

    except Exception as exc:
        # errorMessage/stackTrace deliberately omitted: records processed
        # here can carry user-submitted prompt/response content, which an
        # exception message or traceback could echo back. Only the
        # exception's class name is logged.
        duration_ms = int((time.time() - start) * 1000)
        logger.error(
            "Write failed",
            s3Key=key,
            fileType=file_type,
            errorType=type(exc).__name__,
            durationMs=duration_ms,
        )
        raise


def _write_activity_record(writer: AnalyticsWriter, record: dict, logger: StructuredLogger) -> int:
    """Write one normalized activity record. Returns number of items written."""
    user_id = record["userId"]
    date = record["date"]

    def present(key: str, cast):
        return cast(record[key]) if key in record else None

    credits = present("totalCredits", float)
    overage = present("overageCredits", float)
    messages = present("totalMessages", int)
    conversations = present("totalConversations", int)
    interactions = present("totalInteractions", int)
    input_tokens = present("inputTokens", int)
    output_tokens = present("outputTokens", int)
    cache_read_tokens = present("cacheReadTokens", int)
    cache_write_tokens = present("cacheWriteTokens", int)
    estimated_cost_usd = present("estimatedCostUsd", float)
    tier = record.get("subscriptionTier", "")
    client_type = record.get("clientType", "")

    optional_metrics = {
        "interactions": interactions,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "estimated_cost_usd": estimated_cost_usd,
    }

    writer.increment_daily_stats(
        user_id,
        date,
        credits,
        overage,
        messages,
        conversations,
        interactions,
        subscription_tier=tier,
        client_type=client_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )

    writer.increment_global_daily_stats(
        date,
        credits,
        overage,
        messages,
        conversations,
        {user_id},
        **optional_metrics,
    )

    items = 2

    # Breakdown by tier
    if tier:
        writer.increment_global_tier_stats(
            date,
            tier,
            credits,
            overage,
            messages,
            conversations,
            **optional_metrics,
        )
        items += 1

    # Breakdown by client type
    if client_type:
        writer.increment_global_client_type_stats(
            date,
            client_type,
            credits,
            overage,
            messages,
            conversations,
            **optional_metrics,
        )
        items += 1

    # Upsert activity summary (best-effort — don't fail the record)
    try:
        writer.upsert_activity_summary(user_id, date)
        items += 1
    except Exception as exc:
        logger.error(
            "upsert_activity_summary failed",
            userId=user_id,
            date=date,
            errorType=type(exc).__name__,
        )

    # Persist model messages and newUser metadata (best-effort)
    model_messages = record.get("modelMessages")
    new_user = record.get("newUser", False)
    if model_messages or new_user:
        try:
            writer.set_daily_stats_metadata(user_id, date, model_messages, new_user)
            items += 1
        except Exception as exc:
            logger.error(
                "set_daily_stats_metadata failed",
                userId=user_id,
                date=date,
                errorType=type(exc).__name__,
            )

    return items


def _write_csv_record(writer: AnalyticsWriter, record: dict, logger: StructuredLogger) -> int:
    """Compatibility alias for callers predating the source-adapter seam."""
    return _write_activity_record(writer, record, logger)


def _write_prompt_record(writer: AnalyticsWriter, record: dict, logger: StructuredLogger) -> int:
    """Write a single prompt record. Returns number of items written."""
    user_id = record["userId"]
    date = record.get("date", record.get("timestamp", "")[:10])
    model_id = record.get("modelId", "")
    trigger_type = record.get("triggerType", "")
    prompt = record.get("prompt", "")
    response = record.get("response", "")
    # Placement decision is made upstream by Parse (before the Step Functions
    # Task output is constructed, to stay under the 256KB payload limit).
    # Default False handles in-flight Map children still running the
    # previous Parse output during a deploy window — that output always
    # carries real inline content and never set this key.
    content_in_s3 = record.get("contentInS3", False)

    items = 0

    # 1. Write prompt metadata (PutItem) — handles inline vs S3
    writer.write_prompt(user_id, record, prompt, response, content_in_s3, category=CATEGORY_NOT_CATEGORIZED)
    items += 1

    # 2. Increment daily stats (interactions only)
    writer.increment_daily_stats(user_id, date, 0, 0, 0, 0, 1)
    items += 1

    # 3. Increment model distribution
    if model_id:
        writer.increment_model_count(
            user_id,
            normalize_sk_value(model_id),
            model_id,
        )
        items += 1

    # 4. Increment trigger distribution
    if trigger_type:
        writer.increment_trigger_count(
            user_id,
            normalize_sk_value(trigger_type),
            trigger_type,
        )
        items += 1

    # 5. Increment global daily stats
    writer.increment_global_daily_stats(date, 0, 0, 0, 0, {user_id})
    items += 1

    # 6. Upsert activity summary (best-effort — don't fail the record)
    try:
        writer.upsert_activity_summary(user_id, date)
        items += 1
    except Exception as exc:
        logger.error(
            "upsert_activity_summary failed",
            userId=user_id,
            date=date,
            errorType=type(exc).__name__,
        )

    return items
