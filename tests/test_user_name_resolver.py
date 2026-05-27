"""Tests for etl.user_name_resolver module.

Covers:
- ``resolve_user_names`` default-client construction when ``identity_client=None``.
- ``resolve_user_names`` with an injected cross-account client.
- AccessDenied log path — tolerant fallback to ``("", "")`` plus a log record
  containing the userId and the Identity_Store_Role permission hint.

Feature: cross-account-identity-center (task 4.3).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from etl.user_name_resolver import resolve_user_names


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _make_dynamodb_stub(existing_items: dict | None = None):
    """Build a MagicMock that behaves like ``boto3.resource('dynamodb')``.

    ``get_item`` returns the cached entry when present, otherwise ``{}``.
    ``put_item`` is a no-op capture so tests can assert on cache writes.
    """
    existing_items = existing_items or {}
    table = MagicMock()

    def _get_item(Key):
        user_id = Key["userId"]
        if user_id in existing_items:
            return {"Item": existing_items[user_id]}
        return {}

    table.get_item.side_effect = _get_item
    table.put_item.return_value = None

    dynamodb = MagicMock()
    dynamodb.Table.return_value = table
    return dynamodb, table


# ---------------------------------------------------------------------------
# Default-client construction when identity_client=None
# ---------------------------------------------------------------------------


class TestResolveUserNamesBuildsDefaultClient:
    """When ``identity_client is None`` the resolver must build a default
    ``boto3.client('identitystore')`` (Requirement 4.4 — single-account
    fallback)."""

    def test_default_identity_client_built_when_none(self):
        dynamodb, table = _make_dynamodb_stub()

        fake_identity = MagicMock()
        fake_identity.describe_user.return_value = {
            "DisplayName": "Alice Example",
            "UserName": "alice",
        }

        with patch("etl.user_name_resolver.boto3") as mock_boto3:
            mock_boto3.client.return_value = fake_identity

            result = resolve_user_names(
                user_ids={"user-1"},
                identity_store_id="d-1234567890",
                table_name="UserNamesTable",
                dynamodb=dynamodb,
                identity_client=None,
            )

        # boto3.client('identitystore') was called exactly once
        mock_boto3.client.assert_called_once_with("identitystore")
        # and the resulting client was used for DescribeUser
        fake_identity.describe_user.assert_called_once_with(
            IdentityStoreId="d-1234567890",
            UserId="user-1",
        )
        assert result == {"user-1": ("Alice Example", "alice")}
        # Cache write happened
        table.put_item.assert_called_once()


# ---------------------------------------------------------------------------
# Injected identity_client path — only the injected client is used
# ---------------------------------------------------------------------------


class TestResolveUserNamesUsesInjectedClient:
    """When an ``identity_client`` is injected, the resolver MUST use it
    verbatim and MUST NOT construct a default ``boto3.client('identitystore')``
    (Requirement 4.2 — cross-account client used as-is)."""

    def test_injected_client_is_used_and_boto3_never_called(self):
        dynamodb, table = _make_dynamodb_stub()

        injected = MagicMock()
        injected.describe_user.return_value = {
            "DisplayName": "Bob Cross-Account",
            "UserName": "bob",
        }

        with patch("etl.user_name_resolver.boto3") as mock_boto3:
            result = resolve_user_names(
                user_ids={"user-2"},
                identity_store_id="d-cross-account",
                table_name="UserNamesTable",
                dynamodb=dynamodb,
                identity_client=injected,
            )

        # The injected client's describe_user was the only one called
        injected.describe_user.assert_called_once_with(
            IdentityStoreId="d-cross-account",
            UserId="user-2",
        )
        # And boto3.client("identitystore") was never invoked — the injection
        # seam must be transparent.
        for call in mock_boto3.client.call_args_list:
            assert call.args[:1] != ("identitystore",), (
                f"Default identitystore client was built despite injection: {call}"
            )

        assert result == {"user-2": ("Bob Cross-Account", "bob")}

    def test_injected_client_used_for_every_userid(self):
        """Each userId in the batch goes through the injected client only."""
        dynamodb, _table = _make_dynamodb_stub()

        injected = MagicMock()
        injected.describe_user.side_effect = [
            {"DisplayName": "Alice", "UserName": "alice"},
            {"DisplayName": "Bob", "UserName": "bob"},
            {"DisplayName": "Carol", "UserName": "carol"},
        ]

        with patch("etl.user_name_resolver.boto3") as mock_boto3:
            resolve_user_names(
                user_ids={"u-alice", "u-bob", "u-carol"},
                identity_store_id="d-xa",
                table_name="UserNamesTable",
                dynamodb=dynamodb,
                identity_client=injected,
            )

        assert injected.describe_user.call_count == 3
        # boto3.client("identitystore") must not have been called
        assert all(
            call.args[:1] != ("identitystore",)
            for call in mock_boto3.client.call_args_list
        )


# ---------------------------------------------------------------------------
# AccessDenied log path — userId + hint, tolerant ("", "") return
# ---------------------------------------------------------------------------


class TestResolveUserNamesAccessDeniedLogging:
    """AccessDenied on ``DescribeUser`` must emit a log record that includes the
    userId and the Identity_Store_Role permission hint, and the function must
    still return ``("", "")`` for that userId (Requirements 7.5, 8.2)."""

    def test_access_denied_logs_user_id_and_hint_and_returns_empty(self, caplog):
        dynamodb, _table = _make_dynamodb_stub()

        injected = MagicMock()
        injected.describe_user.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": "User is not authorized to perform identitystore:DescribeUser",
                }
            },
            operation_name="DescribeUser",
        )

        caplog.set_level(logging.WARNING, logger="etl.user_name_resolver")

        result = resolve_user_names(
            user_ids={"denied-user"},
            identity_store_id="d-xa",
            table_name="UserNamesTable",
            dynamodb=dynamodb,
            identity_client=injected,
        )

        # Tolerant fallback: returns ("", "") for the denied userId
        assert result == {"denied-user": ("", "")}

        # One or more warning records were emitted
        access_denied_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and r.name == "etl.user_name_resolver"
        ]
        assert access_denied_records, (
            "Expected at least one WARNING log record for the AccessDenied path"
        )

        # At least one record must include the userId AND the permission hint
        combined = "\n".join(r.getMessage() for r in access_denied_records)
        assert "denied-user" in combined, (
            f"Expected userId 'denied-user' in log output; got: {combined!r}"
        )
        assert "identitystore:DescribeUser" in combined, (
            f"Expected 'identitystore:DescribeUser' hint in log output; got: {combined!r}"
        )
        assert "IDC account" in combined, (
            f"Expected the IDC-account hint phrase in log output; got: {combined!r}"
        )

    def test_access_denied_does_not_write_cache(self, caplog):
        """A failed resolution must not poison the cache with empty strings."""
        dynamodb, table = _make_dynamodb_stub()

        injected = MagicMock()
        injected.describe_user.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": "denied",
                }
            },
            operation_name="DescribeUser",
        )

        caplog.set_level(logging.WARNING, logger="etl.user_name_resolver")

        resolve_user_names(
            user_ids={"u-denied"},
            identity_store_id="d-xa",
            table_name="UserNamesTable",
            dynamodb=dynamodb,
            identity_client=injected,
        )

        # No cache write on AccessDenied
        table.put_item.assert_not_called()
