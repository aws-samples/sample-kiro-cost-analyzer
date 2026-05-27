"""Integration tests for ``etl/reconcile_users_handler.py``.

Uses moto to mock DynamoDB and ``unittest.mock`` to stub the Identity
Center client (moto's ``identitystore`` support is incomplete). The
fail-safe properties (no false tombstones on IDC errors, empty list
abort) are the most important here — getting them wrong would tombstone
every user the next run.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def user_names_table():
    """Create a UserNamesTable populated with three users in different states."""
    with mock_aws():
        os.environ["IDENTITY_STORE_ID"] = "d-test"
        os.environ["USER_NAMES_TABLE"] = "TestUserNamesTable"

        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="TestUserNamesTable",
            KeySchema=[{"AttributeName": "userId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "userId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()

        # Three rows, each in a different state.
        table.put_item(Item={
            "userId": "u-active",
            "displayName": "Active User",
            "userName": "active@co",
            "status": "ACTIVE",
        })
        table.put_item(Item={
            "userId": "u-pre-feature",
            "displayName": "Pre-Feature",
            "userName": "old@co",
            # No status field — represents rows written before this feature.
        })
        table.put_item(Item={
            "userId": "u-tombstoned",
            "displayName": "Tombstoned",
            "userName": "deleted@co",
            "status": "TOMBSTONED",
            "tombstonedAt": "2026-05-01",
        })

        yield table


def _make_idc_client(user_ids: list[str]):
    """Build a mock IDC client whose paginator returns the given userIds."""
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Users": [{"UserId": uid} for uid in user_ids]}
    ]
    client.get_paginator.return_value = paginator
    return client


def _make_failing_idc_client(error_type: str = "AccessDenied"):
    """Build a mock IDC client whose paginator raises an exception."""
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.side_effect = RuntimeError(f"simulated {error_type} failure")
    client.get_paginator.return_value = paginator
    return client


# ---------------------------------------------------------------------------
# Happy-path scenarios
# ---------------------------------------------------------------------------


def test_user_in_idc_keeps_status_active(user_names_table):
    from etl.reconcile_users_handler import reconcile_users_handler

    # All three users present in IDC.
    with patch("boto3.client") as mock_boto_client:
        mock_boto_client.return_value = _make_idc_client(
            ["u-active", "u-pre-feature", "u-tombstoned"]
        )
        result = reconcile_users_handler({}, None)

    # Tombstoned user is restored — counts as "restored".
    assert result["status"] == "ok"
    assert result["restored"] == 1
    assert result["tombstoned"] == 0

    # Verify post-state on the restored row.
    item = user_names_table.get_item(Key={"userId": "u-tombstoned"})["Item"]
    assert item["status"] == "ACTIVE"
    assert "tombstonedAt" not in item
    assert "lastSeenInIdc" in item


def test_user_removed_from_idc_is_tombstoned(user_names_table):
    from etl.reconcile_users_handler import reconcile_users_handler

    # u-pre-feature has been removed from IDC but is still in our cache.
    with patch("boto3.client") as mock_boto_client:
        mock_boto_client.return_value = _make_idc_client(["u-active", "u-tombstoned"])
        result = reconcile_users_handler({}, None)

    assert result["status"] == "ok"
    assert result["tombstoned"] == 1

    # Verify the row was tombstoned but its history was preserved.
    item = user_names_table.get_item(Key={"userId": "u-pre-feature"})["Item"]
    assert item["status"] == "TOMBSTONED"
    assert item["tombstonedAt"] is not None
    assert item["displayName"] == "Pre-Feature"  # history preserved
    assert item["userName"] == "old@co"  # history preserved


def test_active_user_status_lazily_upgraded(user_names_table):
    """Pre-feature rows (no status field) get ``status="ACTIVE"`` set on
    the first reconcile. This is the lazy migration path described in
    the spec — no batch backfill needed."""
    from etl.reconcile_users_handler import reconcile_users_handler

    with patch("boto3.client") as mock_boto_client:
        mock_boto_client.return_value = _make_idc_client(
            ["u-active", "u-pre-feature", "u-tombstoned"]
        )
        reconcile_users_handler({}, None)

    item = user_names_table.get_item(Key={"userId": "u-pre-feature"})["Item"]
    assert item["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Fail-safe scenarios (Requirement 2.1, 2.2, P2)
# ---------------------------------------------------------------------------


def test_idc_error_does_not_tombstone_anyone(user_names_table):
    """Property P2: a single IDC failure must never produce a wave of
    incorrect tombstones."""
    from etl.reconcile_users_handler import reconcile_users_handler

    with patch("boto3.client") as mock_boto_client:
        mock_boto_client.return_value = _make_failing_idc_client()
        result = reconcile_users_handler({}, None)

    assert result["status"] == "error"
    assert result["reason"] == "idc-list-failed"
    assert result["tombstoned"] == 0
    assert result["restored"] == 0

    # The active row was not touched.
    item = user_names_table.get_item(Key={"userId": "u-active"})["Item"]
    assert item["status"] == "ACTIVE"
    # The pre-feature row was not touched (still has no status).
    item = user_names_table.get_item(Key={"userId": "u-pre-feature"})["Item"]
    assert "status" not in item
    # The tombstoned row was not touched.
    item = user_names_table.get_item(Key={"userId": "u-tombstoned"})["Item"]
    assert item["status"] == "TOMBSTONED"
    assert item["tombstonedAt"] == "2026-05-01"  # original date preserved


def test_empty_idc_list_does_not_tombstone_anyone(user_names_table):
    """An empty IDC tenant is far more likely to indicate a misconfigured
    query than every user being deleted simultaneously. Refuse to
    proceed."""
    from etl.reconcile_users_handler import reconcile_users_handler

    with patch("boto3.client") as mock_boto_client:
        mock_boto_client.return_value = _make_idc_client([])
        result = reconcile_users_handler({}, None)

    assert result["status"] == "skipped"
    assert result["reason"] == "idc-empty"
    assert result["tombstoned"] == 0

    # The active user was not flipped to tombstoned.
    item = user_names_table.get_item(Key={"userId": "u-active"})["Item"]
    assert item["status"] == "ACTIVE"
