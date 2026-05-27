# Technical Design — CSV Model Distribution & Schema Validation

## Overview

This design extends the ETL CSV processing pipeline to:
1. Extract dynamic model message columns and `New_User` from Kiro CSVs
2. Persist them as attributes on existing `STATS#DAILY#` DynamoDB items
3. Expose them in the backend API response (no new endpoints)
4. Validate CSV schema before processing (warn-not-block for non-critical issues)

All changes are backward compatible — existing items without `modelMessages` or `newUser` continue to work unchanged.

## Architecture

### 2.1 Data Flow (Modified Steps)

```
S3 CSV → Parse Lambda → [Schema Validation] → [Extract model columns] → Normalize → Writer Lambda → DynamoDB
                              ↓ (reject)                                                    ↓
                         empty list + error log                                   SET modelMessages, newUser
```

### 2.2 Components Modified

| Component | Change |
|---|---|
| `etl/csv_schema_validator.py` | **NEW** — schema validation module |
| `etl/csv_parser.py` | Invoke validator before row iteration |
| `etl/normalizer.py` | Add `modelMessages` and `newUser` to `UserActivityRecord` |
| `etl/processors/csv_processor.py` | Pass new fields to DynamoDB record |
| `etl/writer_handler.py` | Pass new fields to `increment_daily_stats` |
| `layers/shared/shared/analytics_writer.py` | Add SET for `modelMessages` and `newUser` |
| `backend/repository/analytics_repository.py` | No change needed (already returns all attributes) |

## Components and Interfaces

### 3.1 CSV Schema Validator (`etl/csv_schema_validator.py`) — NEW

```python
"""CSV Schema Validator — validates CSV headers against known Kiro report schemas."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DYNAMIC_COLUMN_PATTERN = re.compile(r"^[a-z0-9_]+_messages$")

# New format (user_report) required columns
USER_REPORT_REQUIRED_COLUMNS = {
    "Date", "UserId", "Client_Type", "Chat_Conversations",
    "Credits_Used", "Overage_Cap", "Overage_Credits_Used",
    "Overage_Enabled", "ProfileId", "Subscription_Tier",
    "Total_Messages",
}

# Critical columns — file is rejected if any of these are missing
USER_REPORT_CRITICAL_COLUMNS = {"UserId", "Date", "Credits_Used"}

# Known optional columns that are valid but not required
USER_REPORT_OPTIONAL_COLUMNS = {"New_User"}

# Legacy format minimal required columns
LEGACY_REQUIRED_COLUMNS = {"Date", "UserId"}


@dataclass
class SchemaValidationResult:
    """Result of CSV schema validation."""
    valid: bool
    format_type: str  # "user_report" or "by_user_analytic"
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
    """Validate headers for the new user_report format."""
    header_set = set(headers)
    errors: list[str] = []
    warnings: list[str] = []

    # Check critical columns
    missing_critical = USER_REPORT_CRITICAL_COLUMNS - header_set
    if missing_critical:
        errors.append(f"Missing critical columns: {sorted(missing_critical)}")
        return SchemaValidationResult(
            valid=False, format_type="user_report", errors=errors
        )

    # Check non-critical required columns
    missing_required = USER_REPORT_REQUIRED_COLUMNS - header_set
    if missing_required:
        warnings.append(f"Missing non-critical columns: {sorted(missing_required)}")

    # Identify unexpected columns
    known_columns = USER_REPORT_REQUIRED_COLUMNS | USER_REPORT_OPTIONAL_COLUMNS
    extra_columns = header_set - known_columns
    unexpected = []
    for col in extra_columns:
        # Dynamic model message columns are valid
        if _DYNAMIC_COLUMN_PATTERN.match(col) and col != "Total_Messages":
            continue
        unexpected.append(col)

    if unexpected:
        warnings.append(f"Unexpected columns (will be ignored): {sorted(unexpected)}")

    return SchemaValidationResult(
        valid=True, format_type="user_report", errors=errors, warnings=warnings
    )


def _validate_legacy(headers: list[str]) -> SchemaValidationResult:
    """Validate headers for the legacy by_user_analytic format."""
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
```

### 3.2 CSV Parser Changes (`etl/csv_parser.py`)

