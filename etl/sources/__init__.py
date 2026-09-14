"""Ordered registry for ETL source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .base import SourceAdapter
from .kiro_csv import KiroCsvAdapter
from .kiro_prompt_log import KiroPromptLogAdapter


@dataclass(frozen=True)
class ClaimedFile:
    """An object key together with the adapter that owns it."""

    key: str
    adapter: SourceAdapter


@dataclass(frozen=True)
class DiscoveryResult:
    """Registry discovery output consumed by ListFiles."""

    files: tuple[ClaimedFile, ...]
    counts: dict[str, int]
    unclaimed_keys: tuple[str, ...]


class AdapterRegistry:
    """Validated ordered adapter collection; first claim wins."""

    def __init__(self, adapters: Iterable[SourceAdapter]):
        self.adapters = tuple(adapters)
        self._by_type: dict[str, SourceAdapter] = {}
        wire_types: set[str] = set()

        for adapter in self.adapters:
            for source_type in (adapter.source_type, *adapter.aliases):
                if source_type in self._by_type:
                    raise ValueError(f"Duplicate source type or alias: {source_type}")
                self._by_type[source_type] = adapter

            if adapter.wire_type in wire_types:
                raise ValueError(f"Duplicate wire type: {adapter.wire_type}")
            wire_types.add(adapter.wire_type)

    def resolve(self, file_type: str) -> SourceAdapter:
        """Resolve a canonical source type or historical alias."""
        try:
            return self._by_type[file_type]
        except KeyError as exc:
            raise ValueError(f"Unknown fileType: {file_type}") from exc

    def claim(self, key: str, config: Any) -> SourceAdapter | None:
        """Return the first adapter that claims *key*."""
        return next(
            (adapter for adapter in self.adapters if adapter.claim(key, config)),
            None,
        )

    def discover(self, bucket: str, config: Any, s3_client=None) -> DiscoveryResult:
        """List, classify and de-duplicate source objects in registry order."""
        counts: dict[str, int] = {}
        files: list[ClaimedFile] = []
        unclaimed: list[str] = []
        seen: set[str] = set()

        for adapter in self.adapters:
            candidate_keys = adapter.list_files(bucket, config, s3_client=s3_client)
            counts[adapter.count_key] = len(candidate_keys)
            for key in candidate_keys:
                if key in seen:
                    continue
                seen.add(key)
                owner = self.claim(key, config)
                if owner is None:
                    unclaimed.append(key)
                    continue
                files.append(ClaimedFile(key=key, adapter=owner))

        return DiscoveryResult(
            files=tuple(files),
            counts=counts,
            unclaimed_keys=tuple(unclaimed),
        )


REGISTRY = AdapterRegistry((KiroCsvAdapter(), KiroPromptLogAdapter()))


def resolve_adapter(file_type: str) -> SourceAdapter:
    """Resolve through the process-wide registry."""
    return REGISTRY.resolve(file_type)


def claim_adapter(key: str, config: Any) -> SourceAdapter | None:
    """Claim through the process-wide registry."""
    return REGISTRY.claim(key, config)


def discover_files(bucket: str, config: Any, s3_client=None) -> DiscoveryResult:
    """Discover through the process-wide registry."""
    return REGISTRY.discover(bucket, config, s3_client=s3_client)
