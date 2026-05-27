"""Tests for etl.processing_tracker module."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from etl.processing_tracker import filter_new_files, get_processed_keys, mark_as_processed

TABLE_NAME = "ProcessedFilesTable"


# ---------------------------------------------------------------------------
# get_processed_keys
# ---------------------------------------------------------------------------
class TestGetProcessedKeys:
    def test_returns_all_file_keys(self):
        mock_table = MagicMock()
        mock_table.scan.return_value = {
            "Items": [{"fileKey": "a.csv"}, {"fileKey": "b.csv"}],
        }
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        result = get_processed_keys(TABLE_NAME, dynamodb=mock_dynamodb)

        assert result == {"a.csv", "b.csv"}
        mock_dynamodb.Table.assert_called_once_with(TABLE_NAME)
        mock_table.scan.assert_called_once_with(ProjectionExpression="fileKey")

    def test_handles_pagination(self):
        mock_table = MagicMock()
        mock_table.scan.side_effect = [
            {
                "Items": [{"fileKey": "page1.csv"}],
                "LastEvaluatedKey": {"fileKey": "page1.csv"},
            },
            {
                "Items": [{"fileKey": "page2.csv"}],
            },
        ]
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        result = get_processed_keys(TABLE_NAME, dynamodb=mock_dynamodb)

        assert result == {"page1.csv", "page2.csv"}
        assert mock_table.scan.call_count == 2
        # Second call should include ExclusiveStartKey
        second_call = mock_table.scan.call_args_list[1]
        assert second_call[1]["ExclusiveStartKey"] == {"fileKey": "page1.csv"}

    def test_empty_table_returns_empty_set(self):
        mock_table = MagicMock()
        mock_table.scan.return_value = {"Items": []}
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        result = get_processed_keys(TABLE_NAME, dynamodb=mock_dynamodb)

        assert result == set()

    def test_uses_default_dynamodb_when_none(self):
        with patch("etl.processing_tracker.boto3") as mock_boto3:
            mock_table = MagicMock()
            mock_table.scan.return_value = {"Items": []}
            mock_resource = MagicMock()
            mock_resource.Table.return_value = mock_table
            mock_boto3.resource.return_value = mock_resource

            get_processed_keys(TABLE_NAME)

            mock_boto3.resource.assert_called_once_with("dynamodb")


# ---------------------------------------------------------------------------
# mark_as_processed
# ---------------------------------------------------------------------------
class TestMarkAsProcessed:
    def test_puts_item_with_all_fields(self):
        mock_table = MagicMock()
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        mark_as_processed(
            TABLE_NAME, "path/to/file.csv", 42, "SUCCESS", dynamodb=mock_dynamodb
        )

        mock_dynamodb.Table.assert_called_once_with(TABLE_NAME)
        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["fileKey"] == "path/to/file.csv"
        assert item["recordCount"] == 42
        assert item["status"] == "SUCCESS"
        assert item["errorMessage"] == ""
        # processedAt should be a valid ISO timestamp
        datetime.fromisoformat(item["processedAt"])

    def test_records_error_message(self):
        mock_table = MagicMock()
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        mark_as_processed(
            TABLE_NAME,
            "bad/file.csv",
            0,
            "ERROR",
            error_message="Invalid format",
            dynamodb=mock_dynamodb,
        )

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["status"] == "ERROR"
        assert item["errorMessage"] == "Invalid format"
        assert item["recordCount"] == 0

    def test_uses_default_dynamodb_when_none(self):
        with patch("etl.processing_tracker.boto3") as mock_boto3:
            mock_table = MagicMock()
            mock_resource = MagicMock()
            mock_resource.Table.return_value = mock_table
            mock_boto3.resource.return_value = mock_resource

            mark_as_processed(TABLE_NAME, "k.csv", 1, "SUCCESS")

            mock_boto3.resource.assert_called_once_with("dynamodb")


# ---------------------------------------------------------------------------
# filter_new_files
# ---------------------------------------------------------------------------
class TestFilterNewFiles:
    def test_filters_already_processed(self):
        all_keys = ["a.csv", "b.csv", "c.csv"]
        processed = {"a.csv", "c.csv"}

        result = filter_new_files(all_keys, processed)

        assert result == ["b.csv"]

    def test_returns_all_when_none_processed(self):
        all_keys = ["x.csv", "y.csv"]

        result = filter_new_files(all_keys, set())

        assert result == ["x.csv", "y.csv"]

    def test_returns_empty_when_all_processed(self):
        all_keys = ["a.csv", "b.csv"]
        processed = {"a.csv", "b.csv"}

        result = filter_new_files(all_keys, processed)

        assert result == []

    def test_empty_inputs(self):
        assert filter_new_files([], set()) == []
        assert filter_new_files([], {"a.csv"}) == []

    def test_preserves_order(self):
        all_keys = ["z.csv", "a.csv", "m.csv"]
        processed = {"a.csv"}

        result = filter_new_files(all_keys, processed)

        assert result == ["z.csv", "m.csv"]
