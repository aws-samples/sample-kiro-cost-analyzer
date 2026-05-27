"""SK Normalizer — normalizes raw values into deterministic DynamoDB-compatible sort key slugs."""

from __future__ import annotations

import re

MAX_SK_LENGTH = 128


def normalize_sk_value(raw_value: str, canonical_map: dict[str, str] | None = None) -> str:
    """
    Transform a raw value into a DynamoDB SK-compatible slug.

    Pipeline (in order):
    1. Canonical lookup (if map provided and value found)
    2. Lowercase
    3. Trim whitespace
    4. Replace spaces and special characters with hyphens
    5. Remove non-alphanumeric characters except hyphens
    6. Collapse consecutive hyphens into a single hyphen
    7. Strip leading/trailing hyphens
    8. Truncate to MAX_SK_LENGTH characters
    """
    value = raw_value

    # 1. Canonical lookup
    if canonical_map and value in canonical_map:
        value = canonical_map[value]

    # 2. Lowercase
    value = value.lower()

    # 3. Trim
    value = value.strip()

    # 4. Replace spaces and special characters with hyphens
    value = re.sub(r"[^a-z0-9]", "-", value)

    # 5. Remove non-alphanumeric except hyphens (already handled by step 4)

    # 6. Collapse consecutive hyphens
    value = re.sub(r"-{2,}", "-", value)

    # 7. Strip leading/trailing hyphens
    value = value.strip("-")

    # 8. Truncate and strip any trailing hyphen caused by truncation
    value = value[:MAX_SK_LENGTH].strip("-")

    return value