```python
# Add import
from csv_schema_validator import validate_schema, SchemaValidationResult

def parse_csv(csv_content: str, format_type_from_path: str = "new") -> list[dict]:
    # ... existing header reading ...

    # NEW: Schema validation before row iteration
    format_type = "user_report"  # Only format currently supported via path
    validation = validate_schema(header_columns, format_type)

    if not validation.valid:
        logger.error(
            "CSV schema validation failed",
            formatType=format_type,
            errors=validation.errors,
        )
        return []

    if validation.warnings:
        logger.warning(
            "CSV schema validation warnings",
            formatType=format_type,
            warnings=validation.warnings,
        )

    # ... existing row iteration (unchanged) ...
```

### 3.3 Normalizer Changes (`etl/normalizer.py`)

```python
@dataclass
class UserActivityRecord:
    """User activity record from Kiro user_report CSV."""
    userId: str
    date: str
    clientType: str
    subscriptionTier: str
    profileId: str
    totalMessages: int
    chatConversations: int
    creditsUsed: float
    overageEnabled: bool
    overageCap: float
    overageCreditsUsed: float
    displayName: str = ""
    userName: str = ""
    # NEW fields
    modelMessages: dict[str, int] = field(default_factory=dict)
    newUser: bool = False


def normalize_records(...) -> list[UserActivityRecord]:
    for raw in raw_records:
        # ... existing field extraction ...

        # NEW: Extract model message columns
        model_messages: dict[str, int] = {}
        for col, value in raw.items():
            if col.endswith("_messages") and col != "Total_Messages":
                model_name = col.removesuffix("_messages")
                count = _safe_int(value)
                if count > 0:
                    model_messages[model_name] = count

        # NEW: Extract New_User
        new_user = _safe_bool(raw.get("New_User", "false"))

        results.append(UserActivityRecord(
            # ... existing fields ...
            modelMessages=model_messages,
            newUser=new_user,
        ))
```

### 3.4 CSV Processor Changes (`etl/processors/csv_processor.py`)

```python
def _to_dynamo_record(rec, metadata: dict) -> dict:
    record = {
        # ... existing fields ...
    }
    # NEW: Add model messages and newUser
    if rec.modelMessages:
        record["modelMessages"] = rec.modelMessages
    record["newUser"] = rec.newUser
    return record
```

### 3.5 Writer Handler Changes (`etl/writer_handler.py`)

```python
def _write_csv_record(writer: AnalyticsWriter, record: dict) -> int:
    # ... existing code ...

    # NEW: Persist model messages and newUser
    model_messages = record.get("modelMessages")
    new_user = record.get("newUser", False)
    if model_messages or new_user:
        writer.set_daily_stats_metadata(
            user_id, date,
            model_messages=model_messages,
            new_user=new_user,
        )
        items += 1

    return items
```

### 3.6 Analytics Writer Changes (`layers/shared/shared/analytics_writer.py`)

```python
def set_daily_stats_metadata(
    self,
    user_id: str,
    date: str,
    model_messages: dict[str, int] | None = None,
    new_user: bool = False,
) -> None:
    """SET modelMessages and/or newUser on a STATS#DAILY# item.

    Uses a separate UpdateItem from increment_daily_stats to avoid
    complicating the ADD expression. This is a SET-only operation.

    Args:
        user_id: User identifier.
        date: ISO date string (YYYY-MM-DD).
        model_messages: Dict mapping model name to message count.
        new_user: Whether this is a new user activation day.
    """
    set_clauses: list[str] = []
    expr_values: dict = {}

    if model_messages:
        set_clauses.append("modelMessages = :mm")
        expr_values[":mm"] = model_messages

    if new_user:
        # Only SET newUser when true — avoid overwriting true with false
        set_clauses.append("newUser = :nu")
        expr_values[":nu"] = True

    if not set_clauses:
        return

    self._table.update_item(
        Key={
            "PK": f"USER#{user_id}",
            "SK": f"STATS#DAILY#{date}",
        },
        UpdateExpression="SET " + ", ".join(set_clauses),
        ExpressionAttributeValues=expr_values,
    )
```

## Data Models

### 4.1 Modified Entity: STATS#DAILY#

| Attribute | Type | Source | Notes |
|---|---|---|---|
| `modelMessages` | Map (M) | CSV dynamic columns | `{"auto": 15, "claude_sonnet": 8}` — SET overwrites per day |
| `newUser` | Boolean (BOOL) | CSV `New_User` column | Only written when `true` |

