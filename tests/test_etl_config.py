"""Tests for etl.config module.

Config is read in a single batched ``ssm:GetParameters`` call and cached per
warm container. Key behaviors under test:

- Absent optional parameters (env var unset, or returned under
  ``InvalidParameters``) resolve to "".
- The ``"NONE"`` sentinel resolves to "".
- A transient SSM error (throttling) raises from the batched call and
  PROPAGATES — config must never silently degrade to single-account mode. This
  is the fix for the intermittent cross-account AccessDenied caused by a
  throttled role-arn read falling through to "".
- The per-container cache returns the same object until ``reset_cache()``.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from botocore.exceptions import ClientError

from etl.config import EtlConfig, get_config, reset_cache

ALL_ENV = {
    "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
    "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
    "SSM_PROMPTS_PREFIX": "/kiro-cost-analyzer/prompts-prefix",
    "SSM_IDENTITY_STORE_ID": "/kiro-cost-analyzer/identity-store-id",
    "SSM_SOURCE_BUCKET_ROLE_ARN": "/kiro-cost-analyzer/source-bucket-role-arn",
    "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
}

REQUIRED_ENV = {
    "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
    "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
}


def _params(mapping: dict) -> dict:
    """Build a GetParameters response from a {name: value} mapping."""
    return {"Parameters": [{"Name": n, "Value": v} for n, v in mapping.items()]}


def _throttling_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "GetParameters",
    )


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """Isolate every test from the per-container config cache."""
    reset_cache()
    yield
    reset_cache()


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
    @patch.dict(os.environ, ALL_ENV, clear=True)
    @patch("etl.config.boto3")
    def test_reads_all_ssm_parameters(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameters.return_value = _params({
            ALL_ENV["SSM_BUCKET_NAME"]: "my-source-bucket",
            ALL_ENV["SSM_SOURCE_PREFIX"]: "activities/AWSLogs/123/KiroLogs/",
            ALL_ENV["SSM_PROMPTS_PREFIX"]: "prompts/AWSLogs/123/KiroLogs/",
            ALL_ENV["SSM_IDENTITY_STORE_ID"]: "d-94671e1709",
            ALL_ENV["SSM_SOURCE_BUCKET_ROLE_ARN"]: "arn:aws:iam::111222333444:role/cross-account",
            ALL_ENV["SSM_IDENTITY_STORE_ROLE_ARN"]: "arn:aws:iam::222333444555:role/idc-role",
        })

        cfg = get_config()

        # A single batched read regardless of how many parameters.
        mock_ssm.get_parameters.assert_called_once()
        assert cfg.bucket_name == "my-source-bucket"
        assert cfg.source_prefix == "activities/AWSLogs/123/KiroLogs/"
        assert cfg.prompts_prefix == "prompts/AWSLogs/123/KiroLogs/"
        assert cfg.identity_store_id == "d-94671e1709"
        assert cfg.source_bucket_role_arn == "arn:aws:iam::111222333444:role/cross-account"
        assert cfg.identity_store_role_arn == "arn:aws:iam::222333444555:role/idc-role"

    @patch.dict(os.environ, REQUIRED_ENV, clear=True)
    @patch("etl.config.boto3")
    def test_missing_optional_env_vars_returns_empty(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameters.return_value = _params({
            REQUIRED_ENV["SSM_BUCKET_NAME"]: "my-bucket",
            REQUIRED_ENV["SSM_SOURCE_PREFIX"]: "prefix/",
        })

        cfg = get_config()

        assert cfg.bucket_name == "my-bucket"
        assert cfg.source_prefix == "prefix/"
        assert cfg.prompts_prefix == ""
        assert cfg.identity_store_id == ""
        assert cfg.source_bucket_role_arn == ""
        assert cfg.identity_store_role_arn == ""

    @patch.dict(os.environ, ALL_ENV, clear=True)
    @patch("etl.config.boto3")
    def test_absent_optional_params_resolve_empty(self, mock_boto3):
        """Optional params returned under InvalidParameters (not present in
        Parameters) resolve to "" — a genuinely absent parameter is not an
        error."""
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        # Only the two required params come back; the rest are "absent".
        mock_ssm.get_parameters.return_value = _params({
            ALL_ENV["SSM_BUCKET_NAME"]: "my-bucket",
            ALL_ENV["SSM_SOURCE_PREFIX"]: "prefix/",
        })

        cfg = get_config()

        assert cfg.bucket_name == "my-bucket"
        assert cfg.source_prefix == "prefix/"
        assert cfg.prompts_prefix == ""
        assert cfg.identity_store_id == ""
        assert cfg.source_bucket_role_arn == ""
        assert cfg.identity_store_role_arn == ""

    @patch.dict(os.environ, ALL_ENV, clear=True)
    @patch("etl.config.boto3")
    def test_transient_ssm_error_propagates(self, mock_boto3):
        """A throttling error must PROPAGATE, not degrade to single-account
        mode. This is the regression guard for the intermittent cross-account
        AccessDenied bug."""
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameters.side_effect = _throttling_error()

        with pytest.raises(ClientError):
            get_config()

    def test_missing_required_env_var_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(KeyError):
                get_config()

    @patch.dict(os.environ, ALL_ENV, clear=True)
    @patch("etl.config.boto3")
    def test_cache_returns_same_object(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameters.return_value = _params({
            ALL_ENV["SSM_BUCKET_NAME"]: "my-bucket",
            ALL_ENV["SSM_SOURCE_PREFIX"]: "prefix/",
        })

        first = get_config()
        second = get_config()

        assert first is second
        # Cached: SSM is read once across both calls.
        mock_ssm.get_parameters.assert_called_once()


class TestRoleArnResolution:
    """The "NONE" sentinel and verbatim ARN handling for both role ARNs."""

    @patch.dict(os.environ, ALL_ENV, clear=True)
    @patch("etl.config.boto3")
    def test_none_sentinel_resolves_empty(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_ssm.get_parameters.return_value = _params({
            ALL_ENV["SSM_BUCKET_NAME"]: "my-bucket",
            ALL_ENV["SSM_SOURCE_PREFIX"]: "prefix/",
            ALL_ENV["SSM_SOURCE_BUCKET_ROLE_ARN"]: "NONE",
            ALL_ENV["SSM_IDENTITY_STORE_ROLE_ARN"]: "NONE",
        })

        cfg = get_config()

        assert cfg.source_bucket_role_arn == ""
        assert cfg.identity_store_role_arn == ""

    @patch.dict(os.environ, ALL_ENV, clear=True)
    @patch("etl.config.boto3")
    def test_valid_arn_returned_verbatim(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        src = "arn:aws:iam::111222333444:role/kiro-cost-analyzer-cross-account-read"
        idc = "arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read"
        mock_ssm.get_parameters.return_value = _params({
            ALL_ENV["SSM_BUCKET_NAME"]: "my-bucket",
            ALL_ENV["SSM_SOURCE_PREFIX"]: "prefix/",
            ALL_ENV["SSM_SOURCE_BUCKET_ROLE_ARN"]: src,
            ALL_ENV["SSM_IDENTITY_STORE_ROLE_ARN"]: idc,
        })

        cfg = get_config()

        assert cfg.source_bucket_role_arn == src
        assert cfg.identity_store_role_arn == idc
