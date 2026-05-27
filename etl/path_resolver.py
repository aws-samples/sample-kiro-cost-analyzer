"""Path resolver — extracts metadata from S3 key paths (new format only)."""

from __future__ import annotations

from typing import Optional


def _extract_client_type_and_account(filename: str) -> tuple[str, str]:
    """Extract client_type and account_id from a new-format filename.

    The filename pattern is: {clientType}_{accountId}_user_report_{timestamp}.csv
    The client type can contain underscores (e.g. KIRO_IDE, KIRO_CLI).
    The account_id is always a purely numeric string, so we split on '_'
    and find the first all-digit segment.
    """
    parts = filename.split("_")
    for i, part in enumerate(parts):
        if part.isdigit():
            client_type = "_".join(parts[:i])
            account_id = part
            return client_type, account_id
    return "", ""


def resolve_path_metadata(s3_key: str, source_prefix: str) -> Optional[dict]:
    """Extract metadata from an S3 CSV file path.

    Only the new Kiro report format (``user_report/``) is supported.
    Legacy ``by_user_analytic/`` paths are ignored (returns None).

    New format path:
        user_report/{region}/{year}/{month}/{day}/00/{clientType}_{accountId}_user_report_{ts}.csv

    Returns a dict with extracted fields, or ``None`` for unrecognised paths.
    """
    relative_path = s3_key.removeprefix(source_prefix)

    if not relative_path.startswith("user_report/"):
        return None

    parts = relative_path.split("/")
    if len(parts) < 7:
        return None

    filename = parts[6]
    client_type, account_id = _extract_client_type_and_account(filename)
    return {
        "format_type": "new",
        "region": parts[1],
        "year": parts[2],
        "month": parts[3],
        "day": parts[4],
        "account_id": account_id,
        "client_type": client_type,
    }
