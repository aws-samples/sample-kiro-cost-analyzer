"""Tests for backend.export_handler module."""

import csv
import io
import json
import os
from unittest.mock import patch

import pytest

from backend.handlers.export_handler import (
    CSV_COLUMNS,
    _serialize_csv,
    _serialize_json,
    handle_export,
)


SAMPLE_USERS = [
    {
        "userId": "53ecfaaa-80a1-7073-9432-e0d2acdbd172",
        "subscriptionTier": "PRO_PLUS",
        "totalCredits": 125.50,
        "overageCredits": 12.30,
        "totalMessages": 450,
        "totalConversations": 28,
        "averageDailyCredits": 4.18,
    },
    {
        "userId": "user-002",
        "subscriptionTier": "PRO",
        "totalCredits": 50.0,
        "overageCredits": 0.0,
        "totalMessages": 100,
        "totalConversations": 5,
        "averageDailyCredits": 2.5,
    },
]


class TestSerializeCsv:
    def test_header_row(self):
        result = _serialize_csv([])
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert header == CSV_COLUMNS

    def test_serializes_users(self):
        result = _serialize_csv(SAMPLE_USERS)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["UserId"] == "53ecfaaa-80a1-7073-9432-e0d2acdbd172"
        assert rows[0]["SubscriptionTier"] == "PRO_PLUS"
        assert rows[0]["TotalCredits"] == "125.5"
        assert rows[0]["OverageCredits"] == "12.3"
        assert rows[0]["TotalMessages"] == "450"
        assert rows[0]["TotalConversations"] == "28"
        assert rows[0]["AverageDailyCredits"] == "4.18"

    def test_empty_users_only_header(self):
        result = _serialize_csv([])
        lines = result.strip().split("\n")
        assert len(lines) == 1
        assert lines[0].startswith("UserId")


class TestSerializeJson:
    def test_serializes_users(self):
        result = _serialize_json(SAMPLE_USERS)
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["userId"] == "53ecfaaa-80a1-7073-9432-e0d2acdbd172"
        assert parsed[1]["totalCredits"] == 50.0

    def test_empty_users(self):
        result = _serialize_json([])
        assert json.loads(result) == []


class TestHandleExport:
    @patch.dict(os.environ, {
        "GLUE_DATABASE": "test_db",
        "GLUE_TABLE": "test_table",
        "ATHENA_WORKGROUP": "test-wg",
        "ATHENA_OUTPUT_LOCATION": "s3://test-bucket/results/",
    })
    @patch("backend.handlers.export_handler.handle_usage")
    def test_json_format_default(self, mock_handle_usage):
        mock_handle_usage.return_value = {"users": SAMPLE_USERS, "summary": {}, "period": {}}

        result = handle_export({"startDate": "2026-04-01"})

        assert result["statusCode"] == 200
        assert result["contentType"] == "application/json"
        parsed = json.loads(result["body"])
        assert len(parsed) == 2
        assert parsed[0]["userId"] == SAMPLE_USERS[0]["userId"]

    @patch.dict(os.environ, {
        "GLUE_DATABASE": "test_db",
        "GLUE_TABLE": "test_table",
        "ATHENA_WORKGROUP": "test-wg",
        "ATHENA_OUTPUT_LOCATION": "s3://test-bucket/results/",
    })
    @patch("backend.handlers.export_handler.handle_usage")
    def test_json_format_explicit(self, mock_handle_usage):
        mock_handle_usage.return_value = {"users": SAMPLE_USERS, "summary": {}, "period": {}}

        result = handle_export({"format": "json"})

        assert result["contentType"] == "application/json"
        assert json.loads(result["body"]) == SAMPLE_USERS

    @patch.dict(os.environ, {
        "GLUE_DATABASE": "test_db",
        "GLUE_TABLE": "test_table",
        "ATHENA_WORKGROUP": "test-wg",
        "ATHENA_OUTPUT_LOCATION": "s3://test-bucket/results/",
    })
    @patch("backend.handlers.export_handler.handle_usage")
    def test_csv_format(self, mock_handle_usage):
        mock_handle_usage.return_value = {"users": SAMPLE_USERS, "summary": {}, "period": {}}

        result = handle_export({"format": "csv"})

        assert result["statusCode"] == 200
        assert result["contentType"] == "text/csv"
        reader = csv.DictReader(io.StringIO(result["body"]))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["UserId"] == SAMPLE_USERS[0]["userId"]

    @patch.dict(os.environ, {
        "GLUE_DATABASE": "test_db",
        "GLUE_TABLE": "test_table",
        "ATHENA_WORKGROUP": "test-wg",
        "ATHENA_OUTPUT_LOCATION": "s3://test-bucket/results/",
    })
    @patch("backend.handlers.export_handler.handle_usage")
    def test_csv_format_case_insensitive(self, mock_handle_usage):
        mock_handle_usage.return_value = {"users": [], "summary": {}, "period": {}}

        result = handle_export({"format": "CSV"})

        assert result["contentType"] == "text/csv"

    @patch.dict(os.environ, {
        "GLUE_DATABASE": "test_db",
        "GLUE_TABLE": "test_table",
        "ATHENA_WORKGROUP": "test-wg",
        "ATHENA_OUTPUT_LOCATION": "s3://test-bucket/results/",
    })
    @patch("backend.handlers.export_handler.handle_usage")
    def test_passes_filters_to_handle_usage(self, mock_handle_usage):
        mock_handle_usage.return_value = {"users": [], "summary": {}, "period": {}}

        handle_export({
            "format": "csv",
            "startDate": "2026-04-01",
            "endDate": "2026-04-30",
            "subscriptionTier": "PRO",
        })

        call_params = mock_handle_usage.call_args[0][0]
        assert call_params["startDate"] == "2026-04-01"
        assert call_params["endDate"] == "2026-04-30"
        assert call_params["subscriptionTier"] == "PRO"
        assert "format" not in call_params

    @patch.dict(os.environ, {
        "GLUE_DATABASE": "test_db",
        "GLUE_TABLE": "test_table",
        "ATHENA_WORKGROUP": "test-wg",
        "ATHENA_OUTPUT_LOCATION": "s3://test-bucket/results/",
    })
    @patch("backend.handlers.export_handler.handle_usage")
    def test_empty_result(self, mock_handle_usage):
        mock_handle_usage.return_value = {"users": [], "summary": {}, "period": {}}

        result = handle_export({"format": "json"})

        assert result["statusCode"] == 200
        assert json.loads(result["body"]) == []
