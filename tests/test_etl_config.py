"""Tests for etl.config module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from etl.config import EtlConfig, get_config


class TestEtlConfig:
    def test_dataclass_fields(self):
        cfg = EtlConfig(
            bucket_name="my-bucket",
            source_prefix="prefix/",
            prompts_prefix="prompts/",
            identity_store_id="d-123",
            source_bucket_role_arn="arn:aws:iam::123456789012:role/my-role",
            identity_store_role_arn="arn:aws:iam::222222222222:role/idc-role",
        )
        assert cfg.bucket_name == "my-bucket"
        assert cfg.source_prefix == "prefix/"
        assert cfg.prompts_prefix == "prompts/"
        assert cfg.identity_store_id == "d-123"
        assert cfg.source_bucket_role_arn == "arn:aws:iam::123456789012:role/my-role"
        assert cfg.identity_store_role_arn == "arn:aws:iam::222222222222:role/idc-role"

    def test_frozen(self):
        cfg = EtlConfig(
            bucket_name="b",
            source_prefix="p",
            prompts_prefix="",
            identity_store_id="",
            source_bucket_role_arn="",
            identity_store_role_arn="",
        )
        with pytest.raises(AttributeError):
            cfg.bucket_name = "other"


class TestGetConfig:
    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
        "SSM_PROMPTS_PREFIX": "/kiro-cost-analyzer/prompts-prefix",
        "SSM_IDENTITY_STORE_ID": "/kiro-cost-analyzer/identity-store-id",
        "SSM_SOURCE_BUCKET_ROLE_ARN": "/kiro-cost-analyzer/source-bucket-role-arn",
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    })
    @patch("etl.config.boto3")
    def test_reads_all_ssm_parameters(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "my-source-bucket"}},
            {"Parameter": {"Value": "activities/AWSLogs/123/KiroLogs/"}},
            {"Parameter": {"Value": "prompts/AWSLogs/123/KiroLogs/"}},
            {"Parameter": {"Value": "d-94671e1709"}},
            {"Parameter": {"Value": "arn:aws:iam::111222333444:role/cross-account"}},
            {"Parameter": {"Value": "arn:aws:iam::222333444555:role/idc-role"}},
        ]

        cfg = get_config()

        mock_boto3.client.assert_called_once_with("ssm")
        assert mock_ssm.get_parameter.call_count == 6
        assert cfg.bucket_name == "my-source-bucket"
        assert cfg.source_prefix == "activities/AWSLogs/123/KiroLogs/"
        assert cfg.prompts_prefix == "prompts/AWSLogs/123/KiroLogs/"
        assert cfg.identity_store_id == "d-94671e1709"
        assert cfg.source_bucket_role_arn == "arn:aws:iam::111222333444:role/cross-account"
        assert cfg.identity_store_role_arn == "arn:aws:iam::222333444555:role/idc-role"

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
    }, clear=True)
    @patch("etl.config.boto3")
    def test_missing_optional_env_vars_returns_empty(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "my-bucket"}},
            {"Parameter": {"Value": "prefix/"}},
        ]

        cfg = get_config()

        assert cfg.bucket_name == "my-bucket"
        assert cfg.source_prefix == "prefix/"
        assert cfg.prompts_prefix == ""
        assert cfg.identity_store_id == ""
        assert cfg.source_bucket_role_arn == ""
        assert cfg.identity_store_role_arn == ""
        assert mock_ssm.get_parameter.call_count == 2

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
        "SSM_PROMPTS_PREFIX": "/kiro-cost-analyzer/prompts-prefix",
        "SSM_IDENTITY_STORE_ID": "/kiro-cost-analyzer/identity-store-id",
        "SSM_SOURCE_BUCKET_ROLE_ARN": "/kiro-cost-analyzer/source-bucket-role-arn",
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    })
    @patch("etl.config.boto3")
    def test_ssm_error_on_optional_params_returns_empty(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "my-bucket"}},
            {"Parameter": {"Value": "prefix/"}},
            Exception("ParameterNotFound"),
            Exception("ParameterNotFound"),
            Exception("ParameterNotFound"),
            Exception("ParameterNotFound"),
        ]

        cfg = get_config()

        assert cfg.bucket_name == "my-bucket"
        assert cfg.source_prefix == "prefix/"
        assert cfg.prompts_prefix == ""
        assert cfg.identity_store_id == ""
        assert cfg.source_bucket_role_arn == ""
        assert cfg.identity_store_role_arn == ""

    def test_missing_required_env_var_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(KeyError):
                get_config()


class TestIdentityStoreRoleArn:
    """Tests for the identity_store_role_arn SSM read (Requirements 2.1-2.4, 7.4)."""

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
    }, clear=True)
    @patch("etl.config.boto3")
    def test_env_var_unset_returns_empty(self, mock_boto3):
        """Case 1: SSM_IDENTITY_STORE_ROLE_ARN unset → identity_store_role_arn == ""."""
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "my-bucket"}},
            {"Parameter": {"Value": "prefix/"}},
        ]

        cfg = get_config()

        assert cfg.identity_store_role_arn == ""
        # Only the two required SSM reads occur; no read for identity_store_role_arn
        assert mock_ssm.get_parameter.call_count == 2

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=True)
    @patch("etl.config.boto3")
    def test_ssm_returns_empty_string(self, mock_boto3):
        """Case 2: SSM returns "" → identity_store_role_arn == "".

        An empty string is not the sentinel but should still resolve to "".
        The current implementation maps only "NONE" → ""; an empty raw value
        is returned as-is, which is already "". So the observable result is "".
        """
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "my-bucket"}},
            {"Parameter": {"Value": "prefix/"}},
            {"Parameter": {"Value": ""}},
        ]

        cfg = get_config()

        assert cfg.identity_store_role_arn == ""

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=True)
    @patch("etl.config.boto3")
    def test_ssm_returns_none_sentinel(self, mock_boto3):
        """Case 3: SSM returns "NONE" → identity_store_role_arn == "" (Req 2.3)."""
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "my-bucket"}},
            {"Parameter": {"Value": "prefix/"}},
            {"Parameter": {"Value": "NONE"}},
        ]

        cfg = get_config()

        assert cfg.identity_store_role_arn == ""

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=True)
    @patch("etl.config.boto3")
    def test_ssm_returns_valid_arn(self, mock_boto3):
        """Case 4: SSM returns a valid ARN → identity_store_role_arn equals it verbatim (Req 2.2)."""
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        arn = "arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read"
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "my-bucket"}},
            {"Parameter": {"Value": "prefix/"}},
            {"Parameter": {"Value": arn}},
        ]

        cfg = get_config()

        assert cfg.identity_store_role_arn == arn

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=True)
    @patch("etl.config.boto3")
    def test_ssm_get_parameter_raises_returns_empty(self, mock_boto3):
        """Case 5: SSM get_parameter raises → identity_store_role_arn == "" and get_config() still returns (Req 2.4)."""
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "my-bucket"}},
            {"Parameter": {"Value": "prefix/"}},
            Exception("ParameterNotFound"),
        ]

        cfg = get_config()

        # get_config() returned successfully and populated the empty string
        assert cfg.identity_store_role_arn == ""
        # And the rest of the config is still correct
        assert cfg.bucket_name == "my-bucket"
        assert cfg.source_prefix == "prefix/"
