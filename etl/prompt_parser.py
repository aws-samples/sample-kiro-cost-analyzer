"""Prompt parser — decompresses gzip and parses JSON prompt logs."""

from __future__ import annotations

import gzip
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RawPromptRecord:
    """Raw record extracted from a prompt JSON log."""

    prompt: str
    response: str
    userId: str
    timestamp: str
    modelId: str
    triggerType: str
    customizationArn: str | None
    requestId: str
    conversationId: str | None
    utteranceId: str | None
    followupPrompts: str
    codeReferenceEvents: list
    supplementaryWebLinksEvent: list


def parse_prompt_file(gzipped_content: bytes) -> list[RawPromptRecord]:
    """Decompress gzip content, parse JSON, and extract prompt records.

    Returns a list of :class:`RawPromptRecord` extracted from the ``records``
    array in the JSON payload.

    Returns an empty list when ``records`` is present but empty.

    Raises:
        ValueError: If the content cannot be decompressed or parsed as JSON.
    """
    try:
        decompressed = gzip.decompress(gzipped_content)
    except Exception as exc:
        raise ValueError(f"Failed to decompress gzip content: {exc}") from exc

    try:
        data = json.loads(decompressed)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse JSON content: {exc}") from exc

    records = data.get("records", [])
    if not records:
        return []

    result: list[RawPromptRecord] = []
    for record in records:
        request = record.get("generateAssistantResponseEventRequest", {})
        response = record.get("generateAssistantResponseEventResponse", {})
        message_metadata = response.get("messageMetadata", {})

        result.append(
            RawPromptRecord(
                prompt=request.get("prompt", ""),
                userId=request.get("userId", ""),
                modelId=request.get("modelId", ""),
                triggerType=request.get("chatTriggerType", ""),
                timestamp=request.get("timeStamp", ""),
                customizationArn=request.get("customizationArn"),
                response=response.get("assistantResponse", ""),
                requestId=response.get("requestId", ""),
                conversationId=message_metadata.get("conversationId"),
                utteranceId=message_metadata.get("utteranceId"),
                followupPrompts=response.get("followupPrompts", ""),
                codeReferenceEvents=response.get("codeReferenceEvents", []),
                supplementaryWebLinksEvent=response.get("supplementaryWebLinksEvent", []),
            )
        )

    return result
