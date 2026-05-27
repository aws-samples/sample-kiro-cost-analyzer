"""CSV Schema Validator — validates CSV headers against known Kiro report schemas.

Provides structural validation of CSV column headers before row processing.
Distinguishes between critical columns (file rejected if missing) and
non-critical columns (warning logged, processing continues).

Designed for the ETL parse step to catch malformed files early while
gracefully degrading when Kiro adds new upstream columns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Pattern for dynamic model message columns (e.g., auto_messages, claude_sonnet_messages)
_DYNAMIC_COLUMN_PATTERN = re.compile(r"^[a-z0-9_]+_messages$")

# New format (user_report) required columns
USER_REPORT_REQUIRED_COLUMNS = frozenset({
    "Date", "UserId", "Client_Type", "Chat_Conversations",
    "Credits_Used", "Overage_Cap", "Overage_Credits_Used",
    "Overage_Enabled", "ProfileId", "Subscription_Tier",
    "Total_Messages",
})

# Critical columns — file is rejected if any of these are missing
USER_REPORT_CRITICAL_COLUMNS = frozenset({"UserId", "Date", "Credits_Used"})

# Known optional columns that are valid but not required
USER_REPORT_OPTIONAL_COLUMNS = frozenset({"New_User"})

# Legacy format minimal required columns
LEGACY_REQUIRED_COLUMNS = frozenset({"Date", "UserId"})


@dataclass
class SchemaValidationResult:
    """Result of CSV schema validation.

    Attributes:
        valid: Whether the file should be processed.
        format_type: The detected format ("user_report" or "by_user_analytic").
        errors: List of critical issues that caused rejection.
        warnings: List of non-critical issues (processing continues).
    """

    valid: bool
    format_type: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_schema(
    headers: list[str],
    format_type: str,
) -> SchemaValidationResult:
    """Validate CSV headers against the expected schema for the given format.

    Args:
        headers: List of column names from the CSV header row.
        format_type: Either "user_report" or "by_user_analytic".

    Returns:
        SchemaValidationResult with valid flag, errors, and warnings.
    """
    if format_type == "user_report":
        return _validate_user_report(headers)
    elif format_type == "by_user_analytic":
        return _validate_legacy(headers)
    else:
        return SchemaValidationResult(
            valid=False,
            format_type=format_type,
            errors=[f"Unknown format type: {format_type}"],
        )


def _validate_user_report(headers: list[str]) -> SchemaValidationResult:
    """Validate headers for the new user_report format.

    Validation logic:
    1. Check critical columns (UserId, Date, Credits_Used) — reject if missing
    2. Check non-critical required columns — warn if missing
    3. Identify unexpected columns — warn but allow
    4. Recognize dynamic *_messages columns as valid
    """
    header_set = set(headers)
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Check critical columns — reject if any missing
    missing_critical = USER_REPORT_CRITICAL_COLUMNS - header_set
    if missing_critical:
        errors.append(f"Missing critical columns: {sorted(missing_critical)}")
        return SchemaValidationResult(
            valid=False, format_type="user_report", errors=errors
        )

    # 2. Check non-critical required columns — warn if missing
    missing_required = USER_REPORT_REQUIRED_COLUMNS - header_set
    if missing_required:
        warnings.append(f"Missing non-critical columns: {sorted(missing_required)}")

    # 3. Identify unexpected columns
    known_columns = USER_REPORT_REQUIRED_COLUMNS | USER_REPORT_OPTIONAL_COLUMNS
    extra_columns = header_set - known_columns
    unexpected = []
    for col in sorted(extra_columns):
        # Dynamic model message columns are valid
        if _DYNAMIC_COLUMN_PATTERN.match(col) and col != "Total_Messages":
            continue
        unexpected.append(col)

    if unexpected:
        warnings.append(f"Unexpected columns (will be ignored): {unexpected}")

    return SchemaValidationResult(
        valid=True, format_type="user_report", errors=errors, warnings=warnings
    )


def _validate_legacy(headers: list[str]) -> SchemaValidationResult:
    """Validate headers for the legacy by_user_analytic format.

    Minimal validation — only checks for Date and UserId presence.
    """
    header_set = set(headers)
    missing = LEGACY_REQUIRED_COLUMNS - header_set

    if missing:
        return SchemaValidationResult(
            valid=False,
            format_type="by_user_analytic",
            errors=[f"Missing required columns: {sorted(missing)}"],
        )

    return SchemaValidationResult(
        valid=True, format_type="by_user_analytic"
    )
