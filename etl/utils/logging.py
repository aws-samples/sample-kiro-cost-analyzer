"""Structured Logger — emits JSON-formatted log entries for Lambda observability."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


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
            **kwargs,
        }
        print(json.dumps(entry, default=str))

    def info(self, message: str, **kwargs):
        self._emit("INFO", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._emit("ERROR", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._emit("WARNING", message, **kwargs)
