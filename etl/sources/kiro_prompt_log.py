"""Source adapter for Kiro GenerateAssistantResponse prompt logs."""

from __future__ import annotations

import re
from typing import Any

if __package__.startswith("etl."):
    from ..processors.prompt_processor import _to_dynamo_record
    from ..prompt_normalizer import normalize_prompt_records
    from ..prompt_parser import parse_prompt_file
    from ..prompt_s3_reader import PROMPT_SUBPATH, list_prompt_files, read_prompt_file
    from .base import ParsedSource, PathMetadata
else:  # Lambda imports this module as sources.kiro_prompt_log.
    from processors.prompt_processor import _to_dynamo_record
    from prompt_normalizer import normalize_prompt_records
    from prompt_parser import parse_prompt_file
    from prompt_s3_reader import PROMPT_SUBPATH, list_prompt_files, read_prompt_file
    from sources.base import ParsedSource, PathMetadata


class KiroPromptLogAdapter:
    """Discover, parse and normalize Kiro prompt-log objects."""

    source_type = "kiro_prompt_log"
    aliases = ("prompt",)
    wire_type = "prompt"
    record_kind = "prompt"
    count_key = "totalPromptFiles"
    requires_content_placement = True
    access_denied_message = (
        "Acesso negado ao ler arquivo de prompt. Verifique as permissões da Role_Origem."
    )

    def list_files(self, bucket: str, config: Any, s3_client=None) -> list[str]:
        if not config.prompts_prefix:
            return []
        return list_prompt_files(bucket, config.prompts_prefix, s3_client=s3_client)

    def claim(self, key: str, config: Any) -> bool:
        prefix = f"{config.prompts_prefix}{PROMPT_SUBPATH}"
        return bool(config.prompts_prefix) and key.startswith(prefix) and key.endswith(".json.gz")

    def read(self, bucket: str, key: str, s3_client=None) -> bytes:
        return read_prompt_file(bucket, key, s3_client=s3_client)

    def parse(self, content: str | bytes, key: str, config: Any) -> ParsedSource:
        if not isinstance(content, bytes):
            raise TypeError("Kiro prompt-log content must be bytes")

        metadata = extract_path_metadata(key, config.prompts_prefix)
        return ParsedSource(
            records=parse_prompt_file(content),
            metadata=metadata,
        )

    def normalize(self, parsed: ParsedSource) -> list[dict]:
        if not parsed.records:
            return []
        metadata = parsed.metadata.as_prompt_mapping()
        normalized = normalize_prompt_records(parsed.records, metadata, {})
        return [
            _to_dynamo_record(record, raw, metadata)
            for record, raw in zip(normalized, parsed.records)
        ]


def extract_path_metadata(key: str, prompts_prefix: str) -> PathMetadata:
    """Extract region and account from a Kiro prompt-log object key."""
    relative = key.removeprefix(prompts_prefix)
    parts = relative.split("/")
    region = parts[1] if len(parts) >= 2 and parts[0] == PROMPT_SUBPATH.rstrip("/") else ""

    account_match = re.search(r"/(\d{12})/", prompts_prefix)
    account_id = account_match.group(1) if account_match else ""

    date_parts = parts[2:5] if len(parts) >= 5 else ("", "", "")
    return PathMetadata(
        region=region,
        year=date_parts[0],
        month=date_parts[1],
        day=date_parts[2],
        account_id=account_id,
    )
