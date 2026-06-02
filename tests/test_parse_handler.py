"""Tests for etl.parse_handler module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from etl.parse_handler import (
    _collect_user_ids,
    _enrich_records_with_names,
    _extract_prompt_path_metadata,
    parse_handler,
)


ENV_VARS = {
    "SOURCE_PREFIX": "activities/AWSLogs/123456789012/KiroLogs/",
    "PROMPTS_PREFIX": "prompts/AWSLogs/673826570926/KiroLogs/",
    "IDENTITY_STORE_ID": "d-1234567890",
    "USER_NAMES_TABLE": "UserNamesTable",
}


# ---------------------------------------------------------------------------
# _extract_prompt_path_metadata
# ---------------------------------------------------------------------------

class TestExtractPromptPathMetadata:
    def test_extracts_region_and_account(self):
        prefix = "prompts/AWSLogs/673826570926/KiroLogs/"
        key = f"{prefix}GenerateAssistantResponse/us-east-1/2025/01/15/14/file.json.gz"
        meta = _extract_prompt_path_metadata(key, prefix)
        assert meta["region"] == "us-east-1"
        assert meta["accountId"] == "673826570926"

    def test_missing_region(self):
        prefix = "prompts/AWSLogs/673826570926/KiroLogs/"
        key = f"{prefix}other/file.json.gz"
        meta = _extract_prompt_path_metadata(key, prefix)
        assert meta["region"] == ""
        assert meta["accountId"] == "673826570926"

    def test_no_account_in_prefix(self):
        prefix = "prompts/data/"
        key = f"{prefix}GenerateAssistantResponse/eu-west-1/2025/01/15/14/file.json.gz"
        meta = _extract_prompt_path_metadata(key, prefix)
        assert meta["region"] == "eu-west-1"
        assert meta["accountId"] == ""


# ---------------------------------------------------------------------------
# _collect_user_ids
# ---------------------------------------------------------------------------

class TestCollectUserIds:
    def test_collects_unique_ids(self):
        records = [
            {"userId": "a"},
            {"userId": "b"},
            {"userId": "a"},
            {"userId": ""},
        ]
        assert _collect_user_ids(records) == {"a", "b"}

    def test_empty_records(self):
        assert _collect_user_ids([]) == set()


# ---------------------------------------------------------------------------
# _enrich_records_with_names
# ---------------------------------------------------------------------------

class TestEnrichRecordsWithNames:
    def test_enriches_matching_records(self):
        records = [
            {"userId": "u1", "displayName": "", "userName": ""},
            {"userId": "u2", "displayName": "", "userName": ""},
        ]
        cache = {"u1": ("Alice", "alice"), "u2": ("Bob", "bob")}
        _enrich_records_with_names(records, cache)
        assert records[0]["displayName"] == "Alice"
        assert records[1]["userName"] == "bob"

    def test_skips_unknown_users(self):
        records = [{"userId": "unknown", "displayName": "orig", "userName": "orig"}]
        _enrich_records_with_names(records, {})
        assert records[0]["displayName"] == "orig"


# ---------------------------------------------------------------------------
# parse_handler — CSV path
# ---------------------------------------------------------------------------

class TestParseHandlerCsv:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.parse_handler.get_config")
    @patch("etl.parse_handler.get_identity_store_client", return_value=None)
    @patch("etl.parse_handler.get_s3_client", return_value=None)
    @patch("etl.parse_handler.resolve_names")
    @patch("etl.parse_handler.process_csv")
    @patch("etl.parse_handler.read_csv_content")
    @patch("etl.parse_handler.resolve_path_metadata")
    def test_csv_happy_path(
        self, mock_resolve_path, mock_read, mock_process, mock_names,
        _mock_s3, _mock_idc, mock_get_config,
    ):
        mock_get_config.return_value = _make_cfg()
        mock_resolve_path.return_value = {"format_type": "new", "region": "us-east-1", "account_id": "123"}
        mock_read.return_value = "csv,content"
        mock_process.return_value = [
            {"userId": "u1", "date": "2025-01-15", "totalCredits": 10, "displayName": "", "userName": ""},
        ]
        mock_names.return_value = {"u1": ("Alice", "alice")}

        event = {
            "bucket": "my-bucket",
            "key": "activities/AWSLogs/123/KiroLogs/user_report/us-east-1/2025/01/15/00/file.csv",
            "fileType": "csv",
            "correlationId": "exec-123",
        }
        result = parse_handler(event, None)

        assert result["fileType"] == "csv"
        assert result["recordCount"] == 1
        assert result["records"][0]["displayName"] == "Alice"
        mock_read.assert_called_once_with("my-bucket", event["key"], s3_client=None)

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.parse_handler.get_config")
    @patch("etl.parse_handler.get_identity_store_client", return_value=None)
    @patch("etl.parse_handler.get_s3_client", return_value=None)
    @patch("etl.parse_handler.resolve_path_metadata")
    def test_csv_unrecognised_path_returns_empty(
        self, mock_resolve_path, _mock_s3, _mock_idc, mock_get_config,
    ):
        mock_get_config.return_value = _make_cfg()
        mock_resolve_path.return_value = None

        event = {
            "bucket": "b",
            "key": "unknown/path.csv",
            "fileType": "csv",
            "correlationId": "",
        }
        result = parse_handler(event, None)
        assert result["records"] == []
        assert result["recordCount"] == 0


# ---------------------------------------------------------------------------
# parse_handler — Prompt path
# ---------------------------------------------------------------------------

class TestParseHandlerPrompt:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.parse_handler.get_config")
    @patch("etl.parse_handler.get_identity_store_client", return_value=None)
    @patch("etl.parse_handler.get_s3_client", return_value=None)
    @patch("etl.parse_handler.resolve_names")
    @patch("etl.parse_handler.process_prompts")
    @patch("etl.parse_handler.read_prompt_file")
    def test_prompt_happy_path(
        self, mock_read, mock_process, mock_names, _mock_s3, _mock_idc, mock_get_config,
    ):
        mock_get_config.return_value = _make_cfg()
        mock_read.return_value = b"\x1f\x8b..."
        mock_process.return_value = [
            {"userId": "u2", "requestId": "req-1", "displayName": "", "userName": ""},
        ]
        mock_names.return_value = {"u2": ("Bob", "bob")}

        event = {
            "bucket": "my-bucket",
            "key": "prompts/AWSLogs/673826570926/KiroLogs/GenerateAssistantResponse/us-east-1/2025/01/15/14/file.json.gz",
            "fileType": "prompt",
            "correlationId": "exec-456",
        }
        result = parse_handler(event, None)

        assert result["fileType"] == "prompt"
        assert result["recordCount"] == 1
        assert result["records"][0]["userName"] == "bob"

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.parse_handler.get_config")
    @patch("etl.parse_handler.get_identity_store_client", return_value=None)
    @patch("etl.parse_handler.get_s3_client")
    @patch("etl.parse_handler.read_prompt_file")
    def test_prompt_uses_cross_account_client(
        self, mock_read, mock_get_s3, _mock_idc, mock_get_config,
    ):
        """Regression guard: when a source bucket role ARN is configured, the
        cross-account client built by get_s3_client MUST be forwarded to
        read_prompt_file — never None (which would use the Lambda's own role and
        cause a cross-account AccessDenied)."""
        role_arn = "arn:aws:iam::111222333444:role/kiro-cost-analyzer-cross-account-read"
        mock_get_config.return_value = _make_cfg(source_bucket_role_arn=role_arn)
        xa_client = MagicMock(name="cross-account-s3")
        mock_get_s3.return_value = xa_client
        mock_read.side_effect = Exception("stop after read")

        event = {
            "bucket": "my-bucket",
            "key": "prompts/AWSLogs/673826570926/KiroLogs/GenerateAssistantResponse/us-east-1/2025/01/15/14/f.json.gz",
            "fileType": "prompt",
            "correlationId": "exec-xa",
        }
        with pytest.raises(Exception, match="stop after read"):
            parse_handler(event, None)

        mock_get_s3.assert_called_once_with(role_arn, correlation_id="exec-xa")
        mock_read.assert_called_once_with("my-bucket", event["key"], s3_client=xa_client)


# ---------------------------------------------------------------------------
# parse_handler — Error handling
# ---------------------------------------------------------------------------

class TestParseHandlerErrors:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.parse_handler.get_config")
    @patch("etl.parse_handler.get_identity_store_client", return_value=None)
    @patch("etl.parse_handler.get_s3_client", return_value=None)
    def test_unknown_file_type_raises(self, _mock_s3, _mock_idc, mock_get_config):
        mock_get_config.return_value = _make_cfg()
        event = {
            "bucket": "b",
            "key": "k",
            "fileType": "parquet",
            "correlationId": "",
        }
        with pytest.raises(ValueError, match="Unknown fileType"):
            parse_handler(event, None)

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.parse_handler.get_config")
    @patch("etl.parse_handler.get_identity_store_client", return_value=None)
    @patch("etl.parse_handler.get_s3_client", return_value=None)
    @patch("etl.parse_handler.read_csv_content", side_effect=Exception("S3 error"))
    @patch("etl.parse_handler.resolve_path_metadata", return_value={"format_type": "new"})
    def test_s3_error_propagates(
        self, _mock_path, _mock_read, _mock_s3, _mock_idc, mock_get_config,
    ):
        mock_get_config.return_value = _make_cfg()
        event = {
            "bucket": "b",
            "key": "k",
            "fileType": "csv",
            "correlationId": "",
        }
        with pytest.raises(Exception, match="S3 error"):
            parse_handler(event, None)

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.parse_handler.get_config", side_effect=KeyError("SSM_BUCKET_NAME"))
    def test_config_error_propagates(self, _mock_get_config):
        """Regression guard: a config-read failure must propagate (Step Functions
        retries) — it must NOT be swallowed into single-account mode."""
        event = {
            "bucket": "b",
            "key": "k",
            "fileType": "csv",
            "correlationId": "",
        }
        with pytest.raises(KeyError):
            parse_handler(event, None)


# ---------------------------------------------------------------------------
# parse_handler — cross-account Identity Center wiring
# (Feature: cross-account-identity-center, task 5.2)
# ---------------------------------------------------------------------------


def _make_cfg(identity_store_role_arn: str = "", source_bucket_role_arn: str = ""):
    """Build a minimal EtlConfig-like stub for parse_handler tests.

    Using a plain ``MagicMock`` with explicit attributes keeps the test
    independent of any future fields added to ``EtlConfig`` while still
    exercising the attribute-access path inside ``parse_handler``.
    """
    cfg = MagicMock()
    cfg.bucket_name = "my-bucket"
    cfg.source_prefix = ENV_VARS["SOURCE_PREFIX"]
    cfg.prompts_prefix = ENV_VARS["PROMPTS_PREFIX"]
    cfg.identity_store_id = ENV_VARS["IDENTITY_STORE_ID"]
    cfg.source_bucket_role_arn = source_bucket_role_arn
    cfg.identity_store_role_arn = identity_store_role_arn
    return cfg


class TestParseHandlerCrossAccountIdentityCenter:
    """Verify the ParseFunction ↔ ``get_identity_store_client`` ↔ ``resolve_names`` wiring.

    Validates Requirements 4.1, 4.3, 7.1, 7.2, 8.5 from
    ``.kiro/specs/cross-account-identity-center/requirements.md``.
    """

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.parse_handler.resolve_names")
    @patch("etl.parse_handler.process_csv")
    @patch("etl.parse_handler.read_csv_content")
    @patch("etl.parse_handler.resolve_path_metadata")
    @patch("etl.parse_handler.get_s3_client")
    @patch("etl.parse_handler.get_identity_store_client")
    @patch("etl.parse_handler.get_config")
    def test_cross_account_mode_forwards_injected_client(
        self,
        mock_get_config,
        mock_get_idc_client,
        mock_get_s3_client,
        mock_resolve_path,
        mock_read,
        mock_process,
        mock_names,
    ):
        """Req 4.1/4.3: non-empty ARN → client built via STS, forwarded to resolve_names."""
        role_arn = "arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read"
        mock_get_config.return_value = _make_cfg(identity_store_role_arn=role_arn)
        mock_get_s3_client.return_value = None

        injected_idc_client = MagicMock(name="cross-account-identitystore-client")
        mock_get_idc_client.return_value = injected_idc_client

        mock_resolve_path.return_value = {
            "format_type": "new",
            "region": "us-east-1",
            "account_id": "123",
        }
        mock_read.return_value = "csv,content"
        mock_process.return_value = [
            {"userId": "u1", "date": "2025-01-15", "totalCredits": 1, "displayName": "", "userName": ""},
        ]
        mock_names.return_value = {"u1": ("Alice", "alice")}

        event = {
            "bucket": "my-bucket",
            "key": "activities/AWSLogs/123/KiroLogs/user_report/us-east-1/2025/01/15/00/file.csv",
            "fileType": "csv",
            "correlationId": "exec-idc-xa",
        }
        result = parse_handler(event, None)

        # get_identity_store_client called with the configured ARN + correlation id
        mock_get_idc_client.assert_called_once_with(role_arn, correlation_id="exec-idc-xa")

        # The exact mock returned by the factory is forwarded into resolve_names
        assert mock_names.call_count == 1
        _, kwargs = mock_names.call_args
        assert kwargs["identity_client"] is injected_idc_client
        assert kwargs["identity_store_id"] == ENV_VARS["IDENTITY_STORE_ID"]
        assert kwargs["user_ids"] == {"u1"}

        # Records were enriched and returned as usual
        assert result["recordCount"] == 1
        assert result["records"][0]["displayName"] == "Alice"

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.parse_handler.resolve_names")
    @patch("etl.parse_handler.process_csv")
    @patch("etl.parse_handler.read_csv_content")
    @patch("etl.parse_handler.resolve_path_metadata")
    @patch("etl.parse_handler.get_s3_client")
    @patch("etl.parse_handler.get_identity_store_client")
    @patch("etl.parse_handler.get_config")
    def test_single_account_mode_forwards_none(
        self,
        mock_get_config,
        mock_get_idc_client,
        mock_get_s3_client,
        mock_resolve_path,
        mock_read,
        mock_process,
        mock_names,
    ):
        """Req 7.1/7.2: empty ARN → get_identity_store_client returns None, forwarded as None."""
        mock_get_config.return_value = _make_cfg(identity_store_role_arn="")
        mock_get_s3_client.return_value = None
        # Mirror the real sts_session contract: empty ARN returns None.
        mock_get_idc_client.return_value = None

        mock_resolve_path.return_value = {
            "format_type": "new",
            "region": "us-east-1",
            "account_id": "123",
        }
        mock_read.return_value = "csv,content"
        mock_process.return_value = [
            {"userId": "u1", "date": "2025-01-15", "totalCredits": 1, "displayName": "", "userName": ""},
        ]
        mock_names.return_value = {"u1": ("Alice", "alice")}

        event = {
            "bucket": "my-bucket",
            "key": "activities/AWSLogs/123/KiroLogs/user_report/us-east-1/2025/01/15/00/file.csv",
            "fileType": "csv",
            "correlationId": "exec-idc-single",
        }
        parse_handler(event, None)

        # Factory is always consulted — it's the one that decides single vs cross-account
        mock_get_idc_client.assert_called_once_with("", correlation_id="exec-idc-single")

        # resolve_names receives identity_client=None (single-account fallback)
        _, kwargs = mock_names.call_args
        assert kwargs["identity_client"] is None

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.parse_handler.resolve_names")
    @patch("etl.parse_handler.process_csv")
    @patch("etl.parse_handler.read_csv_content")
    @patch("etl.parse_handler.resolve_path_metadata")
    @patch("etl.parse_handler.get_s3_client")
    @patch("etl.parse_handler.get_identity_store_client")
    @patch("etl.parse_handler.get_config")
    def test_identity_store_client_build_failure_falls_back_to_none(
        self,
        mock_get_config,
        mock_get_idc_client,
        mock_get_s3_client,
        mock_resolve_path,
        mock_read,
        mock_process,
        mock_names,
    ):
        """Req 8.5: if get_identity_store_client raises, parse_handler still completes with None."""
        role_arn = "arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read"
        mock_get_config.return_value = _make_cfg(identity_store_role_arn=role_arn)
        mock_get_s3_client.return_value = None
        mock_get_idc_client.side_effect = RuntimeError("AssumeRole failed")

        mock_resolve_path.return_value = {
            "format_type": "new",
            "region": "us-east-1",
            "account_id": "123",
        }
        mock_read.return_value = "csv,content"
        mock_process.return_value = [
            {"userId": "u1", "date": "2025-01-15", "totalCredits": 1, "displayName": "", "userName": ""},
        ]
        mock_names.return_value = {"u1": ("", "")}

        event = {
            "bucket": "my-bucket",
            "key": "activities/AWSLogs/123/KiroLogs/user_report/us-east-1/2025/01/15/00/file.csv",
            "fileType": "csv",
            "correlationId": "exec-idc-fallback",
        }
        # Must NOT raise — fallback swallows the STS error
        result = parse_handler(event, None)

        mock_get_idc_client.assert_called_once_with(role_arn, correlation_id="exec-idc-fallback")

        # resolve_names still invoked, with identity_client=None
        assert mock_names.call_count == 1
        _, kwargs = mock_names.call_args
        assert kwargs["identity_client"] is None

        # Pipeline continues — handler returns a result envelope as usual
        assert result["fileType"] == "csv"
        assert result["recordCount"] == 1
