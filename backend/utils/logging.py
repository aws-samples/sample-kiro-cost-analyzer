"""Structured Logger — emits JSON-formatted log entries for Lambda observability.

Fallback copy of `layers/shared/shared/structured_logger.py`, used when the
shared Lambda layer is not importable (e.g. local test execution outside the
layer's runtime). Keep the redaction behavior in sync with that module — see
its docstring for the "only log selected metadata fields" usage guideline.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

_SENSITIVE_KEY_PATTERN = re.compile(
    r"token|password|passwd|secret|credential|authorization|apikey|api_key|private[_-]?key",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"


def _redact_sensitive(kwargs: dict) -> dict:
    """Replace values of keys that look sensitive with a redaction marker."""
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
