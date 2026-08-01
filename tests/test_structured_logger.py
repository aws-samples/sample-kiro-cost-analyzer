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


class TestStructuredLoggerRedaction:
    """Sensitive-looking field names are redacted; ordinary ones pass through."""

    def _capture(self, logger_method, message, **kwargs):
        with patch("builtins.print") as mock_print:
            logger_method(message, **kwargs)
        output = mock_print.call_args[0][0]
        return json.loads(output)

    def test_token_field_is_redacted(self):
        logger = StructuredLogger("redact-lambda")
        entry = self._capture(logger.error, "auth failed", token="abc123secretvalue")

        assert entry["token"] == "[REDACTED]"

    def test_password_field_is_redacted(self):
        logger = StructuredLogger("redact-lambda")
        entry = self._capture(logger.error, "login failed", password="hunter2")

        assert entry["password"] == "[REDACTED]"

    def test_secret_field_is_redacted(self):
        logger = StructuredLogger("redact-lambda")
        entry = self._capture(logger.error, "boom", clientSecret="s3cr3t")

        assert entry["clientSecret"] == "[REDACTED]"

    def test_authorization_field_is_redacted(self):
        logger = StructuredLogger("redact-lambda")
        entry = self._capture(logger.info, "request", authorizationHeader="Bearer xyz")

        assert entry["authorizationHeader"] == "[REDACTED]"

    def test_case_insensitive_match(self):
        logger = StructuredLogger("redact-lambda")
        entry = self._capture(logger.error, "boom", ApiKey="k-123")

        assert entry["ApiKey"] == "[REDACTED]"

    def test_ordinary_fields_are_not_redacted(self):
        logger = StructuredLogger("redact-lambda")
        entry = self._capture(
            logger.info,
            "processed",
            recordCount=42,
            s3Key="prompts/file.json",
            errorType="ValueError",
        )

        assert entry["recordCount"] == 42
        assert entry["s3Key"] == "prompts/file.json"
        assert entry["errorType"] == "ValueError"

    def test_required_fields_are_never_redacted(self):
        """correlationId must survive even if a caller never overrides it."""
        logger = StructuredLogger("redact-lambda", "corr-token-123")
        entry = self._capture(logger.info, "hello")

        assert entry["correlationId"] == "corr-token-123"
