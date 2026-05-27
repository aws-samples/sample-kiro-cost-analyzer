"""Tests for etl.prompt_s3_reader module."""

from unittest.mock import MagicMock, patch

import pytest

from etl.prompt_s3_reader import PROMPT_SUBPATH, list_prompt_files, read_prompt_file

BUCKET = "my-source-bucket"
PREFIX = "prompts/AWSLogs/673826570926/KiroLogs/"


class TestListPromptFiles:
    @patch("etl.prompt_s3_reader.boto3")
    def test_returns_json_gz_files(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        gz_key = f"{PREFIX}{PROMPT_SUBPATH}us-east-1/2026/04/10/14/prompt_log.json.gz"

        mock_s3.list_objects_v2.return_value = {
            "Contents": [{"Key": gz_key}],
            "IsTruncated": False,
        }

        result = list_prompt_files(BUCKET, PREFIX)

        assert result == [gz_key]
        assert mock_s3.list_objects_v2.call_count == 1

    @patch("etl.prompt_s3_reader.boto3")
    def test_filters_non_json_gz_files(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        gz_key = f"{PREFIX}{PROMPT_SUBPATH}us-east-1/2026/04/10/14/log.json.gz"
        csv_key = f"{PREFIX}{PROMPT_SUBPATH}us-east-1/2026/04/10/14/file.csv"
        json_key = f"{PREFIX}{PROMPT_SUBPATH}us-east-1/2026/04/10/14/file.json"

        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": gz_key},
                {"Key": csv_key},
                {"Key": json_key},
            ],
            "IsTruncated": False,
        }

        result = list_prompt_files(BUCKET, PREFIX)

        assert result == [gz_key]

    @patch("etl.prompt_s3_reader.boto3")
    def test_handles_pagination(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        key1 = f"{PREFIX}{PROMPT_SUBPATH}us-east-1/2026/04/10/14/page1.json.gz"
        key2 = f"{PREFIX}{PROMPT_SUBPATH}us-east-1/2026/04/11/08/page2.json.gz"

        mock_s3.list_objects_v2.side_effect = [
            {
                "Contents": [{"Key": key1}],
                "IsTruncated": True,
                "NextContinuationToken": "token-abc",
            },
            {"Contents": [{"Key": key2}], "IsTruncated": False},
        ]

        result = list_prompt_files(BUCKET, PREFIX)

        assert result == [key1, key2]
        calls = mock_s3.list_objects_v2.call_args_list
        assert calls[1][1]["ContinuationToken"] == "token-abc"

    @patch("etl.prompt_s3_reader.boto3")
    def test_empty_bucket_returns_empty_list(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        mock_s3.list_objects_v2.return_value = {"IsTruncated": False}

        result = list_prompt_files(BUCKET, PREFIX)

        assert result == []

    @patch("etl.prompt_s3_reader.boto3")
    def test_uses_correct_prefix(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        mock_s3.list_objects_v2.return_value = {"IsTruncated": False}

        list_prompt_files(BUCKET, PREFIX)

        calls = mock_s3.list_objects_v2.call_args_list
        assert len(calls) == 1
        assert calls[0][1]["Prefix"] == f"{PREFIX}{PROMPT_SUBPATH}"
        assert calls[0][1]["Bucket"] == BUCKET


class TestReadPromptFile:
    @patch("etl.prompt_s3_reader.boto3")
    def test_returns_raw_bytes(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        raw_bytes = b"\x1f\x8b\x08\x00fake-gzip-content"
        mock_body = MagicMock()
        mock_body.read.return_value = raw_bytes
        mock_s3.get_object.return_value = {"Body": mock_body}

        result = read_prompt_file(BUCKET, "some/key.json.gz")

        assert result == raw_bytes
        mock_s3.get_object.assert_called_once_with(
            Bucket=BUCKET, Key="some/key.json.gz"
        )
