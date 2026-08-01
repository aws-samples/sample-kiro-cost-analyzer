"""Tests for SSM token resolution (agent/app/GitCorrelationAgent/tools/ssm_token.py)."""

import sys
import os
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent", "app", "GitCorrelationAgent"))

from agent.app.GitCorrelationAgent.tools.ssm_token import (
    fetch_repo_token,
    REPO_ID_PATTERN,
    SSM_TOKEN_PATH_PREFIX,
)


class FakeParameterNotFound(Exception):
    """Stand-in for botocore's ParameterNotFound client exception."""


def _make_ssm_client(get_parameter_side_effect=None, get_parameter_return_value=None):
    client = MagicMock()
    client.exceptions.ParameterNotFound = FakeParameterNotFound
    if get_parameter_side_effect is not None:
        client.get_parameter.side_effect = get_parameter_side_effect
    else:
        client.get_parameter.return_value = get_parameter_return_value
    return client


class TestFetchRepoTokenValidation:
    def test_valid_repo_id_calls_ssm_with_expected_parameter_name(self):
        client = _make_ssm_client(
            get_parameter_return_value={"Parameter": {"Value": "secret-token"}}
        )
        result = fetch_repo_token("0a1b2c3d", ssm_client=client)

        assert result == "secret-token"
        client.get_parameter.assert_called_once_with(
            Name=f"{SSM_TOKEN_PATH_PREFIX}/0a1b2c3d", WithDecryption=True
        )

    @pytest.mark.parametrize(
        "bad_repo_id",
        [
            "",
            "short",
            "TOOLONGREPOID12",
            "0A1B2C3D",  # uppercase hex rejected
            "0a1b2c3g",  # non-hex character
            "0a1b2c3d/../etc",  # path traversal attempt
            "0a1b2c3d#extra",
            "0a1b2c3d ",
            None,
        ],
    )
    def test_invalid_repo_id_returns_empty_without_calling_ssm(self, bad_repo_id):
        client = _make_ssm_client(get_parameter_return_value={})
        result = fetch_repo_token(bad_repo_id, ssm_client=client)

        assert result == ""
        client.get_parameter.assert_not_called()

    def test_repo_id_pattern_matches_generator_shape(self):
        # Mirrors uuid.uuid4().hex[:8] — 8 lowercase hex characters.
        assert REPO_ID_PATTERN.match("0123abcd")
        assert not REPO_ID_PATTERN.match("0123ABCD")


class TestFetchRepoTokenErrorHandling:
    def test_parameter_not_found_returns_empty_string(self):
        client = _make_ssm_client(get_parameter_side_effect=FakeParameterNotFound())
        result = fetch_repo_token("0a1b2c3d", ssm_client=client)

        assert result == ""

    def test_client_error_returns_empty_string(self):
        from botocore.exceptions import ClientError

        error = ClientError(
            error_response={"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            operation_name="GetParameter",
        )
        client = _make_ssm_client(get_parameter_side_effect=error)
        result = fetch_repo_token("0a1b2c3d", ssm_client=client)

        assert result == ""

    def test_missing_parameter_value_defaults_to_empty_string(self):
        client = _make_ssm_client(get_parameter_return_value={"Parameter": {}})
        result = fetch_repo_token("0a1b2c3d", ssm_client=client)

        assert result == ""


class TestFetchRepoTokenLazyClient:
    def test_creates_boto3_client_when_none_provided(self, monkeypatch):
        created_client = _make_ssm_client(
            get_parameter_return_value={"Parameter": {"Value": "lazy-token"}}
        )
        boto3_mock = MagicMock()
        boto3_mock.client.return_value = created_client
        monkeypatch.setitem(sys.modules, "boto3", boto3_mock)

        result = fetch_repo_token("0a1b2c3d")

        assert result == "lazy-token"
        boto3_mock.client.assert_called_once_with("ssm")
