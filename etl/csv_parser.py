"""CSV parser — parses new-format Kiro user_report CSVs."""

from __future__ import annotations

import csv
import io
import logging

try:
    from csv_schema_validator import validate_schema
except ImportError:
    from etl.csv_schema_validator import validate_schema

logger = logging.getLogger(__name__)

_NEW_FORMAT_MARKER = "Credits_Used"


def parse_csv(csv_content: str, format_type_from_path: str = "new") -> list[dict]:
    """Parse a single CSV string and return a list of raw record dicts.

    Validates the CSV schema before processing rows. Files missing critical
    columns are rejected (empty list returned). Non-critical issues are
    logged as warnings but processing continues.

    Only the new Kiro report format is supported (must contain Credits_Used).
    Empty files or files with only a header row return an empty list.
    """
    if not csv_content or not csv_content.strip():
        return []

    reader = csv.DictReader(io.StringIO(csv_content))
    if reader.fieldnames is None:
        return []

    header_columns = list(reader.fieldnames)

    # Schema validation before row iteration
    format_type = "user_report"
    validation = validate_schema(header_columns, format_type)

    if not validation.valid:
        logger.error(
            "CSV schema validation failed: %s",
            validation.errors,
        )
        return []

    if validation.warnings:
        logger.warning(
            "CSV schema validation warnings: %s",
            validation.warnings,
        )

    # Legacy check kept for backward compatibility with existing tests
    if _NEW_FORMAT_MARKER not in header_columns:
        logger.error(
            "Unsupported CSV format. Expected column '%s' not found. "
            "Found columns: %s",
            _NEW_FORMAT_MARKER,
            header_columns,
        )
        return []

    rows: list[dict] = []
    for row in reader:
        rows.append(dict(row))

    return rows


def combine_records(record_lists: list[list[dict]]) -> list[dict]:
    """Combine records from multiple part files into a single list."""
    combined: list[dict] = []
    for part in record_lists:
        combined.extend(part)
    return combined
