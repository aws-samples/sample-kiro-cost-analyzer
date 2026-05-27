"""Tests for shared.structured_logger module."""

import json
from unittest.mock import patch
from datetime import datetime, timezone

from shared.structured_logger import StructuredLogger


class TestStructuredLogger:
    """Unit tests for StructuredLogger."""

    def _capture(self, logger_method, message, **kwargs):
        """Call a logger method and return the parsed JSON output."""
        with patch("builtins.print") as mock_print:
            logger_method(message, **kwargs)
        output = mock_print.call_args[0][0]
        return json.loads(output)

    def test_info_emits_json_with_required_fields(self):
        logger = StructuredLogger("my-lambda", "corr-123")
        entry = self._capture(logger.info, "hello")

        assert entry["level"] == "INFO"
        assert entry["message"] == "hello"
        assert entry["lambda"] == "my-lambda"
        assert entry["correlationId"] == "corr-123"
        assert "timestamp" in entry

    def test_error_emits_error_level(self):
        logger = StructuredLogger("err-lambda")
        entry = self._capture(logger.error, "boom")

        assert entry["level"] == "ERROR"
        assert entry["message"] == "boom"

    def test_warning_emits_warning_level(self):
        logger = StructuredLogger("warn-lambda")
        entry = self._capture(logger.warning, "careful")

        assert entry["level"] == "WARNING"
        assert entry["message"] == "careful"

    def test_extra_kwargs_included_in_output(self):
        logger = StructuredLogger("task-lambda", "exec-abc")
        entry = self._capture(logger.info, "processed", recordCount=42, s3Key="file.csv")

        assert entry["recordCount"] == 42
        assert entry["s3Key"] == "file.csv"

    def test_default_correlation_id_is_empty_string(self):
        logger = StructuredLogger("backend")
        entry = self._capture(logger.info, "request")

        assert entry["correlationId"] == ""

    def test_timestamp_is_utc_iso_format(self):
        logger = StructuredLogger("ts-lambda")
        entry = self._capture(logger.info, "check ts")

        ts = datetime.fromisoformat(entry["timestamp"])
        assert ts.tzinfo == timezone.utc

    def test_non_serializable_kwargs_use_default_str(self):
        logger = StructuredLogger("ser-lambda")
        entry = self._capture(logger.info, "with date", when=datetime(2025, 1, 15, tzinfo=timezone.utc))

        assert "2025-01-15" in entry["when"]
