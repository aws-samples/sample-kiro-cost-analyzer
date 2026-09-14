"""Contracts shared by ETL source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class PathMetadata:
    """Source-independent metadata extracted from an object key."""

    format_type: str = ""
    region: str = ""
    year: str = ""
    month: str = ""
    day: str = ""
    account_id: str = ""
    client_type: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "PathMetadata":
        """Build metadata from either existing CSV or prompt mapping keys."""
        return cls(
            format_type=str(value.get("format_type", "")),
            region=str(value.get("region", "")),
            year=str(value.get("year", "")),
            month=str(value.get("month", "")),
            day=str(value.get("day", "")),
            account_id=str(value.get("account_id", value.get("accountId", ""))),
            client_type=str(value.get("client_type", value.get("clientType", ""))),
        )

    def as_csv_mapping(self) -> dict[str, str]:
        """Return the mapping shape consumed by the existing CSV normalizer."""
        return {
            "format_type": self.format_type,
            "region": self.region,
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "account_id": self.account_id,
            "client_type": self.client_type,
        }

    def as_prompt_mapping(self) -> dict[str, str]:
        """Return the mapping shape consumed by the existing prompt normalizer."""
        return {
            "region": self.region,
            "accountId": self.account_id,
        }


@dataclass(frozen=True)
class ParsedSource:
    """Parsed source records together with metadata needed for normalization."""

    records: list[Any]
    metadata: PathMetadata


@runtime_checkable
class SourceAdapter(Protocol):
    """Boundary implemented by every ETL source format."""

    source_type: str
    aliases: tuple[str, ...]
    wire_type: str
    record_kind: str
    count_key: str
    requires_content_placement: bool
    access_denied_message: str

    def list_files(self, bucket: str, config: Any, s3_client=None) -> list[str]:
        """Discover candidate object keys for this source."""

    def claim(self, key: str, config: Any) -> bool:
        """Return whether this adapter owns *key*."""

    def read(self, bucket: str, key: str, s3_client=None) -> str | bytes:
        """Read one object's raw content."""

    def parse(self, content: str | bytes, key: str, config: Any) -> ParsedSource:
        """Parse raw content and path metadata without normalizing it."""

    def normalize(self, parsed: ParsedSource) -> list[dict]:
        """Normalize parsed records into the Writer envelope."""