No key schema changes. No GSI changes. No new items created.

### 4.2 Item Size Impact

- `modelMessages` with 5 models ≈ 100 bytes
- `newUser` boolean ≈ 10 bytes
- Total increase per item: ~110 bytes (negligible vs 400KB limit)

## Error Handling

| Scenario | Behavior |
|---|---|
| Missing critical columns (UserId, Date, Credits_Used) | File rejected, empty list returned, structured error logged |
| Missing non-critical columns | Warning logged, processing continues with available data |
| Unexpected columns | Warning logged, columns ignored |
| `modelMessages` write fails | Does not fail the record — best-effort (same pattern as `upsert_activity_summary`) |
| Empty `modelMessages` dict | No DynamoDB write for metadata (skip) |

## Correctness Properties

### Property 1: Schema Validation Idempotence

For any valid CSV header list H and format type F, `validate_schema(H, F)` called twice produces equivalent results: same `valid` flag, same `errors`, same `warnings`.

**Validates: Requirements 8.4**

### Property 2: Model Messages Completeness

For any CSV row R with N columns matching `*_messages` (excluding `Total_Messages`) where value > 0, the resulting `modelMessages` dict has exactly N entries with matching keys and integer values.

**Validates: Requirements 1.1, 1.2, 1.3**

### Property 3: Backward Compatibility Invariant

For any `STATS#DAILY#` item written before this feature (without `modelMessages`), the `get_user_daily_stats` response returns the item unchanged — no `modelMessages` key is injected when the attribute does not exist in DynamoDB.

**Validates: Requirements 4.1, 4.2**

### Property 4: Critical Column Rejection Totality

For any CSV header set missing at least one of {UserId, Date, Credits_Used}, `validate_schema` returns `valid=False` with at least one error entry.

**Validates: Requirements 5.2, 6.2**

| Concern | Mitigation |
|---|---|
| Existing items without `modelMessages` | Backend already returns all attributes; frontend treats missing as `{}` |
| Existing items without `newUser` | Frontend treats missing as `false` |
| Old CSVs without dynamic columns | `modelMessages` will be empty dict, no write occurs |
| Legacy format files | Rejected by path_resolver (returns None), schema validator provides safety net |

## Performance Considerations

- **Additional WCU per CSV record**: 1 extra UpdateItem (SET only, ~5 WCUs) for `modelMessages`
- **Reduced RCU for model distribution queries**: Frontend sums `modelMessages` from daily stats instead of querying N `STATS#MODEL#` items. For a user with 30 days × 5 models = 150 items avoided.
- **Net effect**: Slight write increase, significant read decrease for model distribution views.

## Testing Strategy

- **Unit tests**: `test_csv_schema_validator.py` — all validation paths (valid, missing critical, missing non-critical, unexpected columns, legacy format)
- **Unit tests**: `test_normalizer.py` — model message extraction, New_User parsing, empty cases
- **Unit tests**: `test_csv_processor.py` — end-to-end CSV → DynamoDB record with model messages
- **Unit tests**: `test_analytics_writer.py` — `set_daily_stats_metadata` with mocked DynamoDB
- **Integration test**: Full ETL flow with a sample CSV containing dynamic model columns
- **Property-based test**: For any valid CSV header, schema validation is idempotent

## Implementation Plan

| File | Action | Requirements |
|---|---|---|
| `etl/csv_schema_validator.py` | CREATE | 5, 6, 7, 8 |
| `etl/csv_parser.py` | MODIFY | 7 |
| `etl/normalizer.py` | MODIFY | 1, 2 |
| `etl/processors/csv_processor.py` | MODIFY | 1, 2, 4 |
| `etl/writer_handler.py` | MODIFY | 3 |
| `layers/shared/shared/analytics_writer.py` | MODIFY | 3 |
| `tests/test_csv_schema_validator.py` | CREATE | 5, 6, 7, 8 |
| `tests/test_normalizer.py` | MODIFY | 1, 2 |
| `tests/test_csv_processor.py` | MODIFY | 1, 2 |
| `tests/test_analytics_writer.py` | MODIFY | 3 |
| `docs/architecture.md` | MODIFY | — |
| `docs/changelog.md` | MODIFY | — |
