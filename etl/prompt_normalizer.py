"""Prompt normalizer — converts RawPromptRecord into PromptRecord."""

from __future__ import annotations

import logging
from dataclasses import dataclass

try:
    from prompt_parser import RawPromptRecord
except ImportError:
    from etl.prompt_parser import RawPromptRecord

logger = logging.getLogger(__name__)


@dataclass
class PromptRecord:
    """Normalized prompt record for Parquet storage."""

    userId: str
    originalUserId: str
    displayName: str
    userName: str
    timestamp: str
    date: str  # YYYY-MM-DD
    hour: str  # HH
    modelId: str
    triggerType: str
    customizationArn: str
    requestId: str
    conversationId: str
    utteranceId: str
    region: str
    accountId: str
    promptLength: int
    responseLength: int


def extract_uuid(user_id: str) -> str:
    """Extract the UUID part from a prompt userId.

    Format: 'd-{directoryId}.{uuid}' → returns '{uuid}'
    If no '.' is present, returns the original value.
    """
    if "." in user_id:
        return user_id.split(".", 1)[1]
    return user_id


def normalize_prompt_records(
    raw_records: list[RawPromptRecord],
    path_metadata: dict,
    name_cache: dict[str, tuple[str, str]],
) -> list[PromptRecord]:
    """Normalize raw prompt records into PromptRecord instances.

    - Extracts UUID from userId
    - Derives date (YYYY-MM-DD) and hour (HH) from timestamp
    - Substitutes None with empty string for optional fields
    - Calculates promptLength and responseLength
    - Enriches with displayName/userName from name_cache
    - Gets region and accountId from path_metadata
    """
    region = path_metadata.get("region", "")
    account_id = path_metadata.get("accountId", "")
    results: list[PromptRecord] = []

    for raw in raw_records:
        uuid = extract_uuid(raw.userId)
        display_name, user_name = name_cache.get(uuid, ("", ""))

        # Derive date and hour from timestamp
        date = ""
        hour = ""
        if raw.timestamp and len(raw.timestamp) >= 10:
            date = raw.timestamp[:10]
        if raw.timestamp and len(raw.timestamp) >= 13:
            hour = raw.timestamp[11:13]

        results.append(
            PromptRecord(
                userId=uuid,
                originalUserId=raw.userId,
                displayName=display_name,
                userName=user_name,
                timestamp=raw.timestamp,
                date=date,
                hour=hour,
                modelId=raw.modelId,
                triggerType=raw.triggerType,
                customizationArn=raw.customizationArn or "",
                requestId=raw.requestId,
                conversationId=raw.conversationId or "",
                utteranceId=raw.utteranceId or "",
                region=region,
                accountId=account_id,
                promptLength=len(raw.prompt),
                responseLength=len(raw.response),
            )
        )

    return results
