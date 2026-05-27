"""Prompt Processor — parses .json.gz prompt files and normalizes records for DynamoDB writes.

Reuses the existing prompt_parser and prompt_normalizer modules, converting their
output into dicts ready for the AnalyticsWriter (PutItem for PROMPT# items).
"""

from __future__ import annotations

try:
    from prompt_parser import parse_prompt_file
    from prompt_normalizer import normalize_prompt_records, extract_uuid
except ImportError:
    from etl.prompt_parser import parse_prompt_file
    from etl.prompt_normalizer import normalize_prompt_records, extract_uuid


def process_prompts(
    gzipped_content: bytes,
    path_metadata: dict,
    name_cache: dict[str, tuple[str, str]],
) -> list[dict]:
    """Parse and normalize a .json.gz prompt file, returning records ready for DynamoDB writes.

    Each returned dict contains the fields needed by AnalyticsWriter.write_prompt
    and the counter-increment methods:
      - userId, timestamp, requestId, modelId, triggerType, promptLength, responseLength,
        displayName, userName, region, accountId, conversationId, utteranceId,
        customizationArn, date, hour, originalUserId, prompt, response

    Parameters
    ----------
    gzipped_content:
        Raw gzipped bytes of the .json.gz prompt log file.
    path_metadata:
        Path metadata dict (from path_resolver) with ``region`` and ``accountId``.
    name_cache:
        Mapping of userId (UUID) → (displayName, userName) for name enrichment.

    Returns
    -------
    list[dict]
        One dict per normalised prompt record, ready for DynamoDB writes.
    """
    raw_records = parse_prompt_file(gzipped_content)
    if not raw_records:
        return []

    normalized = normalize_prompt_records(raw_records, path_metadata, name_cache)

    return [_to_dynamo_record(rec, raw, path_metadata) for rec, raw in zip(normalized, raw_records)]


def _to_dynamo_record(rec, raw, path_metadata: dict) -> dict:
    """Convert a PromptRecord + raw record into a flat dict for DynamoDB writes."""
    return {
        "userId": rec.userId,
        "originalUserId": rec.originalUserId,
        "timestamp": rec.timestamp,
        "requestId": rec.requestId,
        "modelId": rec.modelId,
        "triggerType": rec.triggerType,
        "promptLength": rec.promptLength,
        "responseLength": rec.responseLength,
        "displayName": rec.displayName,
        "userName": rec.userName,
        "region": rec.region,
        "accountId": rec.accountId,
        "conversationId": rec.conversationId,
        "utteranceId": rec.utteranceId,
        "customizationArn": rec.customizationArn,
        "date": rec.date,
        "hour": rec.hour,
        "prompt": raw.prompt,
        "response": raw.response,
    }
