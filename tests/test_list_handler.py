"""Tests for etl.list_handler module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from etl.list_handler import list_handler


ENV_VARS = {
    "PROCESSED_FILES_TABLE": "ProcessedFilesTable",
    "SSM_BUCKET_NAME": "/app/bucket",
    "SSM_SOURCE_PREFIX": "/app/prefix",
    "SSM_PROMPTS_PREFIX": "/app/prompts_prefix",
}


def _make_config(bucket="my-bucket", source_prefix="activities/AWSLogs/123/KiroLogs/",
                 prompts_prefix="prompts/AWSLogs/123/KiroLogs/", identity_store_id="",
                 source_bucket_role_arn=""):
    cfg = MagicMock()
    cfg.bucket_name = bucket
    cfg.source_prefix = source_prefix
    cfg.prompts_prefix = prompts_prefix
    cfg.identity_store_id = identity_store_id
    cfg.source_bucket_role_arn = source_bucket_role_arn
    return cfg


# ---------------------------------------------------------------------------
# Happy path — mixed CSV and prompt files
# ---------------------------------------------------------------------------

class TestListHandlerHappyPath:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.list_handler.get_processed_keys")
    @patch("etl.list_handler.list_prompt_files")
    @patch("etl.list_handler.list_csv_files")
    @patch("etl.list_handler.get_config")
    def test_returns_new_files_with_metadata(
        self, mock_config, mock_csv, mock_prompts, mock_processed
    ):
        mock_config.return_value = _make_config()
        mock_csv.return_value = ["user_report/a.csv", "user_report/b.csv"]
        mock_prompts.return_value = ["prompts/file1.json.gz", "prompts/file2.json.gz"]
        mock_processed.return_value = {"user_report/a.csv", "prompts/file1.json.gz"}

        result = list_handler({"correlationId": "exec-123"}, None)

        assert result["newFilesCount"] == 2
        assert result["totalCsvFiles"] == 2
        assert result["totalPromptFiles"] == 2
        assert result["processedCount"] == 2

        new_files = result["newFiles"]
        assert len(new_files) == 2

        csv_file = next(f for f in new_files if f["fileType"] == "csv")
        assert csv_file["key"] == "user_report/b.csv"

        prompt_file = next(f for f in new_files if f["fileType"] == "prompt")
        assert prompt_file["key"] == "prompts/file2.json.gz"

        # bucket is at the top level, not per-file
        assert result["bucket"] == "my-bucket"

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.list_handler.get_processed_keys")
    @patch("etl.list_handler.list_prompt_files")
    @patch("etl.list_handler.list_csv_files")
    @patch("etl.list_handler.get_config")
    def test_all_files_already_processed(
        self, mock_config, mock_csv, mock_prompts, mock_processed
    ):
        mock_config.return_value = _make_config()
        mock_csv.return_value = ["a.csv"]
        mock_prompts.return_value = ["b.json.gz"]
        mock_processed.return_value = {"a.csv", "b.json.gz"}

        result = list_handler({}, None)

        assert result["newFilesCount"] == 0
        assert result["newFiles"] == []
        assert result["totalCsvFiles"] == 1
        assert result["totalPromptFiles"] == 1

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.list_handler.get_processed_keys")
    @patch("etl.list_handler.list_prompt_files")
    @patch("etl.list_handler.list_csv_files")
    @patch("etl.list_handler.get_config")
    def test_no_files_at_all(
        self, mock_config, mock_csv, mock_prompts, mock_processed
    ):
        mock_config.return_value = _make_config()
        mock_csv.return_value = []
        mock_prompts.return_value = []
        mock_processed.return_value = set()

        result = list_handler({}, None)

        assert result["newFilesCount"] == 0
        assert result["newFiles"] == []
        assert result["totalCsvFiles"] == 0
        assert result["totalPromptFiles"] == 0
        assert result["processedCount"] == 0


# ---------------------------------------------------------------------------
# No prompts prefix configured
# ---------------------------------------------------------------------------

class TestListHandlerNoPrompts:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.list_handler.get_processed_keys")
    @patch("etl.list_handler.list_csv_files")
    @patch("etl.list_handler.get_config")
    def test_skips_prompt_listing_when_no_prefix(
        self, mock_config, mock_csv, mock_processed
    ):
        mock_config.return_value = _make_config(prompts_prefix="")
        mock_csv.return_value = ["a.csv", "b.csv"]
        mock_processed.return_value = set()

        result = list_handler({}, None)

        assert result["newFilesCount"] == 2
        assert result["totalPromptFiles"] == 0
        assert all(f["fileType"] == "csv" for f in result["newFiles"])


# ---------------------------------------------------------------------------
# Event handling — empty or missing correlationId
# ---------------------------------------------------------------------------

class TestListHandlerEventHandling:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.list_handler.get_processed_keys")
    @patch("etl.list_handler.list_prompt_files")
    @patch("etl.list_handler.list_csv_files")
    @patch("etl.list_handler.get_config")
    def test_handles_empty_event(
        self, mock_config, mock_csv, mock_prompts, mock_processed
    ):
        mock_config.return_value = _make_config()
        mock_csv.return_value = []
        mock_prompts.return_value = []
        mock_processed.return_value = set()

        result = list_handler({}, None)
        assert result["newFilesCount"] == 0

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.list_handler.get_processed_keys")
    @patch("etl.list_handler.list_prompt_files")
    @patch("etl.list_handler.list_csv_files")
    @patch("etl.list_handler.get_config")
    def test_handles_none_event(
        self, mock_config, mock_csv, mock_prompts, mock_processed
    ):
        mock_config.return_value = _make_config()
        mock_csv.return_value = []
        mock_prompts.return_value = []
        mock_processed.return_value = set()

        result = list_handler(None, None)
        assert result["newFilesCount"] == 0


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------

class TestListHandlerErrors:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.list_handler.get_config", side_effect=Exception("SSM error"))
    def test_config_error_propagates(self, _mock_config):
        with pytest.raises(Exception, match="SSM error"):
            list_handler({}, None)

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.list_handler.list_csv_files", side_effect=Exception("S3 access denied"))
    @patch("etl.list_handler.get_config")
    def test_s3_error_propagates(self, mock_config, _mock_csv):
        mock_config.return_value = _make_config()
        with pytest.raises(Exception, match="S3 access denied"):
            list_handler({}, None)


# ---------------------------------------------------------------------------
# File type classification
# ---------------------------------------------------------------------------

class TestFileTypeClassification:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.list_handler.get_processed_keys")
    @patch("etl.list_handler.list_prompt_files")
    @patch("etl.list_handler.list_csv_files")
    @patch("etl.list_handler.get_config")
    def test_csv_files_classified_correctly(
        self, mock_config, mock_csv, mock_prompts, mock_processed
    ):
        mock_config.return_value = _make_config()
        mock_csv.return_value = ["report/data.csv"]
        mock_prompts.return_value = []
        mock_processed.return_value = set()

        result = list_handler({}, None)

        assert result["newFiles"][0]["fileType"] == "csv"

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.list_handler.get_processed_keys")
    @patch("etl.list_handler.list_prompt_files")
    @patch("etl.list_handler.list_csv_files")
    @patch("etl.list_handler.get_config")
    def test_prompt_files_classified_correctly(
        self, mock_config, mock_csv, mock_prompts, mock_processed
    ):
        mock_config.return_value = _make_config()
        mock_csv.return_value = []
        mock_prompts.return_value = ["prompts/log.json.gz"]
        mock_processed.return_value = set()

        result = list_handler({}, None)

        assert result["newFiles"][0]["fileType"] == "prompt"
