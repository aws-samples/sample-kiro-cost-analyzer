"""Structured Logger — emits JSON-formatted log entries for Lambda observability.

Usage guideline: only pass explicitly selected metadata fields as kwargs to
`info`/`warning`/`error` (e.g. `errorType`, `s3Key`, `recordCount`, `userId`).
Never pass an entire request/response body, exception object, or other
caller-supplied payload as a single kwarg value — `_redact_sensitive` below
only inspects field *names*, not values, so a payload stored under a
generic key (e.g. `data`, `payload`, `response`) passes through unredacted
even if it contains a secret. Extract only the specific fields you need to
log before calling.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

# Substring match (case-insensitive) against extra field NAMES, not values.
# Redacts a field's value when its key looks like it could hold a secret,
# regardless of what the caller actually put there. This is a defense-in-depth
# backstop, not a substitute for callers choosing safe field names and values
# in the first place — see `development-standards.md` section 4.1 ("Never
# silence errors without logging them") for the broader logging convention
# this module implements across the project's Lambdas.
_SENSITIVE_KEY_PATTERN = re.compile(
    r"token|password|passwd|secret|credential|authorization|apikey|api_key|private[_-]?key",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"


def _redact_sensitive(kwargs: dict) -> dict:
    """Replace values of keys that look sensitive with a redaction marker.

    Args:
        kwargs: Extra structured-log fields as passed by the caller.

    Returns:
        A new dict with the same keys; values of any key matching
        `_SENSITIVE_KEY_PATTERN` are replaced with `"[REDACTED]"`. Keys with
        ordinary names (e.g. `s3Key`, `recordCount`, `errorType`) are passed
        through unchanged.
    """
    return {
        key: (_REDACTED if _SENSITIVE_KEY_PATTERN.search(key) else value)
        for key, value in kwargs.items()
    }


class StructuredLogger:
    """Emit structured JSON logs with consistent fields across all Lambdas."""

    def __init__(self, lambda_name: str, correlation_id: str = ""):
        self.lambda_name = lambda_name
        self.correlation_id = correlation_id
        self._logger = logging.getLogger(lambda_name)

    def _emit(self, level: str, message: str, **kwargs):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": level,
            "message": message,
            "lambda": self.lambda_name,
            "correlationId": self.correlation_id,
            **_redact_sensitive(kwargs),
        }
        print(json.dumps(entry, default=str))

    def info(self, message: str, **kwargs):
        self._emit("INFO", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._emit("ERROR", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._emit("WARNING", message, **kwargs)
