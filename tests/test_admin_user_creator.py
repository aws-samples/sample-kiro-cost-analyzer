"""Unit tests for the AdminUserCreator custom resource Lambda."""

import importlib
import json
import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_event(request_type="Create", admin_email="admin@example.com", user_pool_id="us-east-1_abc123"):
    return {
        "RequestType": request_type,
        "ResponseURL": "https://cloudformation-custom-resource-response.example.com",
        "StackId": "arn:aws:cloudformation:us-east-1:123456789012:stack/test/guid",
        "RequestId": "unique-id-1234",
        "LogicalResourceId": "AdminUserCreation",
        "ResourceProperties": {
            "UserPoolId": user_pool_id,
            "AdminEmail": admin_email,
        },
    }


def _make_context():
    ctx = MagicMock()
    ctx.log_stream_name = "test-log-stream"
    return ctx


@pytest.fixture()
def mock_cognito():
    """Provide a mock cognito client and reload the module to use it."""
    mock_client = MagicMock()
    # Set up exception classes on the mock
    mock_client.exceptions.GroupExistsException = type("GroupExistsException", (Exception,), {})
    mock_client.exceptions.UsernameExistsException = type("UsernameExistsException", (Exception,), {})

    with patch("boto3.client", return_value=mock_client):
        # Remove cached module so it re-imports with the patched boto3
        for mod_name in list(sys.modules):
            if "admin_user_creator" in mod_name:
                del sys.modules[mod_name]
        if "custom_resources" in sys.modules:
            del sys.modules["custom_resources"]

        from custom_resources import admin_user_creator
        importlib.reload(admin_user_creator)
        yield mock_client, admin_user_creator


@patch("urllib.request.urlopen")
def test_create_creates_group_user_and_adds_to_group(mock_urlopen, mock_cognito):
    cognito_client, module = mock_cognito

    module.lambda_handler(_make_event("Create"), _make_context())

    cognito_client.create_group.assert_called_once_with(
        GroupName="Admins",
        UserPoolId="us-east-1_abc123",
        Description="Administrator group with full access",
    )
    cognito_client.admin_create_user.assert_called_once()
    call_kwargs = cognito_client.admin_create_user.call_args[1]
    assert call_kwargs["UserPoolId"] == "us-east-1_abc123"
    assert call_kwargs["Username"] == "admin@example.com"

    cognito_client.admin_add_user_to_group.assert_called_once_with(
        UserPoolId="us-east-1_abc123",
        Username="admin@example.com",
        GroupName="Admins",
    )

    sent_body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert sent_body["Status"] == "SUCCESS"


@patch("urllib.request.urlopen")
def test_create_handles_existing_group(mock_urlopen, mock_cognito):
    cognito_client, module = mock_cognito
    cognito_client.create_group.side_effect = cognito_client.exceptions.GroupExistsException()

    module.lambda_handler(_make_event("Create"), _make_context())

    cognito_client.admin_create_user.assert_called_once()
    cognito_client.admin_add_user_to_group.assert_called_once()
    sent_body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert sent_body["Status"] == "SUCCESS"


@patch("urllib.request.urlopen")
def test_create_handles_existing_user(mock_urlopen, mock_cognito):
    cognito_client, module = mock_cognito
    cognito_client.admin_create_user.side_effect = cognito_client.exceptions.UsernameExistsException()

    module.lambda_handler(_make_event("Create"), _make_context())

    cognito_client.admin_add_user_to_group.assert_called_once()
    sent_body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert sent_body["Status"] == "SUCCESS"


@patch("urllib.request.urlopen")
def test_update_ensures_group_and_succeeds(mock_urlopen, mock_cognito):
    cognito_client, module = mock_cognito

    module.lambda_handler(_make_event("Update"), _make_context())

    cognito_client.admin_create_user.assert_not_called()
    cognito_client.admin_add_user_to_group.assert_not_called()
    sent_body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert sent_body["Status"] == "SUCCESS"


@patch("urllib.request.urlopen")
def test_delete_is_noop(mock_urlopen, mock_cognito):
    cognito_client, module = mock_cognito

    module.lambda_handler(_make_event("Delete"), _make_context())

    cognito_client.admin_create_user.assert_not_called()
    cognito_client.admin_add_user_to_group.assert_not_called()
    sent_body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert sent_body["Status"] == "SUCCESS"


@patch("urllib.request.urlopen")
def test_error_sends_failed_response(mock_urlopen, mock_cognito):
    cognito_client, module = mock_cognito
    cognito_client.create_group.side_effect = RuntimeError("Unexpected error")

    module.lambda_handler(_make_event("Create"), _make_context())

    sent_body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert sent_body["Status"] == "FAILED"
    assert "Unexpected error" in sent_body["Reason"]
