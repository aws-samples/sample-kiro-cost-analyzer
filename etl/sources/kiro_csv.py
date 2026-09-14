"""Source adapter for Kiro user-report CSV files."""

from __future__ import annotations

from typing import Any

if __package__.startswith("etl."):
    from ..csv_parser import parse_csv
    from ..normalizer import normalize_records
    from ..path_resolver import resolve_path_metadata
    from ..processors.csv_processor import _to_dynamo_record
    from ..s3_reader import list_csv_files, read_csv_content
    from .base import ParsedSource, PathMetadata
else:  # Lambda imports this module as sources.kiro_csv.
    from csv_parser import parse_csv
    from normalizer import normalize_records
    from path_resolver import resolve_path_metadata
    from processors.csv_processor import _to_dynamo_record
    from s3_reader import list_csv_files, read_csv_content
    from sources.base import ParsedSource, PathMetadata


class KiroCsvAdapter:
    """Discover, parse and normalize Kiro user-report CSV objects."""

    source_type = "kiro_csv"
    aliases = ("csv",)
    wire_type = "csv"
    record_kind = "activity"
    count_key = "totalCsvFiles"
    requires_content_placement = False
    access_denied_message = (
        "Acesso negado ao ler arquivo CSV. Verifique as permissões da Role_Origem."
    )

    def list_files(self, bucket: str, config: Any, s3_client=None) -> list[str]:
        return list_csv_files(bucket, config.source_prefix, s3_client=s3_client)

    def claim(self, key: str, config: Any) -> bool:
        if (
            not config.source_prefix
            or not key.startswith(config.source_prefix)
            or not key.endswith(".csv")
        ):
            return False
        return resolve_path_metadata(key, config.source_prefix) is not None

    def read(self, bucket: str, key: str, s3_client=None) -> str:
        return read_csv_content(bucket, key, s3_client=s3_client)

    def parse(self, content: str | bytes, key: str, config: Any) -> ParsedSource:
        if not isinstance(content, str):
            raise TypeError("Kiro CSV content must be text")

        metadata_mapping = resolve_path_metadata(key, config.source_prefix)
        if metadata_mapping is None:
            return ParsedSource(records=[], metadata=PathMetadata())

        metadata = PathMetadata.from_mapping(metadata_mapping)
        return ParsedSource(
            records=parse_csv(content, metadata.format_type),
            metadata=metadata,
        )

    def normalize(self, parsed: ParsedSource) -> list[dict]:
        if not parsed.records:
            return []
        metadata = parsed.metadata.as_csv_mapping()
        records = normalize_records(
            parsed.records,
            parsed.metadata.format_type,
            metadata,
        )
        return [_to_dynamo_record(record, metadata) for record in records]
