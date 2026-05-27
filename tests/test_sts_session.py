"""Tests for etl.sts_session module.

Covers:
- ``get_identity_store_client`` — the new cross-account Identity Store factory.
- ``get_s3_client`` — regression guard for the refactor in task 2.1.

Feature: cross-account-identity-center (design task 2.3).
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from etl.sts_session import (
    _build_session_name,
    get_identity_store_client,
    get_s3_client,
)


# ---------------------------------------------------------------------------
# get_identity_store_client — single-account bypass
# ---------------------------------------------------------------------------


class TestGetIdentityStoreClientSingleAccountMode:
    """``role_arn`` empty or None must short-circuit without touching STS."""

    def test_empty_string_returns_none_and_skips_sts(self):
        with patch("etl.sts_session.boto3") as mock_boto3:
            result = get_identity_store_client("")
        assert result is None
        # Neither sts nor identitystore clients should be constructed
        mock_boto3.client.assert_not_called()

    def test_none_returns_none_and_skips_sts(self):
        with patch("etl.sts_session.boto3") as mock_boto3:
            result = get_identity_store_client(None)  # type: ignore[arg-type]
        assert result is None
        mock_boto3.client.assert_not_called()


# ---------------------------------------------------------------------------
# get_identity_store_client — cross-account happy path via moto
# ---------------------------------------------------------------------------


class TestGetIdentityStoreClientCrossAccount:
    """A non-empty ARN drives an AssumeRole and builds an ``identitystore`` client."""

    @mock_aws
    def test_returns_identitystore_client_with_assumed_credentials(self):
        role_arn = "arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read"
        # Region is required for boto3 when no env is set; rely on AWS_DEFAULT_REGION
        with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}):
            client = get_identity_store_client(role_arn, correlation_id="corr-1")

        assert client is not None
        # Verify the client speaks the identitystore service model
        assert client.meta.service_model.service_name == "identitystore"

    @mock_aws
    def test_calls_sts_assume_role_with_expected_parameters(self):
        """STS AssumeRole must receive the ARN, the computed session name, and 3600s."""
        role_arn = "arn:aws:iam::333333333333:role/identity-store-read"

        captured: dict = {}
        real_sts = boto3.client("sts", region_name="us-east-1")

        original_assume = real_sts.assume_role

        def _spy_assume_role(**kwargs):
            captured.update(kwargs)
            return original_assume(**kwargs)

        with patch("etl.sts_session.boto3") as mock_boto3:
            # Delegate all creation back to real moto-backed boto3, but spy on sts
            def _client_factory(service_name, **kwargs):
                if service_name == "sts":
                    sts = boto3.client("sts", region_name="us-east-1")
                    sts.assume_role = _spy_assume_role  # type: ignore[assignment]
                    return sts
                return boto3.client(service_name, **kwargs)

            mock_boto3.client.side_effect = _client_factory

            with patch.dict(
                os.environ,
                {
                    "AWS_DEFAULT_REGION": "us-east-1",
                    "AWS_LAMBDA_FUNCTION_NAME": "my-parse-fn",
                },
            ):
                client = get_identity_store_client(role_arn)

        assert client is not None
        assert captured["RoleArn"] == role_arn
        assert captured["DurationSeconds"] == 3600
        assert captured["RoleSessionName"] == "kiro-etl-my-parse-fn"


# ---------------------------------------------------------------------------
# get_identity_store_client — AccessDeniedException path
# ---------------------------------------------------------------------------


class TestGetIdentityStoreClientAccessDenied:
    """STS AccessDenied must be logged via StructuredLogger and re-raised."""

    def test_access_denied_logs_and_reraises(self):
        role_arn = "arn:aws:iam::444444444444:role/forbidden"
        access_denied = ClientError(
            error_response={
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": "User is not authorized to perform sts:AssumeRole",
                }
            },
            operation_name="AssumeRole",
        )

        fake_sts = MagicMock()
        fake_sts.assume_role.side_effect = access_denied

        with patch("etl.sts_session.boto3") as mock_boto3:
            mock_boto3.client.return_value = fake_sts
            # Capture StructuredLogger JSON emissions (it uses print under the hood)
            with patch("builtins.print") as mock_print:
                with pytest.raises(ClientError) as excinfo:
                    get_identity_store_client(role_arn, correlation_id="corr-ad")

        # Error is propagated unchanged
        assert "AccessDenied" in str(excinfo.value)

        # Extract every structured log entry written during the call
        entries = [
            json.loads(call.args[0])
            for call in mock_print.call_args_list
            if call.args and isinstance(call.args[0], str)
        ]

        error_entries = [e for e in entries if e.get("level") == "ERROR"]
        assert error_entries, "Expected at least one ERROR log entry"

        # The primary failure log must include the documented structured fields
        primary = next(
            (e for e in error_entries if e["message"] == "Failed to assume cross-account role"),
            None,
        )
        assert primary is not None, (
            f"Expected the 'Failed to assume cross-account role' log; got {error_entries}"
        )
        assert primary["roleArn"] == role_arn
        assert primary["sessionName"].startswith("kiro-etl-")
        assert primary["errorType"] == "ClientError"
        assert "AccessDenied" in primary["errorMessage"]
        assert primary["correlationId"] == "corr-ad"
        assert primary["lambda"] == "sts-session-manager"

        # An AccessDenied-specific hint must also be emitted
        hint = next(
            (e for e in error_entries if "trust policy" in e["message"].lower()),
            None,
        )
        assert hint is not None, (
            f"Expected an AccessDenied hint log; got {error_entries}"
        )
        assert hint["roleArn"] == role_arn


# ---------------------------------------------------------------------------
# RoleSessionName format and DurationSeconds contract
# ---------------------------------------------------------------------------


class TestRoleSessionNameAndDuration:
    """Pin the ``kiro-etl-{AWS_LAMBDA_FUNCTION_NAME}`` format and 3600s duration."""

    def test_build_session_name_uses_lambda_function_name(self):
        with patch.dict(os.environ, {"AWS_LAMBDA_FUNCTION_NAME": "parse-fn"}):
            assert _build_session_name() == "kiro-etl-parse-fn"

    def test_build_session_name_falls_back_to_unknown(self):
        env_no_fn = {k: v for k, v in os.environ.items() if k != "AWS_LAMBDA_FUNCTION_NAME"}
        with patch.dict(os.environ, env_no_fn, clear=True):
            assert _build_session_name() == "kiro-etl-unknown"

    def test_assume_role_receives_session_name_and_duration_3600(self):
        """Covers Requirements 3.2, 3.3, 3.7, 9.1 and 9.5 end-to-end."""
        role_arn = "arn:aws:iam::555555555555:role/ids"
        fake_sts = MagicMock()
        fake_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIAEXAMPLE",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            }
        }
        fake_identity = MagicMock()

        with patch("etl.sts_session.boto3") as mock_boto3:
            def _client_factory(service_name, **kwargs):
                if service_name == "sts":
                    return fake_sts
                if service_name == "identitystore":
                    return fake_identity
                raise AssertionError(f"Unexpected client: {service_name}")

            mock_boto3.client.side_effect = _client_factory

            with patch.dict(os.environ, {"AWS_LAMBDA_FUNCTION_NAME": "etl-parse-abc"}):
                result = get_identity_store_client(role_arn)

        assert result is fake_identity
        fake_sts.assume_role.assert_called_once_with(
            RoleArn=role_arn,
            RoleSessionName="kiro-etl-etl-parse-abc",
            DurationSeconds=3600,
        )
        # identitystore client must be built from the temporary credentials
        identity_call = next(
            c
            for c in mock_boto3.client.call_args_list
            if c.args and c.args[0] == "identitystore"
        )
        assert identity_call.kwargs["aws_access_key_id"] == "AKIAEXAMPLE"
        assert identity_call.kwargs["aws_secret_access_key"] == "secret"
        assert identity_call.kwargs["aws_session_token"] == "token"


# ---------------------------------------------------------------------------
# get_s3_client regression — refactor from task 2.1 must preserve behavior
# ---------------------------------------------------------------------------


class TestGetS3ClientRegression:
    """The refactor that introduced ``_assume_role`` must not change behavior."""

    def test_empty_arn_returns_none(self):
        with patch("etl.sts_session.boto3") as mock_boto3:
            assert get_s3_client("") is None
        mock_boto3.client.assert_not_called()

    def test_none_arn_returns_none(self):
        with patch("etl.sts_session.boto3") as mock_boto3:
            assert get_s3_client(None) is None  # type: ignore[arg-type]
        mock_boto3.client.assert_not_called()

    @mock_aws
    def test_non_empty_arn_returns_s3_client(self):
        role_arn = "arn:aws:iam::666666666666:role/kiro-cost-analyzer-cross-account-read"
        with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}):
            client = get_s3_client(role_arn, correlation_id="corr-2")
        assert client is not None
        assert client.meta.service_model.service_name == "s3"
