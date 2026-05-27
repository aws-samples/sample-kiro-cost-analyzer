"""Tests for backend.users_handler module."""

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.handlers.users_handler import (
    _map_user,
    handle_create_user,
    handle_delete_user,
    handle_list_users,
)


class TestMapUser:
    def test_maps_cognito_user_to_simplified_dict(self):
        cognito_user = {
            "Username": "abc-123",
            "Attributes": [
                {"Name": "email", "Value": "user@example.com"},
                {"Name": "sub", "Value": "abc-123"},
            ],
            "UserStatus": "CONFIRMED",
            "Enabled": True,
            "UserCreateDate": datetime(2026, 4, 1, 10, 0, 0),
        }

        result = _map_user(cognito_user)

        assert result["username"] == "abc-123"
        assert result["email"] == "user@example.com"
        assert result["status"] == "CONFIRMED"
        assert result["enabled"] is True
        assert "2026" in result["createdAt"]

    def test_handles_missing_attributes(self):
        cognito_user = {
            "Username": "xyz",
            "Attributes": [],
            "UserStatus": "FORCE_CHANGE_PASSWORD",
            "Enabled": False,
            "UserCreateDate": "2026-04-01",
        }

        result = _map_user(cognito_user)

        assert result["username"] == "xyz"
        assert result["email"] == ""
        assert result["enabled"] is False


class TestHandleListUsers:
    @patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TestPool"})
    def test_lists_all_users(self):
        client = MagicMock()
        client.list_users.return_value = {
            "Users": [
                {
                    "Username": "user-1",
                    "Attributes": [{"Name": "email", "Value": "a@b.com"}],
                    "UserStatus": "CONFIRMED",
                    "Enabled": True,
                    "UserCreateDate": "2026-04-01",
                },
                {
                    "Username": "user-2",
                    "Attributes": [{"Name": "email", "Value": "c@d.com"}],
                    "UserStatus": "CONFIRMED",
                    "Enabled": True,
                    "UserCreateDate": "2026-04-02",
                },
            ],
        }

        result = handle_list_users(cognito_client=client)

        assert len(result["users"]) == 2
        assert result["users"][0]["username"] == "user-1"
        assert result["users"][1]["email"] == "c@d.com"

    @patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TestPool"})
    def test_handles_pagination(self):
        client = MagicMock()
        client.list_users.side_effect = [
            {
                "Users": [
                    {
                        "Username": "user-1",
                        "Attributes": [{"Name": "email", "Value": "a@b.com"}],
                        "UserStatus": "CONFIRMED",
                        "Enabled": True,
                        "UserCreateDate": "2026-04-01",
                    },
                ],
                "PaginationToken": "token-1",
            },
            {
                "Users": [
                    {
                        "Username": "user-2",
                        "Attributes": [{"Name": "email", "Value": "c@d.com"}],
                        "UserStatus": "CONFIRMED",
                        "Enabled": True,
                        "UserCreateDate": "2026-04-02",
                    },
                ],
            },
        ]

        result = handle_list_users(cognito_client=client)

        assert len(result["users"]) == 2
        assert client.list_users.call_count == 2

    @patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TestPool"})
    def test_empty_user_pool(self):
        client = MagicMock()
        client.list_users.return_value = {"Users": []}

        result = handle_list_users(cognito_client=client)

        assert result["users"] == []


class TestHandleCreateUser:
    @patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TestPool"})
    def test_creates_user_with_email(self):
        client = MagicMock()
        client.admin_create_user.return_value = {
            "User": {
                "Username": "new-user-id",
                "Attributes": [{"Name": "email", "Value": "new@example.com"}],
                "UserStatus": "FORCE_CHANGE_PASSWORD",
                "Enabled": True,
                "UserCreateDate": "2026-04-15",
            }
        }
        client.exceptions.UsernameExistsException = type(
            "UsernameExistsException", (Exception,), {}
        )

        result = handle_create_user(
            {"email": "new@example.com"}, cognito_client=client
        )

        assert result["status"] == "created"
        assert result["user"]["email"] == "new@example.com"
        client.admin_create_user.assert_called_once_with(
            UserPoolId="us-east-1_TestPool",
            Username="new@example.com",
            UserAttributes=[
                {"Name": "email", "Value": "new@example.com"},
                {"Name": "email_verified", "Value": "true"},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )

    def test_empty_email_returns_error(self):
        result = handle_create_user({"email": ""})

        assert result["status"] == "error"
        assert "required" in result["message"]

    def test_missing_email_returns_error(self):
        result = handle_create_user({})

        assert result["status"] == "error"
        assert "required" in result["message"]

    @patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TestPool"})
    def test_duplicate_email_returns_error(self):
        client = MagicMock()
        exc_class = type("UsernameExistsException", (Exception,), {})
        client.exceptions.UsernameExistsException = exc_class
        client.admin_create_user.side_effect = exc_class()

        result = handle_create_user(
            {"email": "existing@example.com"}, cognito_client=client
        )

        assert result["status"] == "error"
        assert "already exists" in result["message"]


class TestHandleDeleteUser:
    @patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TestPool"})
    def test_deletes_user(self):
        client = MagicMock()
        client.exceptions.UserNotFoundException = type(
            "UserNotFoundException", (Exception,), {}
        )

        result = handle_delete_user(
            "target-user", "admin-user", cognito_client=client
        )

        assert result["status"] == "deleted"
        assert result["userId"] == "target-user"
        client.admin_delete_user.assert_called_once_with(
            UserPoolId="us-east-1_TestPool",
            Username="target-user",
        )

    def test_self_removal_blocked(self):
        result = handle_delete_user("admin-user", "admin-user")

        assert result["status"] == "error"
        assert "your own account" in result["message"]

    @patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TestPool"})
    def test_user_not_found_returns_error(self):
        client = MagicMock()
        exc_class = type("UserNotFoundException", (Exception,), {})
        client.exceptions.UserNotFoundException = exc_class
        client.admin_delete_user.side_effect = exc_class()

        result = handle_delete_user(
            "nonexistent-user", "admin-user", cognito_client=client
        )

        assert result["status"] == "error"
        assert "not found" in result["message"]
