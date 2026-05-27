"""Tests for etl.s3_reader module."""

from unittest.mock import MagicMock, patch

import pytest

from etl.s3_reader import NEW_SUBPATH, list_csv_files, read_csv_content

BUCKET = "my-source-bucket"
PREFIX = "activities/AWSLogs/123456789012/KiroLogs/"


class TestListCsvFiles:
    @patch("etl.s3_reader.boto3")
    def test_returns_csv_files_from_new_subpath(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        new_key = f"{PREFIX}{NEW_SUBPATH}us-east-1/2026/04/02/00/KIRO_IDE_123_user_report_202604020000.csv"

        mock_s3.list_objects_v2.return_value = {
            "Contents": [{"Key": new_key}],
            "IsTruncated": False,
        }

        result = list_csv_files(BUCKET, PREFIX)

        assert result == [new_key]
        assert mock_s3.list_objects_v2.call_count == 1

    @patch("etl.s3_reader.boto3")
    def test_filters_non_csv_files(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        csv_key = f"{PREFIX}{NEW_SUBPATH}region/2026/01/01/00/file.csv"
        json_key = f"{PREFIX}{NEW_SUBPATH}region/2026/01/01/00/file.json"

        mock_s3.list_objects_v2.return_value = {
            "Contents": [{"Key": csv_key}, {"Key": json_key}],
            "IsTruncated": False,
        }

        result = list_csv_files(BUCKET, PREFIX)

        assert result == [csv_key]

    @patch("etl.s3_reader.boto3")
    def test_handles_pagination(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        key1 = f"{PREFIX}{NEW_SUBPATH}r/2026/01/01/00/page1.csv"
        key2 = f"{PREFIX}{NEW_SUBPATH}r/2026/01/02/00/page2.csv"

        mock_s3.list_objects_v2.side_effect = [
            {
                "Contents": [{"Key": key1}],
                "IsTruncated": True,
                "NextContinuationToken": "token-abc",
            },
            {"Contents": [{"Key": key2}], "IsTruncated": False},
        ]

        result = list_csv_files(BUCKET, PREFIX)

        assert result == [key1, key2]
        calls = mock_s3.list_objects_v2.call_args_list
        assert calls[1][1]["ContinuationToken"] == "token-abc"

    @patch("etl.s3_reader.boto3")
    def test_empty_bucket_returns_empty_list(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        mock_s3.list_objects_v2.return_value = {"IsTruncated": False}

        result = list_csv_files(BUCKET, PREFIX)

        assert result == []

    @patch("etl.s3_reader.boto3")
    def test_uses_correct_prefix(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        mock_s3.list_objects_v2.return_value = {"IsTruncated": False}

        list_csv_files(BUCKET, PREFIX)

        calls = mock_s3.list_objects_v2.call_args_list
        assert len(calls) == 1
        assert calls[0][1]["Prefix"] == f"{PREFIX}{NEW_SUBPATH}"
        assert calls[0][1]["Bucket"] == BUCKET


class TestReadCsvContent:
    @patch("etl.s3_reader.boto3")
    def test_returns_decoded_content(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        csv_text = "UserId,Date\nuser1,2026-04-01\n"
        mock_body = MagicMock()
        mock_body.read.return_value = csv_text.encode("utf-8")
        mock_s3.get_object.return_value = {"Body": mock_body}

        result = read_csv_content(BUCKET, "some/key.csv")

        assert result == csv_text
        mock_s3.get_object.assert_called_once_with(Bucket=BUCKET, Key="some/key.csv")

    @patch("etl.s3_reader.boto3")
    def test_handles_utf8_special_characters(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        csv_text = "UserId,Name\nuser1,José García\n"
        mock_body = MagicMock()
        mock_body.read.return_value = csv_text.encode("utf-8")
        mock_s3.get_object.return_value = {"Body": mock_body}

        result = read_csv_content(BUCKET, "key.csv")

        assert "José García" in result
