"""CSV Processor — parses activity CSVs and normalizes records for DynamoDB writes.

Reuses the existing csv_parser and normalizer modules, converting their output
into dicts ready for the AnalyticsWriter (STATS#DAILY# updates).
"""

from __future__ import annotations

try:
    from csv_parser import parse_csv
    from normalizer import normalize_records
except ImportError:
    from etl.csv_parser import parse_csv
    from etl.normalizer import normalize_records


def process_csv(csv_content: str, format_type: str, metadata: dict) -> list[dict]:
    """Parse and normalize a CSV file, returning records ready for DynamoDB writes.

    Each returned dict contains the fields needed by AnalyticsWriter.increment_daily_stats:
      - userId, date, totalCredits, overageCredits, totalMessages, totalConversations,
        totalInteractions, clientType, subscriptionTier

    Parameters
    ----------
    csv_content:
        Raw CSV string (including header row).
    format_type:
        Format hint passed to the parser (e.g. "new").
    metadata:
        Path metadata dict (from path_resolver) with optional fallback fields
        like ``client_type``.

    Returns
    -------
    list[dict]
        One dict per normalised activity row, ready for DynamoDB writes.
    """
    raw_rows = parse_csv(csv_content, format_type)
    if not raw_rows:
        return []

    records = normalize_records(raw_rows, format_type, metadata)

    return [_to_dynamo_record(rec, metadata) for rec in records]


def _to_dynamo_record(rec, metadata: dict) -> dict:
    """Convert a UserActivityRecord into a flat dict for DynamoDB writes."""
    record = {
        "userId": rec.userId,
        "date": rec.date,
        "totalCredits": rec.creditsUsed,
        "overageCredits": rec.overageCreditsUsed,
        "totalMessages": rec.totalMessages,
        "totalConversations": rec.chatConversations,
        # totalInteractions = messages + conversations (matches DailyStats schema)
        "totalInteractions": rec.totalMessages + rec.chatConversations,
        "clientType": rec.clientType,
        "subscriptionTier": rec.subscriptionTier,
        "overageEnabled": rec.overageEnabled,
        "overageCap": rec.overageCap,
        "profileId": rec.profileId,
        "displayName": rec.displayName,
        "userName": rec.userName,
        "region": metadata.get("region", ""),
        "accountId": metadata.get("account_id", ""),
        "newUser": rec.newUser,
    }
    if rec.modelMessages:
        record["modelMessages"] = rec.modelMessages
    return record
